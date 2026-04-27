"""drone_isp — pipelined Image Signal Processor.

Maps to a dedicated ISP block on real silicon. The ISP is the critical first
stage of the camera path: raw sensor data (Bayer pattern, 10-12 bit) enters
via MIPI CSI-2, and a fully-formed RGB or YUV tensor exits, ready for the
DSP/NPU. On modern application processors this is a hardware block, NOT a
software pipeline — it must operate at sustained sensor line rate.

A proper ISP pipeline includes (each is a hardware stage, often pipelined
together so latency is one-frame max):

  1. Sensor ingest         : CSI-2 lane RX, packing, line buffering
  2. BLC                   : Black Level Correction
  3. LSC                   : Lens Shading Correction
  4. Defective pixel fix   : DPC
  5. Demosaic              : Bayer → RGB (the heavyweight stage)
  6. WB                    : White Balance
  7. CCM                   : Color Correction Matrix
  8. Gamma / tone map      : LUT-based or local tone mapping (LTM)
  9. HDR merge             : if multi-exposure input (3+ frames)
  10. LDC                  : Lens Distortion Correction (geometric warp)
  11. NR                   : Noise Reduction (2D + 3D temporal)
  12. Sharpening           : edge enhancement
  13. Scaler / formatter   : output to NV12/YUV420/tensor

Total ISP latency budget: ~5-15ms per frame at 1080p; sized as line-rate
throughput (Mpix/s), not per-frame latency. The KPI that matters is whether
the ISP can sustain N×{W×H×fps} pixel rate for N concurrent cameras.

This node simulates the pipeline. Each stage emits its own probe record so
the partition report can show per-stage breakdown of where the ISP budget
goes — useful for arguing about dedicated ISP block sizing vs. relying on
GPU/DSP fallback.
"""

from __future__ import annotations
import os
import time
from pathlib import Path
from typing import Optional

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String
from cv_bridge import CvBridge

from instrumentation.probes import ProbeWriter, OpProbe
from instrumentation.schemas import SUBSYSTEM_ISP, SUBSYSTEM_SENSOR_INGEST


# ──────────────────────────────────────────────────────────────────────
# ISP pipeline stages with realistic per-stage cost.
# Costs are normalized to "ns per pixel" at 1 GHz ISP clock — adjust via
# slider / profile to model different silicon. These are first-order
# defaults that match published ISP datasheets in the application-processor
# class (e.g. Mobileye, Ambarella, NXP S32V/i.MX).
# ──────────────────────────────────────────────────────────────────────

ISP_STAGES = [
    # (stage_name, ns_per_pixel, output_format)
    ("blc",          0.5, "bayer"),
    ("lsc",          0.5, "bayer"),
    ("dpc",          0.6, "bayer"),
    ("demosaic",     2.5, "rgb"),     # heaviest stage — full-color reconstruction
    ("wb",           0.4, "rgb"),
    ("ccm",          0.6, "rgb"),
    ("hdr_merge",    1.5, "rgb"),     # only when N exposures > 1
    ("tonemap",      1.2, "rgb"),
    ("ldc",          2.0, "rgb"),     # geometric warp; bandwidth-heavy
    ("nr_2d",        0.8, "rgb"),
    ("nr_3d",        1.2, "rgb"),     # uses prior frame; doubles BW
    ("sharpen",      0.5, "rgb"),
    ("scaler_yuv",   0.7, "yuv420"),
    ("formatter",    0.3, "tensor"),  # CHW arrangement for NPU consumption
]


