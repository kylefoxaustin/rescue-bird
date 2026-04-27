# rescue-bird

A full drone software stack that runs entirely on a workstation GPU (RTX 5090 target),
instrumented end-to-end so that compute, memory, and bandwidth requirements per subsystem
can be extracted and projected onto an edge SoC.

This is a **use-case extraction harness**, not a flight controller. The flying behavior
is real (PX4 SITL). The point is to measure each subsystem under realistic mission
scenarios so you can answer questions like:

- How many TOPS does the perception pipeline need at the 95th percentile during target
  acquisition?
- What's the sustained memory bandwidth across the camera ISP → encoder → radio path?
- Does BF16 vs FP16 actually matter for SAM2/EdgeTAM at these input sizes and frame rates?
- What LPDDR5 channel count keeps perception + VIO + encode from contending?
- Where is the latency budget actually spent in a "detect → track → command" loop?

## Architecture

```
                  ┌─────────────────────────────────────────────────┐
                  │                  Mission / GCS                  │
                  │       (QGroundControl + custom telemetry UI)    │
                  └────────────────────────┬────────────────────────┘
                                           │  WiFi/5G link emulator
                                           │  (drone_comms)
┌──────────────────────────────────────────┼──────────────────────────────────────────┐
│ DRONE (simulated, all on RTX 5090)       │                                          │
│                                          ▼                                          │
│  ┌──────────────┐   ┌────────────────────────────┐   ┌──────────────────────────┐  │
│  │ Gazebo /     │──▶│  drone_perception          │──▶│  drone_behavior          │  │
│  │ Isaac Sim    │   │  (YOLO / SAM2 / EdgeTAM)   │   │  (mission FSM / target   │  │
│  │ sensors      │   │  TensorRT, BF16/FP16/INT8  │   │   tracking / commands)   │  │
│  └──────┬───────┘   └────────────┬───────────────┘   └────────────┬─────────────┘  │
│         │                        │                                │                 │
│         │                        ▼                                ▼                 │
│         │              ┌─────────────────┐              ┌──────────────────┐        │
│         │              │  drone_vio      │              │  PX4 SITL        │        │
│         │              │  (VIO/SLAM)     │─────────────▶│  (EKF + control) │        │
│         │              └─────────────────┘              └──────────────────┘        │
│         │                                                                            │
│         ▼                                                                            │
│  ┌──────────────────┐         ┌──────────────────┐                                  │
│  │ drone_video_     │────────▶│  drone_comms     │── MAVLink + RTSP/WebRTC ──▶      │
│  │ encode (NVENC)   │         │  (link emulator) │                                  │
│  └──────────────────┘         └──────────────────┘                                  │
│                                                                                      │
│  ┌────────────────────────────────────────────────────────────────────────────┐    │
│  │ drone_telemetry  ◀── instrumentation probes from every node above ──        │    │
│  │ (latency, msg sizes, GPU util, NVENC stats, mem bandwidth, TOPS estimate)   │    │
│  └────────────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Subsystem → silicon mapping (the actual deliverable)

Each ROS 2 package corresponds to a logical block that must land somewhere on a real SoC.
See [`docs/subsystem_to_silicon_map.md`](docs/subsystem_to_silicon_map.md) for the
projection methodology and a worked example, and
[`docs/whatif_kpis.md`](docs/whatif_kpis.md) for the what-if sizing engine.

| ROS 2 Package          | Real-world block          | Likely SoC home        |
|------------------------|---------------------------|------------------------|
| `drone_perception`     | Target ID, segmentation   | NPU                    |
| `drone_vio`            | Visual-inertial odometry  | NPU + GPU + ARM        |
| `drone_radar`          | Radar ingest, clustering  | ARM                    |
| `drone_radar` (fusion) | Camera+radar BEV fusion   | NPU                    |
| `drone_video_encode`   | H.264/H.265 encode        | Dedicated VPU          |
| `drone_behavior`       | Mission FSM, planner      | ARM application core   |
| `drone_comms`          | Radio stack, framing      | ARM + modem            |
| (LLM, when active)     | On-device reasoning       | NPU (memory-BW bound)  |
| `drone_telemetry`      | (host-only — not deployed)| n/a                    |
| PX4 SITL               | Flight control + EKF      | Cortex-M / RT core     |
| Gazebo / Isaac Sim     | (host-only — not deployed)| n/a                    |

## Two ways to use this

**Measure** real workload on a SITL run, then read the partition report:
```bash
./scripts/run_mission.sh fog_rescue --target rescue_bird_a720
```

**Project** workload analytically and ask what-if questions in seconds:
```bash
# Default A720 + 200 TOPS — does it work?
python -m instrumentation.analysis.whatif.whatif_cli point

