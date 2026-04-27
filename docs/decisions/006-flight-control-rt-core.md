# ADR 006: Cortex-M companion core for flight control

**Status:** Accepted
**Date:** 2026-04

## Context

The flight control loop (PID on body angular rates, motor mixing, IMU
integration) has hard real-time constraints set by physics, not software:
a quad's natural instability time constant is ~50-100ms. A control loop
that hiccups for >10ms diverges and crashes.

Concrete needs:
- IMU sampling at 1-8 kHz with microsecond jitter
- Bounded interrupt latency
- No GC pauses, no page faults, no scheduler surprises
- Loop-to-loop wall time stable within ~50 microseconds

Linux on the application complex cannot reliably do this. PREEMPT_RT
helps but is fragile. The well-understood answer is a separate small ARM
core running an RTOS or bare metal.

## Decision

The default A720 profile includes `rt_core.present: true` with a Cortex-M7
companion at 600 MHz, 256 KB TCM. PX4 SITL maps to this core in the
silicon partition table; on real silicon it would run NuttX or ChibiOS
bare-metal-ish.

The application complex (8× A720) runs Linux + ROS 2 + perception + comms
+ behavior. The two communicate via shared memory or RPMsg over the
chip-internal bus.

## Alternatives considered

- **PX4 on Linux with PREEMPT_RT**: rejected. Possible but fragile; the
  jitter floor under contention is too high.
- **External STM32 flight controller**: viable as a fallback. Many
  production drones do this with a $5 STM32 on the ESC bus. The model
  supports this case via `rt_core.present: false`, but the default
  assumes integrated companion core because that's where modern
  application-processor designs land.
- **ARM R-class cortex (e.g., Cortex-R52)**: viable, more capable than
  M7, costs more silicon. Reasonable upgrade path; profile would just
  set `rt_core.type: cortex_r52` and bump the clock.

## Consequences

- Flight control compute is treated as essentially "free" by the
  partition report — the M7 is so over-spec'd for kHz-rate scalar PID
  math that it doesn't drive any KPI.
- Inter-core communication latency (perception → behavior → flight
  command) becomes a real path that must be instrumented separately.
  This is the `radar_to_command_p99` chain in the KPIs.
- The companion-core integration is a real chip-design cost: shared
  cache, interrupt routing, secure inter-core messaging. Worth
  flagging to the silicon team but not modeled in detail.

## Worth knowing

The ROS 2 ↔ MAVLink hop in SITL is **not** representative of the
companion-core path — DDS over loopback is much slower than RPMsg
on chip. SITL latency for "AI says avoid → motor command" overstates
silicon by a factor of 5-10×. Adjust expectations accordingly when
reading the report.
