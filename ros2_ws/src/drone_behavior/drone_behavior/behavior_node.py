"""drone_behavior — mission state machine + target tracking + flight commands.

Maps to ARM application core on real silicon. Light compute, but the latency
floor of detect→track→command lives here. The probe data quantifies how much
ARM headroom is needed even after offloading perception to the NPU.

The node:
  - Loads a mission YAML
  - Publishes /mission/phase so other nodes can tag their records
  - Consumes /perception/detections and /vio/pose
  - Sends MAVLink setpoints via mavros (or pymavlink direct)
  - Runs a simple py_trees-style behavior tree
"""

from __future__ import annotations
import os
import time
import yaml
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from geometry_msgs.msg import PoseStamped

from ratchet.probes import ProbeWriter, OpProbe
from instrumentation.subsystems import (
    SUBSYSTEM_BEHAVIOR, PHASE_IDLE, PHASE_SEARCH, PHASE_ACQUIRE, PHASE_TRACK, PHASE_RTH,
)


class BehaviorNode(Node):
    def __init__(self):
        super().__init__("drone_behavior")

        self.run_id = os.environ.get("RUN_ID", "dev")
        run_dir = Path(os.environ.get("RUN_DIR", f"/runs/{self.run_id}"))
        mission_path = os.environ.get("MISSION", "/opt/missions/search_pattern.yaml")

        self.writer = ProbeWriter(run_dir, subsystem=SUBSYSTEM_BEHAVIOR)
        self.phase = PHASE_IDLE
        self.tick_op = OpProbe(self.writer, self.run_id, SUBSYSTEM_BEHAVIOR,
                               "fsm_tick", lambda: self.phase)

        # Mission
        self.mission = yaml.safe_load(Path(mission_path).read_text())
        self.get_logger().info(f"loaded mission: {self.mission.get('name')}")

        # Pubs/subs
        self.phase_pub = self.create_publisher(String, "/mission/phase", 10)
        self.cmd_pub = self.create_publisher(PoseStamped, "/setpoint/pose", 10)
        self.create_subscription(String, "/perception/detections", self._on_detections, 10)
        self.create_subscription(PoseStamped, "/vio/pose", self._on_pose, 10)

        # State
        self.detections_seen = 0
        self.detections_in_window = 0
        self._last_window_t = time.time()
        self.last_pose: PoseStamped | None = None

        # Tick loop drives the FSM
        self.create_timer(0.05, self._tick)   # 20 Hz

    def _on_detections(self, msg: String) -> None:
        # Stub: real impl would parse a Detections msg
        if "detections=" in msg.data:
            n = int(msg.data.split("=")[1])
            self.detections_seen += n
            self.detections_in_window += n

    def _on_pose(self, msg: PoseStamped) -> None:
        self.last_pose = msg

    def _tick(self) -> None:
        with self.tick_op.measure(precision="fp32"):
            self._fsm_step()
            self._publish_phase()

    def _fsm_step(self) -> None:
        # Window decay so detections_in_window represents recent activity
        now = time.time()
        if now - self._last_window_t > 1.0:
            self.detections_in_window = 0
            self._last_window_t = now

        if self.phase == PHASE_IDLE:
            self.phase = PHASE_SEARCH
        elif self.phase == PHASE_SEARCH:
            if self.detections_in_window >= 3:
                self.phase = PHASE_ACQUIRE
        elif self.phase == PHASE_ACQUIRE:
            if self.detections_in_window >= 10:
                self.phase = PHASE_TRACK
            elif self.detections_in_window == 0:
                self.phase = PHASE_SEARCH
        elif self.phase == PHASE_TRACK:
            if self.detections_in_window == 0:
                self.phase = PHASE_ACQUIRE  # lost lock, try to reacquire

    def _publish_phase(self) -> None:
        m = String()
        m.data = self.phase
        self.phase_pub.publish(m)

    def destroy_node(self):
        self.writer.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = BehaviorNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
