"""OpProbe — context manager that wraps a single operation.

This is the workhorse probe. Wrap any unit of work (one inference, one encode,
one MAVLink batch) and it emits a WorkloadRecord with latency + tensor shapes +
optional MAC count.

Usage:
    op = OpProbe(writer, run_id, subsystem="perception", operation="edgetam_infer")
    with op.measure(input_shape="1x3x1024x1024", input_bytes=...,  precision="bf16",
                    macs=12_500_000_000, src_subsystem="sensor_ingest",
                    dst_subsystem="behavior") as obs:
        result = model(x)
        obs.output_shape = describe(result)
        obs.output_bytes = result.nbytes
"""

from __future__ import annotations
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional, Iterator

from instrumentation.schemas import WorkloadRecord
from instrumentation.probes.probe_writer import ProbeWriter


@dataclass
class OpObservation:
    """Mutable bag the inner block can fill in mid-op (e.g. output_shape after inference)."""
    output_shape: Optional[str] = None
    output_bytes: Optional[int] = None
    extras: dict = field(default_factory=dict)


class OpProbe:
    def __init__(
        self,
        writer: ProbeWriter,
        run_id: str,
        subsystem: str,
        operation: str,
        phase_provider=None,
    ) -> None:
        self.writer = writer
        self.run_id = run_id
        self.subsystem = subsystem
        self.operation = operation
        self.phase_provider = phase_provider or (lambda: "idle")

    @contextmanager
    def measure(
        self,
        input_shape: Optional[str] = None,
        input_bytes: Optional[int] = None,
        precision: Optional[str] = None,
        macs: Optional[int] = None,
        flops: Optional[int] = None,
        src_subsystem: Optional[str] = None,
        dst_subsystem: Optional[str] = None,
        **extra,
    ) -> Iterator[OpObservation]:
        obs = OpObservation()
        t0 = time.perf_counter_ns()
        try:
            yield obs
        finally:
            t1 = time.perf_counter_ns()
            rec = WorkloadRecord(
                run_id=self.run_id,
                subsystem=self.subsystem,
                operation=self.operation,
                phase=self.phase_provider(),
                latency_ns=t1 - t0,
                macs=macs,
                flops=flops,
                precision=precision,
                input_shape=input_shape,
                input_bytes=input_bytes,
                output_shape=obs.output_shape,
                output_bytes=obs.output_bytes,
                src_subsystem=src_subsystem,
                dst_subsystem=dst_subsystem,
            )
            # Per-op extras land in WorkloadRecord.extras for free-form fields
            # (e.g. encode_codec on a video op). The schema dataclass already
            # has typed fields for the common cases; merge those in if present.
            merged = {**extra, **obs.extras}
            for k, v in merged.items():
                if hasattr(rec, k):
                    setattr(rec, k, v)
                else:
                    rec.extras[k] = v
            self.writer.emit(rec)
