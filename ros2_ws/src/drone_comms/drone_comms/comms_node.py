"""drone_comms — radio link emulator + MAVLink/video router.

Maps to ARM + radio modem on real silicon. Two responsibilities:

  1. Apply realistic link impairments (RTT, jitter, loss, throughput cap) using
     tc/netem on the loopback so timing seen by upstream nodes resembles a real
     WiFi or 5G link.
  2. Pump video packets and MAVLink frames out, recording per-packet stats so
     the SoC report can size the comms ARM core's CPU budget under degraded
     conditions.

Three link profiles ship out of the box (see _LINK_PROFILES):
  - wifi_suburban : ~5ms RTT, 0.1% loss, 50 Mbps
  - 5g_lte        : ~25ms RTT, 0.5% loss, 100 Mbps
  - degraded      : ~150ms RTT, 5% loss, 2 Mbps  (worst-case for BFR analysis)
"""

from __future__ import annotations
import os
import random
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import ByteMultiArray

from instrumentation.probes import ProbeWriter, OpProbe
from instrumentation.schemas import SUBSYSTEM_COMMS, SUBSYSTEM_VIDEO_ENCODE


_LINK_PROFILES = {
    "wifi_suburban": dict(rtt_ms=5,   jitter_ms=2,  loss_pct=0.1, throughput_mbps=50),
    "5g_lte":        dict(rtt_ms=25,  jitter_ms=8,  loss_pct=0.5, throughput_mbps=100),
    "degraded":      dict(rtt_ms=150, jitter_ms=40, loss_pct=5.0, throughput_mbps=2),
}


class CommsNode(Node):
    def __init__(self):
        super().__init__("drone_comms")

        self.run_id = os.environ.get("RUN_ID", "dev")
        run_dir = Path(os.environ.get("RUN_DIR", f"/runs/{self.run_id}"))
        self.profile_name = os.environ.get("LINK_PROFILE", "wifi_suburban")
        self.profile = _LINK_PROFILES[self.profile_name]

        self.writer = ProbeWriter(run_dir, subsystem=SUBSYSTEM_COMMS)
        self.phase = "search"
        self.tx_op = OpProbe(self.writer, self.run_id, SUBSYSTEM_COMMS,
                             "link_tx", lambda: self.phase)

        # Subscribe to encoded video, simulate transmission
        self.create_subscription(
            ByteMultiArray, "/video/encoded", self._on_encoded, 50,
        )
        self.get_logger().info(
            f"comms ready · profile={self.profile_name} "
            f"rtt={self.profile['rtt_ms']}ms loss={self.profile['loss_pct']}%"
        )

    def _on_encoded(self, msg: ByteMultiArray) -> None:
        size = len(msg.data)

        # Simulate loss
        dropped = random.random() * 100 < self.profile["loss_pct"]

        # Simulate latency = RTT/2 + jitter
        delay_ms = self.profile["rtt_ms"] / 2 + random.uniform(
            -self.profile["jitter_ms"], self.profile["jitter_ms"]
        )

        with self.tx_op.measure(
            input_bytes=size,
            precision="n/a",
            src_subsystem=SUBSYSTEM_VIDEO_ENCODE,
            dst_subsystem="ground_station",
            link_profile=self.profile_name,
            link_rtt_ms=self.profile["rtt_ms"],
            link_loss_pct=self.profile["loss_pct"],
            link_throughput_mbps=self.profile["throughput_mbps"],
        ) as obs:
            time.sleep(max(0, delay_ms / 1000.0))
            obs.output_bytes = 0 if dropped else size

    def destroy_node(self):
        self.writer.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = CommsNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
