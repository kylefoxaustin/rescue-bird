# ADR 002: Per-subsystem ROS 2 nodes for partition fidelity

**Status:** Accepted
**Date:** 2026-04

## Context

The simulation could be structured as one monolithic process or as N
separate ROS 2 nodes. Monolithic is simpler to debug. Separate nodes are
more work but mirror real silicon better.

## Decision

Each logical block that maps to a distinct silicon engine gets its own
ROS 2 node, in its own container. Specifically: `drone_perception`,
`drone_vio`, `drone_radar`, `drone_isp`, `drone_dsp`, `drone_video_encode`,
`drone_behavior`, `drone_comms`. Plus host-only nodes `drone_telemetry`
that don't deploy.

## Alternatives considered

- **Monolithic Python process.** Rejected: process boundaries are how
  real silicon enforces engine isolation. Co-locating everything in one
  process makes the bandwidth measurements wrong (no DRAM round-trip for
  data passed in-process).
- **Threads in one node.** Rejected: same problem, plus the GIL hides
  realistic CPU contention.

## Consequences

- Every interface between subsystems goes through ROS 2 DDS or shared
  memory IPC, which is observable. The bandwidth section of the partition
  report wouldn't exist without this structure.
- Each container can be cgroup-isolated (CPU/memory limits) and
  GPU-pinned. Approximates engine isolation on real silicon.
- Per-node Docker containers cost build time and memory. Acceptable
  trade because it's a development tool, not a deployed system.
- Making this match production deployment is now a smaller delta — most
  ROS 2 packages port directly to a real platform once the engines are
  identified.

## Worth knowing

The ROS 2 message hop is not free — it adds 100-500µs of latency per
hop on a typical Linux box. That's much higher than the equivalent
SoC NoC traversal would be. For tight latency budgets (the radar →
behavior → flight command chain) this means the SITL latency
*overestimates* what real silicon would do. Subtract the ROS hop
overhead before reporting silicon-side latency.
