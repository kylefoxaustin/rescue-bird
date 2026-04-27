"""drone_telemetry — instrumentation aggregator.

This node is host-only — it does NOT correspond to a block on the deployed SoC.
Its job is to:

  1. Periodically print a live summary of subsystem activity (so you can watch
     a mission scenario unfold and see the FSM phase changes + GPU draw).
  2. Sample host-level system metrics (CPU%, RSS) for cross-checking.
  3. Emit a final manifest.json into the run directory describing which env
     vars / model / link profile / mission were active for this run, so the
     analysis script can group runs sensibly.

If you want extra fidelity, point Nsight Systems at the perception container
during a run — its trace lines up timestamp-wise with our Parquet records.
"""

from __future__ import annotations
import json
import os
import time
from pathlib import Path

import psutil
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class TelemetryNode(Node):
    def __init__(self):
        super().__init__("drone_telemetry")

        self.run_id = os.environ.get("RUN_ID", "dev")
        self.run_dir = Path(os.environ.get("RUN_DIR", f"/runs/{self.run_id}"))
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.phase = "idle"
        self.create_subscription(String, "/mission/phase", self._on_phase, 10)

        # Write run manifest immediately so it's there even if the run crashes
        self._write_manifest()

        # Live summary every 2s
        self.create_timer(2.0, self._tick)
        self._t0 = time.time()

    def _on_phase(self, msg: String) -> None:
        self.phase = msg.data

    def _tick(self) -> None:
        elapsed = time.time() - self._t0
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        self.get_logger().info(
            f"[t={elapsed:5.1f}s phase={self.phase:>9s}] cpu={cpu:5.1f}% mem={mem:5.1f}%"
        )

    def _write_manifest(self) -> None:
        manifest = {
            "run_id": self.run_id,
            "started_wall_time": time.time(),
            "env": {
                k: os.environ.get(k) for k in [
                    "MODEL_NAME", "MODEL_PRECISION",
                    "ENCODE_CODEC", "ENCODE_BITRATE_KBPS",
                    "LINK_PROFILE", "PX4_SIM_MODEL", "PX4_GZ_WORLD",
                    "MISSION", "RUN_NAME",
                ]
            },
        }
        (self.run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


def main(args=None):
    rclpy.init(args=args)
    node = TelemetryNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
