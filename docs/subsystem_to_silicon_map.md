# Subsystem → Silicon Mapping

This is the methodology that turns mission telemetry into a concrete silicon
spec. The simulation exists to feed this document with numbers.

## The question we're answering

For each candidate edge SoC, given the mission set we care about (search,
acquire, track, degraded-link return-to-home), can the SoC sustain the
required compute, memory bandwidth, and I/O — and where does it break?

## The mapping

Every ROS 2 package in this repo corresponds to a logical block that has to
land *somewhere* on real silicon. The table below captures the canonical
placement; the analysis script flags subsystems that exceed their target
budget.

| ROS 2 Package          | Logical block             | Primary engine         | Co-resident hardware                        |
|------------------------|---------------------------|------------------------|---------------------------------------------|
| `drone_isp`            | Image signal processing   | Dedicated ISP          | CSI-2 RX, line buffers, fixed-point pipe   |
| `drone_dsp`            | Pyramids / warps / HDR    | Cadence Vision DSP     | Wide SIMD, local SRAM, AGU                  |
| `drone_perception`     | Target ID, segmentation   | NPU                    | Local SRAM, MAC array, BF16/FP16 datapath   |
| `drone_vio`            | Visual-inertial odometry  | NPU + GPU + ARM        | Consumes DSP pyramid output                 |
| `drone_radar`          | Radar ingest, clustering  | ARM                    | DMA from radar IF, occupancy grid in DRAM   |
| `drone_radar` (fusion) | Camera+radar BEV fusion   | NPU                    | NPU, requires camera features in DRAM       |
| `drone_video_encode`   | H.264/H.265 encode        | Dedicated VPU          | Pixel pipeline, rate control                |
| `drone_behavior`       | Mission FSM, planner      | ARM application core   | L1/L2 cache, interrupt path                 |
| `drone_comms`          | Radio stack, framing      | ARM + modem            | Modem subsystem, DMA to MIPI/PCIe           |
| `drone_telemetry`      | (host-only — not deployed)| n/a                    | n/a                                         |
| (LLM, when active)     | On-device reasoning       | NPU (memory-bound)     | Large DRAM working set, LPDDR5x bandwidth   |
| PX4 SITL               | Flight control + EKF      | Cortex-M / RT core     | Tightly-coupled FPU, IMU/ESC peripherals    |
| Gazebo / Isaac Sim     | (host-only — not deployed)| n/a                    | n/a                                         |

**Camera path data flow (top to bottom):**

```
   [Camera sensor MIPI CSI-2]
            │
            ▼
   ┌──────────────────────┐
   │   ISP (drone_isp)    │  fixed-point pipeline, sustained line rate
   │   Bayer→RGB→YUV/CHW  │  raw → demosaic → tone map → LDC → output
   └──────────┬───────────┘
              │
   ┌──────────┴──────────────────┐
   │                             │
   ▼                             ▼
┌───────────────────┐   ┌─────────────────────┐
│ DSP (drone_dsp)   │   │ VPU (drone_video_   │
│ pyramids, flow    │   │     encode)         │
│ init, warps, HDR  │   │ H.265 to comms      │
└─────────┬─────────┘   └─────────────────────┘
          │
          ▼
┌────────────────────┐  ┌────────────────────┐
│ NPU (drone_        │  │ NPU (drone_vio)    │
│   perception)      │  │ feature extract +  │
│ SAM2/EdgeTAM/YOLO  │  │ pose optimization  │
└────────────────────┘  └────────────────────┘
```

The data path matters because each arrow is a DRAM round-trip on most SoCs.
A poorly-architected chip routes the image through DRAM 4-5 times before a
detection comes out; a well-architected one keeps it in on-chip SRAM
(ISP→DSP) and only touches DRAM at the NPU boundary. The bandwidth section
of the partition report shows this directly.

## Methodology: from sim to silicon

### Step 1 — Run the mission set

Run each mission under each precision config you care about. For BF16-vs-FP16
analysis the bare minimum is:

```bash
MODEL_PRECISION=bf16 ./scripts/run_mission.sh rescue_bird_full
MODEL_PRECISION=fp16 ./scripts/run_mission.sh rescue_bird_full
MODEL_PRECISION=int8 ./scripts/run_mission.sh rescue_bird_full
```

For competitive comparison, also run search_pattern (cruise floor) and
target_acquisition (peak). Three precisions × three missions = nine runs,
each ~3-7 minutes. Plan for one evening.

### Step 2 — The five numbers per subsystem

The analysis script extracts the following from each run, per subsystem:

1. **Peak TOPS (BF16-equivalent)** — derived from MAC count × frequency.
   This is what NPU spec sheets report. Compare directly to `npu_tops_bf16`
   in the candidate SoC profile.

