# ADR 005: Cadence-class DSPs for classical CV preprocessing

**Status:** Accepted
**Date:** 2026-04

## Context

A lot of vision work isn't AI. Pyramid construction (Gaussian, Laplacian),
dense optical flow initialization, lens distortion correction, HDR merge,
panorama alignment, ORB/FAST keypoint detection — these run before any
neural network and consume meaningful compute.

These workloads are awkward:
- **Wrong shape for NPU**: small kernels (3×3, 5×5), low data reuse,
  irregular access patterns. NPU efficiency drops to ~20%.
- **Too parallel for CPU**: a 4MP × 5-level pyramid at 30fps is hundreds
  of GOPs. Burns 4-6 A-class cores.
- **Need predictable cycles**: VIO front-end consumes pyramid output at
  fixed wall-clock budget. Variable-latency execution drops VIO frames.

The Cadence Tensilica Vision Q-series (Q6 / Q7 / Q8) is the de facto
standard solution: ~1 GHz with very wide SIMD (512 / 1024 / 2048 bit) and
purpose-built address-generation units for bilinear interpolation and
geometric warps.

## Decision

The default A720 profile carries `dsp.present: true` with two Vision Q7
class DSPs (1024-bit SIMD, 1.1 GHz). The workload model includes a
`dsp_demand` calculator that sizes by (cycles per pixel × pixel count
factor × fps × n_streams) ÷ (clock × SIMD lanes × count).

Six DSP operations are catalogued with first-order cycle costs:
`pyramid_gaussian`, `pyramid_laplacian`, `lens_distortion`, `hdr_merge`,
`optical_flow_init`, `feature_pre`. Sliders pick which Q-class (lanes:
16/32/64), how many DSPs, and clock frequency.

## Alternatives considered

- **Push everything to the NPU.** Rejected for the reasons above —
  efficiency cliff, latency variance, no AGU for warps.
- **Push everything to the GPU.** Rejected because while a discrete GPU
  could do it, edge-class integrated GPUs are weak (~1 TFLOPS) and
  contend with 3D rendering for the same shaders.
- **Push to CPU SIMD.** Acceptable for ≤2 cameras at modest res; falls
  apart for the 6-camera 360° default. Flagged in the report as
  "fallback mode" if `dsp.present: false`.

## Consequences

- Asymmetric DSP load (forward stereo only, not surround) is explicit
  in the workload — see ADR 003.
- The `gigacycles_per_sec` budget vs requirement is a primary KPI in
  the partition report.
- DSPs add real silicon area; the spec needs to defend their
  inclusion. The report's DSP cycle table is the defense — it shows
  exactly what work would otherwise have to land on NPU/CPU.

## Worth knowing

The cycle costs in `_DSP_OPS` (and the parallel table in
`drone_dsp/dsp_node.py:DSP_OPS`) are first-order best-guesses. The
real way to refine them is the Cadence Xtensa Xplorer / xt-clang
toolchain — it emits cycle-accurate counts at compile time for
specific Vision Q variants. A 1-day refinement pass with someone
who has the toolchain converts these numbers from "credible" to
"defensible."
