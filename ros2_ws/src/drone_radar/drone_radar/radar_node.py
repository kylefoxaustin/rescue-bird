"""drone_radar — mmWave radar processing pipeline.

Maps to a mix of ARM (ingest, ego-compensation, clustering) and NPU (fusion)
on real silicon. Emits two distinct subsystem labels so the partitioning
report breaks them out separately:

  - SUBSYSTEM_RADAR        : ARM-side processing (point ingest, DBSCAN, tracks)
  - SUBSYSTEM_RADAR_FUSION : NPU-side fusion model (camera + radar BEV)

Three data formats are supported via $RADAR_FORMAT:
  - point_cloud   : radar already did range FFT + Doppler + angle (cheapest)
  - range_doppler : radar gives 2D RD maps, host does angle estimation
  - raw_adc       : highest data rate, radar just does ADC capture (~GBps)

The format choice dominates the SoC implication and drives the bandwidth
story for the report. range_doppler is the interesting middle ground because
it lets the NPU do learnable angle estimation while keeping the radar simple.
"""

from __future__ import annotations
import os
import time
from pathlib import Path

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import String
from geometry_msgs.msg import PoseStamped

from ratchet.probes import ProbeWriter, OpProbe, GpuProbe
from instrumentation.subsystems import (
    SUBSYSTEM_RADAR, SUBSYSTEM_RADAR_FUSION, SUBSYSTEM_OCCUPANCY,
    SUBSYSTEM_BEHAVIOR, SUBSYSTEM_PERCEPTION,
)


# Approximate MAC counts per fusion model variant.
# Replace with measured values once a real fusion network is plugged in.
FUSION_MACS = {
    "late_fusion":      50_000_000,           # Object-level Bayesian, trivial
    "bev_fusion_small": 8_000_000_000,        # ResNet18 + small BEV head
    "bev_fusion_full":  45_000_000_000,       # Full BEVFusion-style
    "transfusion":      120_000_000_000,      # TransFusion-class
}


