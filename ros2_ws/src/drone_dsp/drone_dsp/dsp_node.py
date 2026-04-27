"""drone_dsp — Cadence Vision Q-class DSP workloads.

Maps to dedicated vision DSP(s) on real silicon. The Cadence Tensilica Vision
Q-series (Q6, Q7, Q8) are the de facto standard for "classical CV that has
to run before AI" — Gaussian/Laplacian pyramids, dense optical flow init,
HDR merge, lens distortion correction, panorama stitch front-ends, and
stereo disparity pre-passes. They run at ~1 GHz with very wide SIMD (512 or
1024-bit) and excel at fixed-point convolution-heavy kernels that map
poorly to NPU MAC arrays (small kernels, irregular access patterns) and
poorly to general CPU (massive parallel data).

Why NOT just push everything to the NPU:
  - NPUs are optimized for large dense GEMM/conv. Pyramid construction is
    a sequence of small (3x3 or 5x5) Gaussian + downsample passes — high
    arithmetic intensity but low data reuse, NPU efficiency drops to ~20%.
  - Some operations (geometric warps, distortion correction) need bilinear
    interpolation with arbitrary memory access patterns. Cadence DSPs have
    purpose-built address-generation units for exactly this.
  - Latency: pyramid output feeds VIO at fixed wall-clock budget. DSPs
    deliver predictable cycle counts; NPU latency depends on kernel queue
    state.

Why NOT just CPU:
  - 4MP image × 5-level Gaussian pyramid × 30fps is hundreds of GOPs. A
    cluster of A720 cores would burn 4-6 cores on it. DSP at 1 GHz with
    1024-bit SIMD does it on one tile.

Typical Cadence Vision Q-class workloads modeled here:
  - pyramid_build       : Gaussian pyramid 5 levels (input → /32)
  - pyramid_laplacian   : Laplacian pyramid (DoG variant)
  - dense_optical_flow_init  : feature pre-warp / pyramid for L-K flow
  - hdr_merge_ghost_corr : multi-exposure align + ghost detect
  - lens_distortion     : geometric warp + bilinear interp
  - panorama_align      : ECC-style alignment for multi-cam stitch
  - feature_pre         : ORB/FAST keypoint detection front-end (before
                          NN-based matcher on NPU)

Sized as: cycles per pixel × pixels × fps / clock_mhz / simd_lanes → DSP
utilization fraction. The KPI is whether the DSP can sustain the workload
without dropping frames.
"""

from __future__ import annotations
import os
import time
from pathlib import Path

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String
from cv_bridge import CvBridge

from ratchet.probes import ProbeWriter, OpProbe
from instrumentation.subsystems import SUBSYSTEM_DSP, SUBSYSTEM_ISP, SUBSYSTEM_PERCEPTION


# ──────────────────────────────────────────────────────────────────────
# DSP workload definitions.
#
# cycles_per_pixel = SIMD-effective cycles per output pixel for the kernel.
# pyramid_factor   = scale factor for total pixels touched (5-level gaussian
#                    pyramid touches ~1.33× input pixels because of the
#                    geometric series 1 + 1/4 + 1/16 + ... ≈ 4/3).
#
# These constants are first-order. Replace with measured values from the
# real DSP toolchain (Cadence Xtensa Xplorer / xt-clang -mlongcalls
# emits cycle-accurate counts at compile time).
# ──────────────────────────────────────────────────────────────────────

DSP_OPS = {
    "pyramid_gaussian": {
        "cycles_per_output_pixel": 6,
        "pixel_count_factor": 1.33,     # 5-level pyramid touches 4/3 of input
        "pyramid_levels": 5,
        "kernel_size": 5,
    },
    "pyramid_laplacian": {
        "cycles_per_output_pixel": 9,
        "pixel_count_factor": 1.33,
        "pyramid_levels": 5,
        "kernel_size": 5,
    },
    "lens_distortion": {
        "cycles_per_output_pixel": 12,  # bilinear interp + complex addressing
        "pixel_count_factor": 1.0,
        "pyramid_levels": 0,
        "kernel_size": 0,
    },
    "hdr_merge": {
        "cycles_per_output_pixel": 18,  # 3-exposure align + tonemap blend
        "pixel_count_factor": 3.0,      # touches all 3 exposures
        "pyramid_levels": 0,
        "kernel_size": 3,
    },
    "optical_flow_init": {
        "cycles_per_output_pixel": 15,
        "pixel_count_factor": 1.33,     # operates on pyramid
        "pyramid_levels": 4,
        "kernel_size": 7,
    },
    "feature_pre": {
        "cycles_per_output_pixel": 4,   # FAST + Harris response
        "pixel_count_factor": 1.0,
        "pyramid_levels": 0,
        "kernel_size": 9,
    },
}


