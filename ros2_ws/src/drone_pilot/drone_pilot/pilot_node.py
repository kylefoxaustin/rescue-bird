"""drone_pilot — runs a pilot behavior model alongside the SITL stack.

This node is host-only — it does NOT correspond to a block on the
deployed SoC. Its job is to produce flyability observations that
quantify whether the chip's measured g2g latency is good enough for a
human operator to fly the configured scenario.

Currently uses the latency_aware model (measurement only). The interface
allows future models — recorded human stick replay, rule-based closed-
loop pilots — to plug in via the same node by changing $PILOT_MODEL.

The node does NOT publish stick commands. A real test harness with
recorded pilot input would publish to /pilot/setpoint; this node only
publishes observations to /pilot/observation for the report aggregator.
"""

from __future__ import annotations
import os
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Float32

from ratchet.probes import ProbeWriter
from ratchet.probes.op_probe import OpProbe
from ratchet.schemas import WorkloadRecord
from instrumentation.pilots import observe, aggregate, PilotObservation


PILOT_SUBSYSTEM = "pilot"   # not in the canonical list — host-only


class PilotNode(Node):
    def __init__(self):
        super().__init__("drone_pilot")

        self.run_id = os.environ.get("RUN_ID", "dev")
        run_dir = Path(os.environ.get("RUN_DIR", f"/runs/{self.run_id}"))
        self.model_name = os.environ.get("PILOT_MODEL", "latency_aware")
        self.visual_reaction_ms = float(os.environ.get("PILOT_VISUAL_REACTION_MS", "200"))
        self.drone_speed_mps = float(os.environ.get("PILOT_DRONE_SPEED_MPS", "8"))

        if self.model_name != "latency_aware":
            self.get_logger().warning(
                f"Unknown pilot model '{self.model_name}', falling back to latency_aware"
            )
            self.model_name = "latency_aware"

        self.writer = ProbeWriter(run_dir, subsystem=PILOT_SUBSYSTEM)
        self.observations: list[PilotObservation] = []

        # Subscribe to glass-to-glass measurements emitted by the encode node
        # via the G2gProbe. We watch for /g2g/total_ms publications which the
        # encode node emits as a side effect of its display stamps.
        self.create_subscription(Float32, "/g2g/total_ms", self._on_g2g, 50)
        self.pub = self.create_publisher(String, "/pilot/observation", 50)

        # Periodic summary
        self.create_timer(5.0, self._emit_summary)

        self.get_logger().info(
            f"drone_pilot ready · model={self.model_name} "
            f"reaction={self.visual_reaction_ms}ms speed={self.drone_speed_mps}m/s"
        )

    def _on_g2g(self, msg: Float32) -> None:
        g2g_ms = float(msg.data)
        obs = observe(
            g2g_latency_ms=g2g_ms,
            drone_speed_mps=self.drone_speed_mps,
            pilot_visual_reaction_ms=self.visual_reaction_ms,
        )
        self.observations.append(obs)

        # Emit a record into the partition Parquet so the report can pick it up
        rec = WorkloadRecord(
            run_id=self.run_id,
            subsystem=PILOT_SUBSYSTEM,
            operation=f"{self.model_name}_observe",
            phase="track",
            g2g_total_ms=g2g_ms,
        )
        rec.extras = {
            "control_quality_pct": obs.control_quality_pct,
            "estimated_overshoot_m": obs.estimated_overshoot_m,
            "effective_reaction_ms": obs.effective_reaction_ms,
            "flyability_status": obs.flyability_status,
        }
        self.writer.emit(rec)

        # Publish a one-line observation for downstream
        out = String()
        out.data = (
            f"g2g={g2g_ms:.1f}ms quality={obs.control_quality_pct:.0f}% "
            f"overshoot={obs.estimated_overshoot_m:.2f}m status={obs.flyability_status}"
        )
        self.pub.publish(out)

    def _emit_summary(self) -> None:
        if not self.observations:
            return
        s = aggregate(self.observations)
        self.get_logger().info(
            f"pilot · n={s['n']} flyable={s['mission_flyable']} "
            f"degraded={s['pct_degraded']:.1f}% unflyable={s['pct_unflyable']:.1f}% "
            f"p99_g2g={s['p99_g2g_latency_ms']:.1f}ms p99_overshoot={s['p99_overshoot_m']:.2f}m"
        )

    def destroy_node(self):
        # Final summary
        self._emit_summary()
        self.writer.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PilotNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
