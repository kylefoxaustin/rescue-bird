# nightjar

Drone software stack + edge-SoC sizing tool (the rescue-bird use case).
Two purposes side-by-side: **measure** workload via instrumented SITL
(ROS 2 + Gazebo + PX4) and **project** workload via an analytical model
(33 sliders → 15 KPIs). The goal is producing defensible numbers for an
edge-SoC partitioning conversation (NPU TOPS, ISP/DSP/VPU sizing, memory
bandwidth, BF16 vs FP16, LLM headroom).

This repo depends on **`ratchet`** (the generic SoC sizing engine) for
slider/demand/KPI primitives, probes, and the WorkloadRecord schema. See
the "Dev install" section below.

## Read these first

- `DESIGN.md` — high-level architecture map
- `docs/decisions/` — 5 nightjar-specific ADRs (003 asymmetric multi-camera,
  004 dedicated ISP, 005 Cadence DSP, 006 Cortex-M flight control,
  010 glass-to-glass <100ms) plus stubs at 001/002/007/008/009/011 pointing
  to the engine-level ADRs in ratchet.
- `docs/testing.md` — six layers of testing strategy
- `docs/whatif_kpis.md` — slider catalog and worked examples

In the ratchet repo:
- `ratchet/docs/decisions/` — 6 engine-level ADRs (two-source model,
  process isolation, BF16, LLM memory-bound, NPU efficiency, trajectory
  test harness pattern)

## Current state

**v0.3.0-dev** — engine extraction complete. The drone-specific drivers,
trajectories, pilot model, ROS 2 nodes, profiles, missions, and report
generator live here. The generic engine (sliders/demands/KPIs/probes/
schema) lives in [`ratchet`](https://github.com/kylefoxaustin/ratchet).

A stable v0.3.0 will not be cut until the second site (`keyhole`, the
video sizer) confirms the ratchet API is solid.

**Standing calibration goal**: Replace `_StubModel` in perception_node.py
with TensorRT-converted EdgeTAM, run test scenarios, refine
`npu_efficiency_factor` (currently 0.55, see ratchet ADR 005 — formerly
nightjar ADR 009).

## Dev install

```bash
# Clone ratchet alongside nightjar
cd ..
git clone https://github.com/kylefoxaustin/ratchet.git
cd nightjar

# Editable install picks up local ratchet sources
pip install -e ../ratchet
pip install -e ".[dev]"
```

If you `pip install -e ".[dev]"` first, pip will pull `ratchet>=0.1.0`
from PyPI (or fail if it isn't published yet). For active engine
development, `pip install -e ../ratchet` first to ensure the editable
checkout is what gets used.

## Commands

```bash
# Run all tests (82 unit + 10 golden = 92 total)
pytest tests/ -v

# Run ratchet's own framework tests too
pytest ../ratchet/tests/ -v   # 76 tests

# Regenerate golden snapshots after intentional model changes
pytest tests/golden --update-goldens

# Point evaluation: does the default chip pass at default workload?
python -m instrumentation.sizing.whatif_cli point

# 1D sweep over a slider
python -m instrumentation.sizing.whatif_cli sweep --slider npu_tops_bf16 --steps 5

# 2D Pareto across two sliders
python -m instrumentation.sizing.whatif_cli pareto --x npu_tops_bf16 --y memory_channels

# Run a SITL mission (requires Docker + GPU)
./scripts/run_mission.sh test_aerobatic_forest --target rescue_bird_a720
```

## Architecture pointers

- `instrumentation/sizing/` — drone-specific what-if model (sliders,
  workload demand calcs, KPIs, CLI). Imports the engine framework from
  `ratchet.engine.*` and the runner from `ratchet.whatif`.
- `instrumentation/analysis/profiles/*.yaml` — SoC profiles
  (rescue_bird_a720, imx95, snapdragon)
- `instrumentation/analysis/soc_partition_report.py` — Markdown report
  from Parquet runs (drone-flavored; consumes records produced via
  ratchet probes)
- `instrumentation/subsystems.py` — drone `SUBSYSTEM_*` and `PHASE_*`
  string constants (formerly in `instrumentation/schemas/`)
- `instrumentation/trajectories/` — deterministic flight profile generators
- `instrumentation/pilots/` — measurement-only pilot flyability model
- `ros2_ws/src/drone_*/` — per-subsystem ROS 2 nodes (each maps to a
  silicon engine; imports `ratchet.probes` and `ratchet.schemas`)
- `missions/test_*.yaml` — the four trajectory-driven test scenarios

In ratchet:
- `ratchet/engine/` — Slider, SubsystemDemand, KpiResult dataclasses;
  generic NPU/CPU/memory KPIs; LLM-bandwidth math
- `ratchet/whatif/` — point/sweep/pareto runner that consumes the engine
- `ratchet/probes/` — Parquet-emitting probes (op, GPU, NVENC, g2g)
- `ratchet/schemas/` — WorkloadRecord dataclass + PyArrow schema

## Gotchas

- **Editable ratchet install**: if you change ratchet sources, the
  changes are picked up immediately by nightjar (because of
  `pip install -e ../ratchet`). No reinstall needed. Do reinstall if
  you change ratchet's pyproject.toml.
- **Cross-platform line endings**: this repo expects LF. If editing on
  Windows, set `git config core.autocrlf false` and `git config
  core.fileMode false` in your local clone before committing.
- **Don't add a `requirements.txt`** — dependencies are listed in
  `pyproject.toml`. Use `pip install -e .` for dev install.
- **Stub models in perception/radar nodes are deliberate** — they exist
  so the SITL plumbing can be validated before real model weights are
  wired in. When swapping in real models, keep the stub path as a
  fallback for CI.
- **ROS 2 hop latency overstates real silicon by 5-10×** (see ratchet
  ADR 002, formerly nightjar ADR 002). Subtract DDS overhead before
  reporting on-chip latency in the competitive deck.