2. **p99 latency per operation** — the latency you must guarantee, not the
   average. Real systems are sized by tail.

3. **DRAM bandwidth in/out** — per-edge bytes/sec from the bandwidth table.
   Sum the edges hitting a given engine to get its required DRAM BW share.
   Then compare to the SoC's *available* BW after subtracting CPU/encode draw.

4. **Working set** — peak resident bytes (model weights + activations + KV
   cache for transformer models). Drives NPU local SRAM sizing and informs
   whether weights can stay on-chip.

5. **Duty cycle per phase** — fraction of time the engine is active during
   each mission phase. Drives the average power calculation (peak ≠ avg).

### Step 3 — Project onto target SoC

The analysis script loads a target profile (e.g. `imx95.yaml`) and produces a
fit table. Each row is a subsystem×operation; columns are: required, budget,
delta, status. Anything overage is flagged.

Key projection assumptions baked into the script:

- **NPU efficiency factor.** A stream of MACs on an ideal NPU is rare. We
  apply a 0.6 efficiency factor (configurable in the profile) when comparing
  required TOPS to spec-sheet TOPS. Real silicon almost never hits 90%+
  utilization on transformer-heavy workloads.

- **DRAM BW headroom.** We require the sum of all engines' BW + 25% headroom
  to be below the SoC's published memory BW. The 25% reflects refresh /
  controller overhead / contention.

- **VPU pixel rate.** Encode is sized in Mpix/s = (W × H × fps). Compare
  directly to `vpu_h265_max_mpix_per_sec`.

- **Precision support.** If the candidate SoC lacks BF16 (`npu_supports_bf16:
  false`) and the workload was characterized in BF16, the report force-flags
  the gap. Either re-run in FP16 to get an apples-to-apples number or argue
  the BF16-only differentiator with this delta as evidence.

### Step 4 — Iterate the silicon spec

When a subsystem doesn't fit, the typical levers (in rough order of
preference) are:

1. **Compress the model.** Distillation, structured pruning, INT8 PTQ.
   Re-run the mission set; observe latency/accuracy delta.
2. **Add a memory channel.** Most often LPDDR5 x16 → x32 changes the picture.
3. **Add NPU local SRAM.** Cuts DRAM traffic; pays for itself if the bandwidth
   was the binding constraint.
4. **Move work between engines.** Some VIO front-end work moves cleanly to
   GPU, some to NPU; the right answer depends on which is closer to its
   ceiling in the report.
5. **Add an NPU tile.** Last resort; expensive in area and validation cost.

## Worked example: i.MX 95-class fit, rescue_bird_full

The shipped `imx95.yaml` profile is intentionally tight so the report has
something interesting to say. Running the full mission with EdgeTAM at BF16
should produce an envelope roughly like:

| subsystem        | operation         | p99 ms | tops_peak | status          |
|------------------|-------------------|--------|-----------|-----------------|
| perception       | edgetam_infer     | ~22    | ~1.4      | within budget   |
| vio              | feature_extract   | ~10    | ~0.4      | within budget   |
| video_encode     | h265_encode_frame | ~15    | n/a       | check VPU rate  |
| behavior         | fsm_tick          | <1     | negligible| within budget   |
| comms            | link_tx           | 5–25   | n/a       | within budget   |

(These numbers are placeholders driven by the stub models — your real run
will produce different ones once the actual TensorRT engines are wired in.)

The exercise is then: under PHASE_ACQUIRE, with both perception and VIO
running concurrently, does the *combined* DRAM bandwidth fit in 17 GB/s?
This is exactly the question your competitive analysis decks need a
data-driven answer to, and it's exactly what the bandwidth table in the
report produces.

## What this scaffold does not do

Three things you'll want to add as the project matures:

- **Power modeling.** This sim measures compute, not Joules. For power
  projections, you need either cycle-accurate models (slow, painful) or
  empirical W/op measurements from the candidate silicon itself.

- **Thermal/throttling.** Real edge SoCs throttle; the sim doesn't. Sustained
  scenarios on real hardware will reveal duty-cycle limits the sim can't.

- **Real model accuracy.** Latency/MAC count is decoupled from accuracy here.
  When you wire in real model weights, also capture mAP/IoU/etc. in the
  `extras` field of WorkloadRecord so the precision-comparison table can
  show accuracy delta alongside latency delta.

## Pointers

- Probe schema: `instrumentation/schemas/workload_record.py`
- Report generator: `instrumentation/analysis/soc_partition_report.py`
- Target profiles: `instrumentation/analysis/profiles/*.yaml`
- Add a new target profile: copy `imx95.yaml` and edit the numbers.