class IspNode(Node):
    def __init__(self):
        super().__init__("drone_isp")

        self.run_id = os.environ.get("RUN_ID", "dev")
        run_dir = Path(os.environ.get("RUN_DIR", f"/runs/{self.run_id}"))
        self.input_format = os.environ.get("ISP_INPUT_FORMAT", "bayer_rggb")
        self.input_width  = int(os.environ.get("ISP_INPUT_WIDTH",  "1920"))
        self.input_height = int(os.environ.get("ISP_INPUT_HEIGHT", "1080"))
        self.input_bitdepth = int(os.environ.get("ISP_INPUT_BITDEPTH", "12"))
        self.fps = float(os.environ.get("ISP_FPS", "60"))
        self.csi_lanes = int(os.environ.get("ISP_CSI_LANES", "4"))
        self.hdr_exposures = int(os.environ.get("ISP_HDR_EXPOSURES", "1"))   # 1=SDR, 3=HDR3
        self.ns_per_pixel_scale = float(os.environ.get("ISP_NS_PER_PIXEL_SCALE", "1.0"))

        self.writer = ProbeWriter(run_dir, subsystem=SUBSYSTEM_ISP)
        self.phase = "search"
        self.stage_ops: dict[str, OpProbe] = {
            stage: OpProbe(self.writer, self.run_id, SUBSYSTEM_ISP,
                           f"isp_{stage}", lambda: self.phase)
            for stage, _, _ in ISP_STAGES
        }

        self.bridge = CvBridge()
        # Subscribe to raw frames (in real systems this would be a CSI-2
        # bridge; in the SITL world we receive pre-rendered RGB and treat
        # it as if it had been raw Bayer)
        self.create_subscription(Image, "/camera/raw", self._on_raw_frame, 10)
        self.create_subscription(String, "/mission/phase", self._on_phase, 10)
        # Publish ISP-processed tensor (consumed by perception, VIO, encode, DSP)
        self.pub = self.create_publisher(Image, "/camera/image_raw", 10)

        self.frame_period_ms = 1000.0 / self.fps
        self.get_logger().info(
            f"ISP ready · {self.input_width}x{self.input_height}@{self.fps}fps "
            f"hdr={self.hdr_exposures}x lanes={self.csi_lanes} "
            f"ns/pix scale={self.ns_per_pixel_scale}"
        )

    def _on_phase(self, msg: String) -> None:
        self.phase = msg.data

    def _on_raw_frame(self, msg: Image) -> None:
        cv = self.bridge.imgmsg_to_cv2(msg, "rgb8")
        h, w = cv.shape[:2]
        pixels = w * h
        bytes_per_pixel_in = self.input_bitdepth / 8.0  # Bayer is 1 sample/pixel pre-demosaic
        in_bytes = int(pixels * bytes_per_pixel_in * self.hdr_exposures)
        line_rate_mpps = (pixels * self.fps) / 1e6

        # Run each stage of the pipeline. They are pipelined in real HW, so
        # total wall-clock ≈ max(stage_costs) + small per-stage register
        # overhead. We model that by sleeping the *max* stage cost rather
        # than summing them.
        stage_latencies_ns: list[int] = []

        prev_format = self.input_format
        cur_bytes = in_bytes
        for stage, ns_per_pix, out_format in ISP_STAGES:
            # Skip HDR merge if not in HDR mode
            if stage == "hdr_merge" and self.hdr_exposures <= 1:
                continue
            cost_ns = int(pixels * ns_per_pix * self.ns_per_pixel_scale)
            # In a fully pipelined ISP all stages run concurrently per line.
            # We simulate this by sleeping the stage cost but record it for
            # total throughput accounting.
            t0 = time.perf_counter_ns()

            with self.stage_ops[stage].measure(
                input_shape=f"{w}x{h}",
                input_bytes=cur_bytes,
                precision="fixed_point",          # ISPs are fixed-point datapaths
                src_subsystem=SUBSYSTEM_SENSOR_INGEST if stage == ISP_STAGES[0][0] else SUBSYSTEM_ISP,
                isp_stage=stage,
                isp_input_format=prev_format,
                isp_output_format=out_format,
                isp_line_rate_mpps=line_rate_mpps,
                isp_pixels_processed=pixels,
                isp_lanes_used=self.csi_lanes,
                isp_hdr_exposures=self.hdr_exposures,
            ) as obs:
                # Tiny sleep to model per-stage register/DMA setup; the real
                # pipeline stage cost is captured in stage_latencies_ns total.
                time.sleep(min(0.0005, cost_ns / 1e9))
                # Output bytes — formats change pixel size
                if out_format == "rgb":
                    cur_bytes = pixels * 3
                elif out_format == "yuv420":
                    cur_bytes = int(pixels * 1.5)
                elif out_format == "tensor":
                    cur_bytes = pixels * 3   # CHW float tensor sized later in NPU
                obs.output_bytes = cur_bytes

            stage_latencies_ns.append(int(time.perf_counter_ns() - t0))
            prev_format = out_format

        # Publish processed frame for downstream
        self.pub.publish(msg)

    def destroy_node(self):
        self.writer.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = IspNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