class DspNode(Node):
    """Simulates DSP workloads. Subscribes to ISP-processed frames, runs the
    configured pipeline of DSP operations, publishes outputs (pyramids,
    flow fields, undistorted frames) to downstream consumers."""

    def __init__(self):
        super().__init__("drone_dsp")

        self.run_id = os.environ.get("RUN_ID", "dev")
        run_dir = Path(os.environ.get("RUN_DIR", f"/runs/{self.run_id}"))

        # Configuration
        self.dsp_clock_mhz = float(os.environ.get("DSP_CLOCK_MHZ", "1000"))
        self.dsp_simd_lanes = int(os.environ.get("DSP_SIMD_LANES", "16"))    # 512-bit / 32-bit lanes
        # Comma-separated list of ops to run per frame.
        # Default approximates: undistort → pyramid → optical flow init.
        ops_str = os.environ.get("DSP_OPS", "lens_distortion,pyramid_gaussian,optical_flow_init")
        self.ops = [o.strip() for o in ops_str.split(",") if o.strip() in DSP_OPS]

        self.writer = ProbeWriter(run_dir, subsystem=SUBSYSTEM_DSP)
        self.phase = "search"
        self.op_probes = {
            op: OpProbe(self.writer, self.run_id, SUBSYSTEM_DSP,
                        f"dsp_{op}", lambda: self.phase)
            for op in self.ops
        }

        self.bridge = CvBridge()
        self.create_subscription(Image, "/camera/image_raw", self._on_frame, 10)
        self.create_subscription(String, "/mission/phase", self._on_phase, 10)
        self.pyramid_pub = self.create_publisher(Image, "/dsp/pyramid_l0", 10)

        self.get_logger().info(
            f"DSP ready · clock={self.dsp_clock_mhz}MHz lanes={self.dsp_simd_lanes} "
            f"ops={self.ops}"
        )

    def _on_phase(self, msg: String) -> None:
        self.phase = msg.data

    def _on_frame(self, msg: Image) -> None:
        cv = self.bridge.imgmsg_to_cv2(msg, "rgb8")
        h, w = cv.shape[:2]
        pixels = w * h

        for op_name in self.ops:
            cfg = DSP_OPS[op_name]
            total_pixels = int(pixels * cfg["pixel_count_factor"])
            # cycles = total_pixels × cycles_per_pixel / SIMD lanes
            # (lanes is how many output pixels we produce per cycle)
            cycles = (total_pixels * cfg["cycles_per_output_pixel"]) // self.dsp_simd_lanes
            wall_ns = int((cycles / self.dsp_clock_mhz) * 1000)   # MHz → ns

            # Determine downstream consumer
            if op_name == "lens_distortion":
                dst = SUBSYSTEM_DSP   # next DSP op consumes
            elif op_name in ("pyramid_gaussian", "pyramid_laplacian"):
                dst = "vio"
            elif op_name == "optical_flow_init":
                dst = "vio"
            elif op_name == "feature_pre":
                dst = SUBSYSTEM_PERCEPTION
            else:
                dst = SUBSYSTEM_PERCEPTION

            with self.op_probes[op_name].measure(
                input_shape=f"{w}x{h}",
                input_bytes=pixels * 3,
                precision="fixed_point",
                src_subsystem=SUBSYSTEM_ISP,
                dst_subsystem=dst,
                dsp_op=op_name,
                dsp_pyramid_levels=cfg["pyramid_levels"],
                dsp_kernel_size=cfg["kernel_size"],
                dsp_simd_lanes=self.dsp_simd_lanes,
                dsp_cycles=cycles,
                dsp_clock_mhz=self.dsp_clock_mhz,
            ) as obs:
                # Sleep the modeled wall time, capped to keep ROS responsive
                time.sleep(min(0.040, wall_ns / 1e9))
                # Output bytes depend on op
                if op_name == "pyramid_gaussian":
                    obs.output_bytes = int(pixels * 3 * 1.33)   # all pyramid levels
                elif op_name == "pyramid_laplacian":
                    obs.output_bytes = int(pixels * 3 * 1.33)
                elif op_name == "lens_distortion":
                    obs.output_bytes = pixels * 3
                elif op_name == "optical_flow_init":
                    obs.output_bytes = pixels * 4 * 2  # 2D flow field × float
                elif op_name == "feature_pre":
                    obs.output_bytes = 1000 * 32       # ~1000 keypoints × 32B
                elif op_name == "hdr_merge":
                    obs.output_bytes = pixels * 3

        # Publish pyramid level 0 for VIO to consume
        self.pyramid_pub.publish(msg)

    def destroy_node(self):
        self.writer.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = DspNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
