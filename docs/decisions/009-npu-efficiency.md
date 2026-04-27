# ADR 009: NPU efficiency factor of 0.55 default

**Status:** Moved to ratchet
**Moved on:** 2026-04 during the engine extraction (nightjar v0.3.0-dev)

This ADR has been migrated to the ratchet engine repository, where it now
lives as **ratchet ADR 005**:

> https://github.com/kylefoxaustin/ratchet/blob/main/docs/decisions/005-npu-efficiency.md

The 0.55 default lives in `ratchet.engine.demand.eff_tops` and is shared
by every sizer consuming the engine. This stub is preserved so that
historical references to "rescue-bird ADR 009" remain navigable.
