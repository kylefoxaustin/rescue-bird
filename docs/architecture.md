# Architecture

## Process model

Every subsystem runs as its own ROS 2 node in its own container. This is
deliberate — it mirrors how the same logical blocks would land on dedicated
SoC engines in production silicon, and forces the data path between them to
go through observable interfaces.

```
┌────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ rb-sim         │    │ rb-perception    │    │ rb-behavior     │
│  • Gazebo      │    │  • SAM2/EdgeTAM  │    │  • Mission FSM  │
│  • PX4 SITL    │    │  • TensorRT      │    │  • py_trees     │
│  • IMU/cam pub │    │  • CUDA          │    │  • MAVLink out  │
└────────┬───────┘    └────────┬─────────┘    └────────┬────────┘
         │                     │                       │
         │ ROS 2 DDS (host network)                    │
         └─────────────────────┴───────────────────────┘
                               │
                ┌──────────────┴──────────────┐
                │                             │
        ┌───────▼────────┐           ┌────────▼────────┐
        │ rb-comms       │           │ rb-telemetry    │
        │  • NVENC pump  │           │  • aggregator   │
        │  • netem link  │           │  • host-only    │
        │  • MAVLink     │           └─────────────────┘
        └────────────────┘
```

## Data paths that dominate bandwidth

1. **Sensor → Perception → Behavior.** Camera frames at 30 fps × N MP × 3
   bytes. SAM2-class models keep most activations on-device; only detection
   and mask outputs cross to behavior. This path drives NPU input bandwidth.

2. **Sensor → Encode → Comms → Link.** Longest sustained bandwidth path on
   the SoC. Frame buffer → VPU → DRAM → modem DMA. Sizing the SoC's DRAM
   channel count almost always comes back to whether this path leaves
   headroom for perception during PHASE_ACQUIRE.

3. **IMU + Camera → VIO → FlightControl.** IMU at high rate (200–1000 Hz),
   camera at 30 fps. VIO reduces both to a 50–200 Hz pose stream. The small
   output size hides the fact that the *internal* bandwidth (feature maps,
   optimization state) is significant.

## Threading and timing

Each ROS 2 node uses a multi-threaded executor. The probe writers are
thread-safe and buffer in memory; flush is amortized over batches of 256
records by default. The hot path adds <1µs per probe call.

PX4 SITL uses real-time-ish scheduling on the sim's MAVLink loop. We do not
attempt to match production flight controller jitter — the sim is for
upstream stack characterization, not control loop tuning.

## Why ROS 2 + Docker, not bare metal

Two reasons. First, ROS 2 is what real production drone stacks use, so what
we measure here is representative. Second, putting each node in its own
container means we can pin GPU access, cgroup CPU/memory, and apply network
shaping per-process — matching how engine isolation works on a real SoC.
(You can't cgroup-shape the NPU, but the principle holds: enforce isolation
so contention is observable.)
