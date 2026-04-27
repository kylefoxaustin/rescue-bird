"""drone_perception — target detection / segmentation node.

This is the workload that drives NPU sizing in the partitioning report. It runs
SAM2 / EdgeTAM / YOLOv8 against the simulated camera feed and emits detections
to /perception/detections.

Real silicon implication: every measurement this node emits with subsystem=
'perception' becomes a row in the SoC report. The MAC count per inference + the
latency p99 + input/output tensor sizes are sufficient to size the NPU and the
NoC bandwidth from sensor_ingest → perception → behavior.

The model is loaded once at startup. Precision is set via $MODEL_PRECISION
(bf16|fp16|int8) so a single mission run can exercise multiple precisions if
you re-run with different env values.
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

from ratchet.probes import ProbeWriter, OpProbe, GpuProbe
from instrumentation.subsystems import (
    SUBSYSTEM_PERCEPTION, SUBSYSTEM_BEHAVIOR, SUBSYSTEM_SENSOR_INGEST,
)


# ──────── MAC counts per model (fill in real values from torchinfo / fvcore) ────────
# These are placeholders. Replace with measured GMAC values after model conversion.
MODEL_MACS = {
    ("edgetam", "1024x1024"): 12_500_000_000,
    ("sam2",    "1024x1024"): 145_000_000_000,
    ("yolov8",  "640x640"):     3_200_000_000,
}


class PerceptionNode(Node):
    def __init__(self):
        super().__init__("drone_perception")

        self.run_id = os.environ.get("RUN_ID", "dev")
        run_dir = Path(os.environ.get("RUN_DIR", f"/runs/{self.run_id}"))
        self.precision = os.environ.get("MODEL_PRECISION", "bf16")
        self.model_name = os.environ.get("MODEL_NAME", "edgetam")

        self.writer = ProbeWriter(run_dir, subsystem=SUBSYSTEM_PERCEPTION)
        self.phase = "search"   # behavior node will publish updates to /mission/phase
        self.op = OpProbe(self.writer, self.run_id, SUBSYSTEM_PERCEPTION,
                          operation=f"{self.model_name}_infer",
                          phase_provider=lambda: self.phase)
        self.gpu = GpuProbe(self.writer, self.run_id, SUBSYSTEM_PERCEPTION,
                            phase_provider=lambda: self.phase)
        self.gpu.start()

        self.bridge = CvBridge()
        self.sub = self.create_subscription(
            Image, "/camera/image_raw", self._on_frame, 10,
        )
        self.pub = self.create_publisher(String, "/perception/detections", 10)
        self.phase_sub = self.create_subscription(
            String, "/mission/phase", self._on_phase, 10,
        )

        self._model = self._load_model()
        self.get_logger().info(
            f"perception ready · model={self.model_name} precision={self.precision}"
        )

    # ─── Model loading is split out so swapping in real weights is trivial ───
    def _load_model(self):
        # TODO: replace stub with real TensorRT engine or torch.compile model.
        #
        # For SAM2 / EdgeTAM:
        #   from sam2.build_sam import build_sam2
        #   model = build_sam2(cfg, ckpt).to(dtype=torch.bfloat16, device="cuda")
        #
        # For YOLOv8:
        #   from ultralytics import YOLO
        #   model = YOLO("yolov8n.pt")
        #
        # The point of this scaffold is to wire instrumentation correctly.
        # Wire in the real model once you've decided which one to characterize.
        return _StubModel(self.model_name, self.precision)

    def _on_phase(self, msg: String) -> None:
        self.phase = msg.data

    def _on_frame(self, msg: Image) -> None:
        cv = self.bridge.imgmsg_to_cv2(msg, "rgb8")
        h, w = cv.shape[:2]
        shape = f"1x3x{h}x{w}"
        in_bytes = cv.nbytes
        macs = MODEL_MACS.get((self.model_name, f"{h}x{w}"))

        with self.op.measure(
            input_shape=shape,
            input_bytes=in_bytes,
            precision=self.precision,
            macs=macs,
            src_subsystem=SUBSYSTEM_SENSOR_INGEST,
            dst_subsystem=SUBSYSTEM_BEHAVIOR,
        ) as obs:
            detections = self._model.infer(cv)
            obs.output_bytes = sum(d.nbytes for d in detections) if detections else 0
            obs.output_shape = f"{len(detections)}xdet"

        # Publish detections so behavior node can act on them
        out = String()
        out.data = f"detections={len(detections)}"
        self.pub.publish(out)

    def destroy_node(self):
        self.gpu.stop()
        self.writer.close()
        super().destroy_node()


class _StubModel:
    """Placeholder model. Sleeps to imitate inference cost so probes capture
    plausible latency until a real model is wired in."""
    def __init__(self, name: str, precision: str):
        self.name = name
        self.precision = precision
        # Calibration: a guess at "typical" GPU latency at this size+precision.
        # Replace with measured values once the real model is hooked in.
        self._cost_ms = {
            "edgetam":  18.0 if precision == "bf16" else 16.0,
            "sam2":    140.0 if precision == "bf16" else 120.0,
            "yolov8":    6.0 if precision == "bf16" else  5.0,
        }.get(name, 20.0)

    def infer(self, frame: np.ndarray) -> list[np.ndarray]:
        time.sleep(self._cost_ms / 1000.0)
        # Pretend we found some detections.
        return [np.zeros((4,), dtype=np.float32)]


def main(args=None):
    rclpy.init(args=args)
    node = PerceptionNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
