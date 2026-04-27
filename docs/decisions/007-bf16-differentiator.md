# ADR 007: Native BF16 on NPU as competitive differentiator

**Status:** Accepted
**Date:** 2026-04

## Context

Modern transformer-class vision models — SAM2, EdgeTAM, BEVFusion family,
many of the TAM-class detectors — are trained in BF16 and deploy best in
BF16 at the edge. BF16 has the same dynamic range as FP32 (8 exponent
bits) which matters for stable inference with the activation magnitudes
these models produce.

FP16 has only 5 exponent bits and silently saturates on large activations,
producing accuracy regressions that look like quantization noise. In
practice, FP16 deployment of a BF16-trained transformer needs per-layer
scaling and calibration that often costs 1-3% mAP / IoU.

INT8 fixes the dynamic range issue but requires post-training
quantization or QAT, which is a separate engineering task and
historically loses 1-5% accuracy unless done carefully.

The competitive landscape in this class:
- Some NPUs claim BF16 support natively in the MAC array
- Others quietly emulate BF16 via FP16 + scaling tricks
- Some don't support BF16 at all and the SDK silently downcasts

For the rescue-bird use case (SAM2/EdgeTAM-class perception, BEVFusion
for radar/camera), this is a real differentiator.

## Decision

The default A720 profile's NPU declares `npu.supports_bf16: true` and
exposes `tops_bf16` as a primary spec. The competitive profile
(`snapdragon.yaml`) declares `supports_bf16: false` and only exposes
`tops_fp16` and `tops_int8`.

The KPI evaluator flags any chip that lacks BF16 support when the
workload was characterized in BF16, with a clear note in the failure
message. The partition report's precision-sensitivity section
(section 4) shows the per-precision latency comparison directly.

## Alternatives considered

- **Treat BF16 vs FP16 as equivalent.** Rejected. The accuracy delta on
  segmentation models is real and operationally significant for rescue
  use cases (missed detection of partially-occluded survivors).
- **Quantize everything to INT8.** Acceptable for some workloads but not
  all — segmentation masks degrade noticeably under PTQ at INT8 without
  significant calibration work. Listed as an option via
  `perception_precision` slider but not the default.

## Consequences

- The NPU TOPS slider has effect at all three precisions (`bf16`, `fp16`,
  `int8`); the workload model picks the right one based on the
  perception precision setting.
- The competitive deck has a clean number to defend: "running SAM2 in
  native BF16 vs. FP16 emulation gives X% accuracy improvement at Y%
  latency cost."
- Sliders let the user move `perception_precision` to compare directly.

## Worth knowing

This is the most competitively-relevant single ADR in this set.
Quantifying the BF16 differentiator with measurements (not just spec
sheets) is the highest-leverage thing to do with the SITL stack. Run
the same model in BF16 and FP16 and put the numbers side-by-side in
the report.
