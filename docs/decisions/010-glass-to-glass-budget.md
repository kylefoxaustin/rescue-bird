# ADR 010: Glass-to-glass <100ms for tree-dodging

**Status:** Accepted
**Date:** 2026-04

## Context

Remotely-piloted FPV drones have a hard latency ceiling for "operator
pilots through trees" use cases. The FPV racing community has converged
on this empirically:
- <50ms total: preferred (racing-class quads)
- <100ms total: workable (most commercial FPV)
- >150ms total: unflyable through thin obstacles at speed

The constraint is human reaction time + control loop coupling.

For a rescue drone dancing between branches in a forest at modest speed
(~10 m/s), 100ms is the right design target. Tighter is better but
chases diminishing returns.

## Decision

The default A720 profile sets `latency_budgets_ms.glass_to_glass_p99: 100`.
The `g2g_latency_p99` KPI evaluates the sum of:
- capture + ISP (~10-20ms, set by sensor + ISP block)
- encode (~5-15ms, set by VPU low-latency mode)
- transmit (~10-30ms good link, ~30-80ms degraded)
- decode (~5-15ms)
- display + pilot (~30-50ms, mostly pilot)

The `G2gProbe` instruments all 7 stages (capture, ISP done, encode done,
TX done, RX done, decode done, display) so the report shows where the
budget actually goes per run.

## Alternatives considered

- **Tighter budget (50ms)**: not necessary for the rescue use case at
  cruise speeds; would force expensive silicon choices (faster encode
  block, dedicated low-latency video transport) that don't pay back.
- **Looser budget (150ms)**: rejected. Tree-dodging at the use case
  speed becomes unsafe.
- **Different budgets per phase**: the `track` phase actually needs
  tighter latency than `transit`. Could add per-phase budgets later.
  Default is the worst case.

## Consequences

- VPU `min_encode_latency_ms` becomes a primary spec, not just peak
  Mpix/s. This is what makes "low-latency mode support" a hard
  requirement for the chip — see also ADR 005's notes on slice
  output and intra-refresh.
- The `link_rtt_ms` slider is high-leverage: switching from WiFi
  (~20ms) to degraded 5G (~80ms) eats most of the budget by itself.
- Encode resolution becomes a tradeoff: 4Kp60 looks great but adds
  ~10ms encode latency over 1080p60, which can flip pass to fail.

## Worth knowing

The pilot reaction time component (~30-50ms) is not silicon. The chip
team can't optimize past it. That's why "shave 5ms off encode" has
proportionally larger impact than it sounds — every ms saved in
silicon is a ms the pilot has to react.

For autonomous (no pilot) configurations the budget changes
completely. The drone's own perception → command loop replaces the
pilot's eyes-to-stick loop, and the relevant constraint is whatever
the AI policy needs to react to obstacles. That's typically 30-50ms,
which is *tighter* than the pilot case for the silicon side.
