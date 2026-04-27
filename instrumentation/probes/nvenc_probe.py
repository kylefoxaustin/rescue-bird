"""NVENC probe — emit one record per encoded frame.

The video encode path is one of the most important blocks for SoC partitioning
because real silicon has a *dedicated VPU* with very different characteristics
from a GPU's NVENC engine. Per-frame stats (size, keyframe flag, latency) let
us derive the real bitrate variability the VPU has to handle.

Hook this into a GStreamer pipeline by attaching to pad probes on the encoder
sink and source pads, or driving it from the Python encode wrapper.
"""

from __future__ import annotations
import time
from typing import Optional

from instrumentation.schemas import WorkloadRecord, SUBSYSTEM_VIDEO_ENCODE
from instrumentation.probes.probe_writer import ProbeWriter


class NvencProbe:
    def __init__(
        self,
        writer: ProbeWriter,
        run_id: str,
        codec: str = "h265",
        bitrate_kbps: float = 6000.0,
        phase_provider=None,
    ) -> None:
        self.writer = writer
        self.run_id = run_id
        self.codec = codec
        self.bitrate_kbps = bitrate_kbps
        self.phase_provider = phase_provider or (lambda: "idle")

        self._frame_in_t_ns: Optional[int] = None

    def on_input_frame(self) -> None:
        """Call when a raw frame enters the encoder."""
        self._frame_in_t_ns = time.perf_counter_ns()

    def on_encoded_frame(
        self,
        size_bytes: int,
        keyframe: bool,
        input_shape: Optional[str] = None,
    ) -> None:
        """Call when an encoded packet exits the encoder."""
        t = time.perf_counter_ns()
        latency = (t - self._frame_in_t_ns) if self._frame_in_t_ns else None
        rec = WorkloadRecord(
            run_id=self.run_id,
            subsystem=SUBSYSTEM_VIDEO_ENCODE,
            operation=f"{self.codec}_encode_frame",
            phase=self.phase_provider(),
            latency_ns=latency,
            input_shape=input_shape,
            output_bytes=size_bytes,
            encode_codec=self.codec,
            encode_bitrate_kbps=self.bitrate_kbps,
            encode_frame_size_bytes=size_bytes,
            encode_keyframe=keyframe,
            src_subsystem="sensor_ingest",
            dst_subsystem="comms",
        )
        self.writer.emit(rec)
