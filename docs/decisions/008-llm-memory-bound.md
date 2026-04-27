# ADR 008: LLM workload modeled as memory-BW-bound

**Status:** Moved to ratchet
**Moved on:** 2026-04 during the engine extraction (nightjar v0.3.0-dev)

This ADR has been migrated to the ratchet engine repository, where it now
lives as **ratchet ADR 004**:

> https://github.com/kylefoxaustin/ratchet/blob/main/docs/decisions/004-llm-memory-bound.md

The LLM-is-bandwidth-bound math (`ratchet.engine.demand.llm_demand`) is
engine-level; nightjar consumes it. This stub is preserved so that
historical references to "rescue-bird ADR 008" remain navigable.
