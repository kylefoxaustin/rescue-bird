# Instrumentation Guide

This is the practical "how do I add a probe" reference. The conceptual
discussion of *what to measure and why* lives in
`subsystem_to_silicon_map.md`.

## The three probe types

### `OpProbe` — wrap a single operation

Use this around any unit of work whose latency, MAC count, or tensor sizes
matter. It captures: latency, input/output shapes/bytes, precision, MACs,
plus optional source/destination subsystem labels for the bandwidth graph.

```python
from instrumentation.probes import ProbeWriter, OpProbe
from instrumentation.schemas import SUBSYSTEM_PERCEPTION, SUBSYSTEM_BEHAVIOR

writer = ProbeWriter(run_dir, subsystem=SUBSYSTEM_PERCEPTION)
op = OpProbe(writer, run_id, SUBSYSTEM_PERCEPTION, "edgetam_infer")

with op.measure(
    input_shape="1x3x1024x1024",
    input_bytes=frame.nbytes,
    precision="bf16",
    macs=12_500_000_000,
    src_subsystem="sensor_ingest",
    dst_subsystem=SUBSYSTEM_BEHAVIOR,
) as obs:
    result = model(frame)
    obs.output_shape = describe(result)
    obs.output_bytes = result.nbytes
```

### `GpuProbe` — sample NVML in the background

A sidecar thread that samples GPU SM%, memory, NVENC%, NVDEC% at a fixed
rate. Start it once at node init, stop it at shutdown. The sampled records
get attributed to whichever subsystem owns the probe — that's how the
report tells you "perception drove SM% to 78% during acquire."

```python
from instrumentation.probes import GpuProbe

gpu = GpuProbe(writer, run_id, SUBSYSTEM_PERCEPTION,
               sample_hz=20.0,
               phase_provider=lambda: current_phase)
gpu.start()
# ... node runs ...
gpu.stop()
```

### `NvencProbe` — per-frame encoder stats

Specialized for the video encode path. Two methods: `on_input_frame()` when
a raw frame enters the encoder, `on_encoded_frame()` when an encoded packet
leaves. Captures size, keyframe flag, and latency per frame.

```python
from instrumentation.probes import NvencProbe

probe = NvencProbe(writer, run_id, codec="h265", bitrate_kbps=6000)

probe.on_input_frame()
encoded, is_kf = encoder.encode(frame)
probe.on_encoded_frame(size_bytes=len(encoded), keyframe=is_kf,
                       input_shape="1x3x1080x1920")
```

## Adding a new probe type

If you need something the existing probes don't cover, follow this pattern:

1. The probe holds a `ProbeWriter` reference.
2. It exposes start/stop or context-manager methods.
3. It emits `WorkloadRecord` instances via `writer.emit()`.
4. It fills in only the fields it can cheaply measure; everything else
   stays None and the analysis script ignores nulls.

Don't add new fields to `WorkloadRecord` unless they're broadly useful.
For one-off fields, use the `extras` dict — but note that extras are not
in the Parquet schema and are not aggregated by the report.

## Run identity

Every probe needs a `run_id`. The `run_mission.sh` script sets `RUN_ID`
and `RUN_DIR` env vars before launching ROS 2. Nodes pick these up at
startup. The report aggregator uses `run_id` to keep separate runs
separate — but you can also concatenate multiple Parquet files from
different runs by hand if you want comparative analysis.

## Performance notes

- `OpProbe.measure` adds about 1µs of overhead per call. If you wrap an
  operation that itself takes <100ns, you'll measure mostly the probe.
- `ProbeWriter.emit` appends to an in-memory list. A flush every 256
  records writes a single Parquet row group (~tens of KB).
- `GpuProbe` at 20 Hz costs about 0.1% of one CPU core via NVML calls.
- All probes are thread-safe. Multiple probes can share a single
  `ProbeWriter`.

## Tying probe data back to mission phases

Pass a `phase_provider` callable when constructing any probe. The behavior
node publishes `/mission/phase`; subscribe to it in your node, store the
current phase in an attribute, and pass `lambda: self.phase` as the
provider. Every record then carries the phase that was active at emit time
— this is what powers the "during PHASE_ACQUIRE..." rows in the report.