# What if NPU drops to 100 TOPS and we add a 7B LLM?
python -m instrumentation.analysis.whatif.whatif_cli point \
    --set npu_tops_bf16=100 --set llm_active=1 --set llm_model_b_params=7

# Where does memory bandwidth become the binding constraint?
python -m instrumentation.analysis.whatif.whatif_cli sweep \
    --slider memory_channels --steps 4

# 2D Pareto: NPU TOPS × perception model size
python -m instrumentation.analysis.whatif.whatif_cli pareto \
    --x npu_tops_bf16 --y perception_model_gmacs
```

See [`docs/whatif_kpis.md`](docs/whatif_kpis.md) for the full slider catalog and
worked examples for the competitive deck.

## Quickstart

```bash
git clone <this-repo>
cd rescue-bird
cp docker/.env.example docker/.env
./scripts/setup.sh                          # build images, fetch PX4, fetch model weights
./scripts/run_sim.sh                        # bring up sim + flight stack + ROS bridge
./scripts/run_mission.sh search_pattern     # fly a baseline mission
./scripts/run_mission.sh rescue_bird_full   # end-to-end with target acquisition
```

After a mission run, telemetry lands in `./runs/<timestamp>/` as Parquet. Generate the
silicon-partitioning report with:

```bash
python instrumentation/analysis/soc_partition_report.py runs/<timestamp>/
```

## Phasing

This repo is structured to be useful at any of the following maturity levels — start at 1
and stop wherever the data is good enough for your competitive analysis.

1. **Fly a square.** PX4 SITL + Gazebo, MAVLink commands. No AI, no encode. Validates
   the harness.
2. **See and stream.** Add the simulated camera, NVENC encode, RTSP out. Measures the
   video pipeline in isolation.
3. **Detect.** Add `drone_perception` with YOLO or SAM2. Measures NPU-class workload.
4. **Localize.** Add `drone_vio`. Measures the bandwidth-heavy combined GPU/NPU case.
5. **Close the loop.** Detection drives `drone_behavior` drives flight commands. End-to-end
   latency budget is now real.

Each phase has a corresponding `missions/*.yaml` scenario.

## Why a workstation GPU

The 5090 is deliberately overkill. The point isn't that the drone *needs* a 5090; the point
is that running everything fat and unconstrained on the 5090 lets the instrumentation
capture honest peak compute, memory, and bandwidth numbers that you can then project
downward onto the candidate edge SoC. Throttling for fit comes later.

## Repo layout

```
rescue-bird/
├── docker/                  # Containerized environments (sim, perception, comms)
├── docs/                    # Architecture + silicon mapping methodology
├── gazebo/                  # World files
├── instrumentation/         # Probes, schemas, analysis (the secret sauce)
│   ├── probes/              # Per-node hooks (latency, GPU, NVENC, bandwidth)
│   ├── schemas/             # Parquet record definitions
│   └── analysis/            # SoC partition report generator
├── missions/                # Mission YAML scenarios
├── px4/                     # PX4 airframe + param overrides
├── ros2_ws/src/             # All ROS 2 packages (one per real subsystem)
└── scripts/                 # setup.sh, run_sim.sh, run_mission.sh
```

## License

MIT