class RadarNode(Node):
    def __init__(self):
        super().__init__("drone_radar")

        self.run_id = os.environ.get("RUN_ID", "dev")
        run_dir = Path(os.environ.get("RUN_DIR", f"/runs/{self.run_id}"))
        self.radar_format = os.environ.get("RADAR_FORMAT", "point_cloud")
        self.fusion_mode = os.environ.get("RADAR_FUSION", "bev_fusion_small")
        self.radar_hz = float(os.environ.get("RADAR_HZ", "20"))
        self.points_per_frame = int(os.environ.get("RADAR_POINTS", "1000"))

        # Two writers — radar pipeline ARM-side and fusion NPU-side go to
        # separate Parquet files so they roll up to different rows in the report.
        self.w_radar = ProbeWriter(run_dir, subsystem=SUBSYSTEM_RADAR)
        self.w_fusion = ProbeWriter(run_dir, subsystem=SUBSYSTEM_RADAR_FUSION)

        self.phase = "search"
        self.ingest_op  = OpProbe(self.w_radar, self.run_id, SUBSYSTEM_RADAR,
                                  "ingest_egocomp", lambda: self.phase)
        self.cluster_op = OpProbe(self.w_radar, self.run_id, SUBSYSTEM_RADAR,
                                  "cluster_track", lambda: self.phase)
        self.voxel_op   = OpProbe(self.w_radar, self.run_id, SUBSYSTEM_OCCUPANCY,
                                  "occupancy_update", lambda: self.phase)
        self.fusion_op  = OpProbe(self.w_fusion, self.run_id, SUBSYSTEM_RADAR_FUSION,
                                  f"fusion_{self.fusion_mode}", lambda: self.phase)
        self.gpu = GpuProbe(self.w_fusion, self.run_id, SUBSYSTEM_RADAR_FUSION,
                            phase_provider=lambda: self.phase)
        self.gpu.start()

        # Pubs / subs
        self.create_subscription(PointCloud2, "/radar/points", self._on_points, 10)
        self.create_subscription(PoseStamped, "/vio/pose", self._on_pose, 50)
        self.create_subscription(String, "/mission/phase", self._on_phase, 10)
        self.tracks_pub = self.create_publisher(String, "/radar/tracks", 10)

        self.last_pose: PoseStamped | None = None

        # If we're not connected to a real radar source, run a synthetic generator.
        if os.environ.get("RADAR_SYNTHETIC", "1") == "1":
            self.create_timer(1.0 / self.radar_hz, self._synthetic_tick)

        self.get_logger().info(
            f"radar ready · format={self.radar_format} fusion={self.fusion_mode} "
            f"hz={self.radar_hz} points={self.points_per_frame}"
        )

    def _on_phase(self, msg: String) -> None:
        self.phase = msg.data

    def _on_pose(self, msg: PoseStamped) -> None:
        self.last_pose = msg

    def _on_points(self, msg: PointCloud2) -> None:
        # Real point cloud arrived from radar driver (or sim plugin)
        n_points = max(1, msg.width * msg.height)
        self._process_frame(n_points, real=True)

    def _synthetic_tick(self) -> None:
        # Vary point count by phase to make the report interesting:
        # search has open sky (fewer returns), track in dense forest (many).
        if self.phase == "track":
            n = int(self.points_per_frame * 1.5)
        elif self.phase == "acquire":
            n = int(self.points_per_frame * 1.2)
        else:
            n = self.points_per_frame
        self._process_frame(n, real=False)

    def _process_frame(self, n_points: int, real: bool) -> None:
        # ── Stage 1: ingest + ego-motion compensation (ARM) ────
        # 4 bytes/coord × 4 (x,y,z,velocity) × n_points
        in_bytes = n_points * 16
        with self.ingest_op.measure(
            input_bytes=in_bytes,
            input_shape=f"{n_points}x4",
            precision="fp32",
            radar_n_points=n_points,
            radar_format=self.radar_format,
        ) as obs:
            # Stub: real impl subtracts ego-velocity from each point's Doppler
            time.sleep(0.0008 + n_points * 1e-7)   # ~1ms for 1000 points
            obs.output_bytes = in_bytes
            obs.output_shape = f"{n_points}x4"

        # ── Stage 2: cluster + track (ARM) ────
        # DBSCAN on points; tens of clusters max in a forest scene.
        n_clusters = max(1, n_points // 50)
        n_tracks = min(n_clusters, 30)
        with self.cluster_op.measure(
            input_bytes=in_bytes,
            input_shape=f"{n_points}x4",
            precision="fp32",
            radar_n_points=n_points,
            radar_n_clusters=n_clusters,
            radar_n_tracks=n_tracks,
        ) as obs:
            time.sleep(0.002 + n_points * 5e-8)
            # Per-track output: id, pos, vel, extent, confidence
            obs.output_bytes = n_tracks * 64
            obs.output_shape = f"{n_tracks}x16"

        # ── Stage 3: 3D occupancy grid update (ARM or NPU) ────
        # Bandwidth-bound: 256³ voxels × 1 byte = 16 MB; only updated regions touched.
        with self.voxel_op.measure(
            input_bytes=n_points * 16,
            precision="fp16",
            src_subsystem=SUBSYSTEM_RADAR,
        ) as obs:
            time.sleep(0.001)
            obs.output_bytes = 256 * 256 * 16    # ~1MB of "dirty" voxels written per frame

        # ── Stage 4: AI fusion (NPU) ────
        # This is the headline workload that drives NPU sizing for the
        # all-weather rescue case. Combines radar BEV + camera features.
        macs = FUSION_MACS.get(self.fusion_mode, 8_000_000_000)
        with self.fusion_op.measure(
            input_bytes=in_bytes + 1024 * 1024 * 3,    # radar + 1MP camera features
            input_shape=f"radar:{n_points}x4+cam:1x256x128x128",
            precision="bf16",
            macs=macs,
            src_subsystem=SUBSYSTEM_PERCEPTION,
            dst_subsystem=SUBSYSTEM_BEHAVIOR,
        ) as obs:
            # Cost scales loosely with MACs and 5090 effective TOPS
            cost_ms = macs / 1e10  # ~10ms per 100 GMAC at 5090 BF16 (rough)
            time.sleep(min(0.060, cost_ms / 1000.0))
            obs.output_bytes = 256 * 256 * 4    # BEV fused output
            obs.output_shape = "1x256x256"

        # Publish
        msg = String()
        msg.data = f"tracks={n_tracks};clusters={n_clusters};points={n_points}"
        self.tracks_pub.publish(msg)

    def destroy_node(self):
        self.gpu.stop()
        self.w_radar.close()
        self.w_fusion.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = RadarNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
