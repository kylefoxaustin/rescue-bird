"""drone_vio — visual-inertial odometry node.

Maps to GPU + NPU + ARM on real silicon. The reason VIO matters separately from
perception is that it has very different bandwidth characteristics: it consumes
both camera frames AND high-rate IMU data, runs feature extraction on GPU, and
emits pose at 50-200 Hz. The probe data here is what justifies (or doesn't)
giving the NPU dedicated DRAM channels vs. sharing with perception.

Real implementations to consider plugging in:
  - Isaac ROS Visual SLAM (cuVSLAM)         — GPU-heavy, NPU optional
  - VINS-Fusion / OpenVINS                  — CPU-bound, useful as baseline
  - Kimera-VIO                              — mixed
"""

from __future__ import annotations
import os
import time
from pathlib import Path

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, Imu
from geometry_msgs.msg import PoseStamped
from cv_bridge import CvBridge

from ratchet.probes import ProbeWriter, OpProbe, GpuProbe
from instrumentation.subsystems import (
    SUBSYSTEM_VIO, SUBSYSTEM_FLIGHT_CONTROL, SUBSYSTEM_SENSOR_INGEST,
)


class VioNode(Node):
    def __init__(self):
        super().__init__("drone_vio")

        self.run_id = os.environ.get("RUN_ID", "dev")
        run_dir = Path(os.environ.get("RUN_DIR", f"/runs/{self.run_id}"))

        self.writer = ProbeWriter(run_dir, subsystem=SUBSYSTEM_VIO)
        self.phase = "search"
        self.feat_op = OpProbe(self.writer, self.run_id, SUBSYSTEM_VIO,
                               "feature_extract", lambda: self.phase)
        self.opt_op = OpProbe(self.writer, self.run_id, SUBSYSTEM_VIO,
                              "pose_optimize", lambda: self.phase)
        self.gpu = GpuProbe(self.writer, self.run_id, SUBSYSTEM_VIO,
                            phase_provider=lambda: self.phase)
        self.gpu.start()

        self.bridge = CvBridge()
        self.create_subscription(Image, "/camera/image_raw", self._on_frame, 10)
        self.create_subscription(Imu, "/imu/data", self._on_imu, 100)
        self.pose_pub = self.create_publisher(PoseStamped, "/vio/pose", 50)

        self._last_pose = np.zeros(7, dtype=np.float32)
        self._imu_count = 0

    def _on_imu(self, msg: Imu) -> None:
        self._imu_count += 1
        # IMU integration is cheap CPU work; we only sample-instrument it
        # to capture the rate, not per-message latency.

    def _on_frame(self, msg: Image) -> None:
        cv = self.bridge.imgmsg_to_cv2(msg, "mono8")
        h, w = cv.shape[:2]
        shape = f"1x1x{h}x{w}"

        # Stage 1: feature extraction (GPU-heavy in real impls)
        with self.feat_op.measure(
            input_shape=shape, input_bytes=cv.nbytes,
            precision="fp16", macs=2_000_000_000,
            src_subsystem=SUBSYSTEM_SENSOR_INGEST,
        ) as obs:
            time.sleep(0.008)  # stub
            obs.output_bytes = 200 * 256 * 4   # ~200 features × 256-d descriptor
            obs.output_shape = "200x256"

        # Stage 2: bundle adjustment / pose optimization (CPU/GPU mixed)
        with self.opt_op.measure(
            input_bytes=200 * 256 * 4,
            precision="fp32",
            dst_subsystem=SUBSYSTEM_FLIGHT_CONTROL,
        ) as obs:
            time.sleep(0.004)
            obs.output_bytes = 7 * 4
            obs.output_shape = "7"

        # Publish a pose
        p = PoseStamped()
        p.header.stamp = msg.header.stamp
        p.header.frame_id = "odom"
        self.pose_pub.publish(p)

    def destroy_node(self):
        self.gpu.stop()
        self.writer.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = VioNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
