"""GPU probe — sample NVML at a fixed rate for util / mem / NVENC / NVDEC.

Run as a sidecar thread in any container that uses the GPU. Records carry the
'subsystem' label of whatever process owns this probe so we can attribute the
GPU draw to the right block when partitioning.

The 5090's NVML exposes:
  - SM utilization
  - Memory utilization & used bytes
  - NVENC / NVDEC engine utilization (separate from SM)
  - Tensor Core active percentage (via DCGM if present, else estimated from SM activity)

We deliberately don't try to attribute SM time to specific kernels here — that's a
profiler job (Nsight). The point of this probe is *coarse* duty-cycle so we can
say "perception averaged 78% SM during PHASE_ACQUIRE."
"""

from __future__ import annotations
import threading
import time
from typing import Optional

try:
    import pynvml
    pynvml.nvmlInit()
    _NVML_OK = True
except Exception:
    _NVML_OK = False

from instrumentation.schemas import WorkloadRecord
from instrumentation.probes.probe_writer import ProbeWriter


class GpuProbe:
    """Background thread that samples GPU state and writes WorkloadRecords."""

    def __init__(
        self,
        writer: ProbeWriter,
        run_id: str,
        subsystem: str,
        sample_hz: float = 20.0,
        gpu_index: int = 0,
        phase_provider=None,   # callable returning current PHASE_* string
    ) -> None:
        self.writer = writer
        self.run_id = run_id
        self.subsystem = subsystem
        self.sample_hz = sample_hz
        self.gpu_index = gpu_index
        self.phase_provider = phase_provider or (lambda: "idle")

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._handle = None
        if _NVML_OK:
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_index)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name=f"GpuProbe-{self.subsystem}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # ──── internals ────

    def _run(self) -> None:
        period = 1.0 / max(self.sample_hz, 0.1)
        while not self._stop.is_set():
            self._sample_once()
            time.sleep(period)

    def _sample_once(self) -> None:
        if not _NVML_OK or self._handle is None:
            return
        h = self._handle
        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(h)
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            try:
                enc_util, _ = pynvml.nvmlDeviceGetEncoderUtilization(h)
            except Exception:
                enc_util = None
            try:
                dec_util, _ = pynvml.nvmlDeviceGetDecoderUtilization(h)
            except Exception:
                dec_util = None
        except Exception:
            return

        rec = WorkloadRecord(
            run_id=self.run_id,
            subsystem=self.subsystem,
            operation="gpu_sample",
            phase=self.phase_provider(),
            gpu_util_pct=float(util.gpu),
            sm_active_pct=float(util.gpu),                  # NVML reports SM% as 'gpu'
            gpu_mem_used_mb=mem.used / (1024 * 1024),
            nvenc_util_pct=float(enc_util) if enc_util is not None else None,
            nvdec_util_pct=float(dec_util) if dec_util is not None else None,
        )
        self.writer.emit(rec)
