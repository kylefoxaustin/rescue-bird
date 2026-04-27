"""drone_video_encode — H.264/H.265/AV1 encode via NVENC.

Maps to a dedicated VPU on real silicon. The per-frame stats (size, keyframe
flag, latency) emitted by NvencProbe are what size the VPU pixel-rate budget,
the VPU→radio bandwidth, and the bitrate-control headroom under degraded link.

This node uses GStreamer's nvh265enc (or nvh264enc / nvav1enc) by codec env.
For simulation work where you don't have a real GStreamer install yet, the
fallback path uses ffmpeg-python or PyAV. The NvencProbe interface is identical
either way.
"""

from __future__ import annotations
import os
import time
from pathlib import Path

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import ByteMultiArray
from cv_bridge import CvBridge

from ratchet.probes import ProbeWriter, NvencProbe
from instrumentation.subsystems import SUBSYSTEM_VIDEO_ENCODE


class VideoEncodeNode(Node):
    def __init__(self):
        super().__init__("drone_video_encode")

        self.run_id = os.environ.get("RUN_ID", "dev")
        run_dir = Path(os.environ.get("RUN_DIR", f"/runs/{self.run_id}"))
        self.codec = os.environ.get("ENCODE_CODEC", "h265")
        self.bitrate_kbps = float(os.environ.get("ENCODE_BITRATE_KBPS", "6000"))

        self.writer = ProbeWriter(run_dir, subsystem=SUBSYSTEM_VIDEO_ENCODE)
        self.phase = "search"
        self.probe = NvencProbe(
            self.writer, self.run_id,
            codec=self.codec, bitrate_kbps=self.bitrate_kbps,
            phase_provider=lambda: self.phase,
        )

        self.bridge = CvBridge()
        self.frame_count = 0
        self.create_subscription(Image, "/camera/image_raw", self._on_frame, 10)
        self.pub = self.create_publisher(ByteMultiArray, "/video/encoded", 10)

        self.encoder = self._build_encoder()
        self.get_logger().info(
            f"video_encode ready · codec={self.codec} bitrate={self.bitrate_kbps}kbps"
        )

    def _build_encoder(self):
        # TODO: replace with real GStreamer pipeline:
        #   appsrc ! videoconvert ! nvh265enc bitrate=6000 ! h265parse ! appsink
        # or PyAV-based encode. For now, stub that simulates GOP behavior.
        return _StubEncoder(self.codec, self.bitrate_kbps)

    def _on_frame(self, msg: Image) -> None:
        cv = self.bridge.imgmsg_to_cv2(msg, "rgb8")
        h, w = cv.shape[:2]
        self.probe.on_input_frame()
        encoded, is_keyframe = self.encoder.encode(cv)
        self.probe.on_encoded_frame(
            size_bytes=len(encoded),
            keyframe=is_keyframe,
            input_shape=f"1x3x{h}x{w}",
        )

        # Publish encoded frame (so comms node can ship it)
        out = ByteMultiArray()
        out.data = list(encoded)
        self.pub.publish(out)
        self.frame_count += 1

    def destroy_node(self):
        self.writer.close()
        super().destroy_node()


class _StubEncoder:
    """Placeholder encoder. Generates plausible per-frame sizes:
    keyframes every GOP, P-frames much smaller, with bitrate target ≈ configured."""
    def __init__(self, codec: str, bitrate_kbps: float, gop: int = 30, fps: float = 30.0):
        self.codec = codec
        self.gop = gop
        self.frame_idx = 0
        # Average bytes per frame for the configured bitrate
        self.avg_bytes_per_frame = (bitrate_kbps * 1000 / 8) / fps
        # Keyframes are ~5x bigger than P-frames typically
        self.kf_factor = 5.0

    def encode(self, frame: np.ndarray) -> tuple[bytes, bool]:
        is_kf = (self.frame_idx % self.gop) == 0
        if is_kf:
            size = int(self.avg_bytes_per_frame * self.kf_factor)
        else:
            # 30 P-frames have to average to (gop * avg) - kf_size, so:
            p_size = (self.avg_bytes_per_frame * self.gop -
                      self.avg_bytes_per_frame * self.kf_factor) / (self.gop - 1)
            jitter = np.random.normal(1.0, 0.15)
            size = int(max(64, p_size * jitter))
        # Imitate encode latency: keyframes take longer
        time.sleep(0.012 if is_kf else 0.004)
        self.frame_idx += 1
        return (b"\x00" * size, is_kf)


def main(args=None):
    rclpy.init(args=args)
    node = VideoEncodeNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
