# ADR 002: Per-subsystem ROS 2 nodes for partition fidelity

**Status:** Moved to ratchet (renamed)
**Moved on:** 2026-04 during the engine extraction (nightjar v0.3.0-dev)

This ADR has been migrated to the ratchet engine repository, where it now
lives as **ratchet ADR 002 — Per-subsystem process isolation for partition
fidelity**:

> https://github.com/kylefoxaustin/ratchet/blob/main/docs/decisions/002-per-subsystem-isolation.md

The principle is engine-generic (each measurable engine gets its own
process boundary so DMA-crossing measurements are real). Nightjar's
specific instantiation — per-subsystem ROS 2 nodes — is one application
of the pattern; the ratchet ADR generalizes the framing.
