# ADR 011: Trajectory-driven test harness with measurement-only pilot model

**Status:** Pattern moved to ratchet; drone-specific instantiation stays in nightjar
**Moved on:** 2026-04 during the engine extraction (nightjar v0.3.0-dev)

The general pattern (deterministic profile generators + measurement-only
consumer model) has been migrated to the ratchet engine repository as
**ratchet ADR 006 — Trajectory-driven test harness pattern**:

> https://github.com/kylefoxaustin/ratchet/blob/main/docs/decisions/006-trajectory-test-harness.md

Nightjar's specific instantiation — the four flight scenarios
(`cruise_straight`, `gentle_maneuver`, `medium_maneuver`,
`aerobatic_forest`) and the latency-aware FPV pilot model — remains
drone-specific and lives in nightjar:

- `instrumentation/trajectories/trajectories.py`
- `instrumentation/pilots/latency_aware_pilot.py`

This stub is preserved so that historical references to "rescue-bird
ADR 011" remain navigable.
