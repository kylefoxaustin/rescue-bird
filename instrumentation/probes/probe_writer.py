"""ProbeWriter — buffered Parquet sink shared by all probes.

Every probe in the system uses an instance of this to dump WorkloadRecords.
Records are buffered in memory and flushed in row-group-sized batches to keep
write overhead off the hot path. Each subsystem gets its own file under the run
directory; the analysis script globs them all together.
"""

from __future__ import annotations
import os
import threading
from pathlib import Path
from typing import List, Optional

import pyarrow as pa
import pyarrow.parquet as pq

from instrumentation.schemas import WorkloadRecord, WORKLOAD_SCHEMA


class ProbeWriter:
    """Thread-safe, buffered Parquet writer for WorkloadRecords."""

    def __init__(
        self,
        run_dir: str | Path,
        subsystem: str,
        flush_every: int = 256,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.subsystem = subsystem
        self.flush_every = flush_every

        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / f"{subsystem}.parquet"

        self._buffer: List[WorkloadRecord] = []
        self._lock = threading.Lock()
        self._writer: Optional[pq.ParquetWriter] = None

    def emit(self, record: WorkloadRecord) -> None:
        """Add one record. Flushes when buffer is full."""
        with self._lock:
            self._buffer.append(record)
            if len(self._buffer) >= self.flush_every:
                self._flush_locked()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def close(self) -> None:
        with self._lock:
            self._flush_locked()
            if self._writer is not None:
                self._writer.close()
                self._writer = None

    # ──── internals ────

    def _flush_locked(self) -> None:
        if not self._buffer:
            return
        # Build column-major dict from the buffered records.
        cols = {field.name: [] for field in WORKLOAD_SCHEMA}
        for rec in self._buffer:
            d = rec.to_dict()
            d.pop("extras", None)  # extras are not in the schema; serialize separately if needed
            for k in cols:
                cols[k].append(d.get(k))
        table = pa.Table.from_pydict(cols, schema=WORKLOAD_SCHEMA)
        if self._writer is None:
            self._writer = pq.ParquetWriter(self.path, WORKLOAD_SCHEMA)
        self._writer.write_table(table)
        self._buffer.clear()

    def __enter__(self) -> "ProbeWriter":
        return self

    def __exit__(self, *args) -> None:
        self.close()
