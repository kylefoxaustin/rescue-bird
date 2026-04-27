# ADR 001: Two-source model — measured + projected

**Status:** Accepted
**Date:** 2026-04
**Decision drivers:** speed of iteration, defensibility of numbers,
calibration discipline.

## Context

The project has two inseparable goals:

1. **Sizing**: produce defensible numbers for an edge-SoC partitioning
   conversation (NPU TOPS, DSP cycles, ISP line rate, memory BW).
2. **Iteration**: explore "what if" questions in seconds, not days.

A pure-measurement approach (run the SITL stack, read the Parquet, write
the report) gives defensible numbers but takes 5-15 minutes per data point
and requires functioning real models for every subsystem. A pure-analytical
approach (math from spec sheets) iterates fast but isn't credible to anyone
who hasn't seen it line up against reality.

## Decision

Both, side by side. Every subsystem produces:
- **Measured** numbers from the SITL run (Parquet records via probes)
- **Projected** numbers from the analytical workload model

The partition report shows them in adjacent columns when both exist. The
delta is the calibration signal — when projection diverges from measurement,
the model's constants need refinement.

## Alternatives considered

- **Measured-only.** Rejected: the iteration loop is too slow for an
  executive what-if conversation. "Can we drop NPU TOPS by 30%?" can't
  require an overnight rerun.
- **Analytical-only.** Rejected: not credible. Anyone who's watched a real
  edge SoC underperform its spec sheet knows the constants matter.
- **Single source that switches mode.** Rejected: hides which numbers are
  measured vs. projected. The whole value is in seeing the delta.

## Consequences

- Workload model constants (`npu_efficiency_factor`, ISP `ns_per_pixel`,
  DSP `cycles_per_pixel`, etc.) become living artifacts. They start as
  best-guesses and get refined every time real measurements come in.
- The instrumentation framework has to work even when models are stubs —
  hence `_StubModel` with calibrated sleep times and the synthetic radar
  generator. The point is to validate the *plumbing* before the real
  models exist.
- Reports must clearly label which numbers came from where. The "delta
  column" is the most important UX in the report.

## Worth knowing

The most-likely-to-be-wrong constant is `npu_efficiency_factor=0.55`. Real
NPU efficiency on transformer workloads ranges 0.4-0.75 depending on
compiler, kernel sizes, and operator coverage. Calibrating that one
constant against measurements is high-leverage.
