# Design overview

This is the high-level design map for someone joining the project. It links
to the deeper docs rather than duplicating them.

## What this project is

A drone software stack that runs entirely on a workstation GPU (RTX 5090
target), instrumented end-to-end so that compute, memory, and bandwidth
requirements per subsystem can be:

1. **Measured** by running mission scenarios in SITL
2. **Projected** by an analytical workload model that takes 21+ named
   sliders as input and emits per-subsystem KPIs

The two work side-by-side. Measured numbers calibrate the model. The model
lets you ask "what if?" without rerunning the mission.

## Why this exists

To produce defensible numbers for an edge-SoC partitioning conversation.
Concretely: how many TOPS, what memory bandwidth, what kind of ISP/DSP/VPU
blocks, and which precisions does a chip need to fly a rescue drone
through a forest while detecting survivors and streaming low-latency video
to an operator.

## Architecture in one diagram

```
              [ Camera sensors via MIPI CSI-2 ]
                          │
                          ▼
              ┌─────────────────────────┐
              │  drone_isp (ISP block)  │  fixed-point pipeline
              │  Bayer→demosaic→...→YUV │  sustained line rate
              └────────────┬────────────┘
                           │
              ┌────────────┴───────────────────┐
              │                                │
              ▼                                ▼
   ┌──────────────────────┐        ┌──────────────────────┐
   │ drone_dsp            │        │ drone_video_encode   │
   │ (Cadence Vision Q)   │        │ (VPU)                │
   │ pyramids, flow, warp │        │ H.265 → comms        │
   └──────┬───────────────┘        └──────────────────────┘
          │
          ▼
   ┌──────────────────────┐        ┌──────────────────────┐
   │ drone_perception     │        │ drone_vio            │
   │ (NPU)                │        │ (NPU + ARM)          │
   │ SAM2/EdgeTAM/YOLO    │        │ feature + pose       │
   └──────────────────────┘        └──────────────────────┘

   ┌──────────────────────┐        ┌──────────────────────┐
   │ drone_radar          │        │ drone_radar (fusion) │
   │ (ARM)                │        │ (NPU)                │
   │ ingest, cluster      │        │ camera+radar BEV     │
   └──────────────────────┘        └──────────────────────┘

   ┌──────────────────────┐        ┌──────────────────────┐
   │ drone_behavior       │        │ drone_comms          │
   │ (ARM application)    │        │ (ARM + modem)        │
   │ FSM, planning        │        │ link emulator        │
   └──────────────────────┘        └──────────────────────┘

   ┌──────────────────────┐
   │ PX4 SITL             │   real-time control loop
   │ (Cortex-M companion) │   on dedicated RT core
   └──────────────────────┘
```

## Where to read more

- **`README.md`** — quickstart, file layout, what each script does
- **`docs/architecture.md`** — detailed dataflow with bandwidth implications
- **`docs/subsystem_to_silicon_map.md`** — methodology for projecting
  measured workloads onto a candidate SoC
- **`docs/whatif_kpis.md`** — slider catalog, KPI definitions, worked
  examples for the competitive deck
- **`docs/instrumentation_guide.md`** — how to add new probes
- **`docs/testing.md`** — six layers of testing from unit to real-hardware
- **`docs/decisions/`** — 10 ADRs capturing the why behind key choices

## What's in scope today

- Full ROS 2 stack for 9 subsystems (perception, VIO, radar, ISP, DSP,
  video encode, behavior, comms, telemetry)
- Probe framework (op-level, GPU-sample, NVENC, glass-to-glass) writing
  to Parquet
- Analytical workload model with 33 sliders
- KPI evaluator with 15 KPIs at default config
- 3 SoC profiles (rescue_bird_a720, imx95, snapdragon)
- 4 mission scenarios (search_pattern, target_acquisition,
  rescue_bird_full, fog_rescue)
- 49 unit tests + 10 golden-file regression tests

## What's not in scope yet

- Real model weights for perception (uses calibrated stubs)
- Cycle-accurate vendor-tooling cross-checks
- Real-hardware validation runs
- Power modeling (compute is sized; Joules are not)
- Thermal/throttling

These are documented in `docs/testing.md` as the natural next steps for
building confidence in the numbers.
