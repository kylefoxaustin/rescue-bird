# ADR 009: NPU efficiency factor of 0.55 default

**Status:** Accepted (provisional — needs measured calibration)
**Date:** 2026-04

## Context

Spec-sheet TOPS is peak. Real workloads achieve some fraction of peak.
The fraction depends on:
- Operator coverage in the NPU compiler
- Kernel sizes (small kernels underutilize wide MAC arrays)
- Memory bandwidth (compute stalls when activations don't arrive on time)
- Operator scheduling and parallelism

For transformer-heavy workloads (segmentation models, BEVFusion, LLM
prefill), efficiency typically lands 0.4-0.75. For convolutional models
with large kernels (e.g. ResNet50), efficiency can hit 0.7-0.85.

The number is contested. Vendors quote peak. Users measure 30-60%.
Optimization teams sweat for months to move the needle 5%.

## Decision

Default `npu.efficiency_factor` is 0.55. Sliders allow 0.30-0.90.

Rationale: 0.55 is the median of measured BF16 transformer workloads on
modern edge NPUs that I trust. Lower than 0.7 because rescue-bird is
transformer-heavy (SAM/TAM, BEVFusion). Higher than 0.4 because the
candidate silicon is in the post-2024 generation with mature compilers.

Every report that uses the analytical model is sensitive to this number
and should call it out when presenting results.

## Alternatives considered

- **0.7 default**: too optimistic for the workload class. Would produce
  reports that pass at default but fail in practice — exactly the
  failure mode this project exists to prevent.
- **0.4 default**: too pessimistic. Would over-spec the chip and lose
  the "we can fit on smaller silicon" arguments.
- **Per-operation efficiency**: more accurate but much more work to
  configure, and the data to pin per-op efficiency doesn't exist
  outside vendor labs. Maybe later.

## Consequences

- **This is the most-likely-to-be-wrong constant in the model.** It's
  also the most leveraged. Calibration against measured runs is the
  highest-priority refinement.
- The "two-source" approach (ADR 001) is what makes this defensible:
  when measurements come in, compare to projection, refine the
  constant. Without that loop, 0.55 is a guess.
- For competitive analysis, the slider lets the user show "even at
  0.4 efficiency this chip still meets the rescue-bird KPIs" — a
  stronger claim than "at 0.55 it works."

## Worth knowing

Three workloads to measure first, in priority order:
1. EdgeTAM at 1024×1024 BF16 (the headline rescue-bird perception model)
2. BEVFusion-small at the radar/camera fusion config
3. Whatever LLM size you're considering (3B or 7B)

Each measurement provides one calibration point. Three points
substantially constrain the constant.
