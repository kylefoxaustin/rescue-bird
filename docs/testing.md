# Testing strategy

The rescue-bird project does two things — runs an instrumented SITL
pipeline, and projects per-subsystem demands analytically — and the test
strategy has to cover both. This doc lays out the layers from cheapest
to most expensive.

## Layer 1 — unit tests on the analytical model

Cheapest. Highest ROI. Covered by `tests/unit/`.

The workload model is pure math: given (profile, workload), produces
(demands, KPIs). Tests pin known inputs to expected outputs. When
algebra changes (or breaks), these catch it immediately.

Run with:
```
pytest tests/unit -v
```

Coverage targets:
- Each `*_demand` function: 3-5 representative inputs each
- Each KPI: the boundary case that flips PASS/WARN/FAIL
- Slider apply functions: confirm they actually mutate the right path
- Edge cases: zero, negative, wildly out-of-range — model should not
  crash, should produce sane fallbacks

## Layer 2 — golden-file tests on full configurations

`tests/golden/` holds JSON files capturing the full KPI evaluation for
representative configurations. The test runs the model against each
config and diffs against the golden file. Any model change that shifts
numbers triggers a test failure.

When the change is intentional, regenerate the golden file:
```
pytest tests/golden --update-goldens
```

This is the single highest-leverage test, because it catches
unintended model regressions instantly. When you're three months
deep in calibrating `npu_efficiency_factor` and accidentally break
the LLM bandwidth math, you find out on the next test run, not when
an executive asks why the chart shifted.

Configurations to lock in golden files:
- Default A720 baseline
- 6-camera 360° surround (the realistic default)
- LLM-active variant
- Fog mission (radar-heavy)
- Stress: 8MP × 60fps × HDR3 × 7B LLM
- Snapdragon comparison profile

## Layer 3 — integration tests on the SITL stack

End-to-end run validation. Not in the default test suite because they
need Docker + GPU access; run via `make integration` or in CI on
self-hosted runners with appropriate hardware.

What they verify:
- Every subsystem produces the expected number of records (perception
  @ 30fps × 60s mission ≈ 1800 records ± 10%)
- Latencies are within plausible ranges (no sub-microsecond, no >1s
  on routine ops)
- Bandwidth edges are populated correctly (sensor_ingest → perception
  edge exists with nonzero bytes)
- Phase transitions happen
- Glass-to-glass record gets emitted with all 7 stamps populated
- The partition report generates without errors

Stub models are fine for these tests — the point is structural
plumbing validation, not workload accuracy.

## Layer 4 — calibration runs against real models

This is where the project pays off. Replace the `_StubModel` in
`perception_node.py` with a real TensorRT-converted EdgeTAM, run the
mission, compare measured numbers against analytical projection.

Per the two-source design (ADR 001), every report column has measured
and projected side by side. Deltas above ~20% indicate a model
constant needs refinement.

The calibration constants worth refining first:
1. `npu.efficiency_factor` (currently 0.55, see ADR 009)
2. ISP per-stage `ns_per_pixel` table
3. DSP per-op `cycles_per_output_pixel` table

Calibration runs aren't automated — they're a manual workflow with a
spreadsheet of measurement deltas. Recommended cadence: monthly while
the project is active.

## Layer 5 — vendor tooling cross-checks

The SITL can't replace cycle-accurate vendor simulators. For the
silicon spec to land, cross-check key numbers against authoritative
sources:

| Subsystem | Tool to cross-check against |
|-----------|----------------------------|
| NPU       | Vendor profiler (ARM Streamline, eIQ Toolkit, TensorRT) |
| DSP       | Cadence Xtensa Xplorer / xt-clang cycle counts |
| VPU       | Vendor's published encode latency at given preset |
| ISP       | libcamera-style soft-ISP for correctness, vendor for timing |

When SITL projection and vendor tool agree, that's the gold-standard
data for the report.

## Layer 6 — real-hardware validation

Eventually some of this needs to run on actual silicon. Most of the
workload pieces have real-hardware reference implementations
already:
- PX4 on Pixhawk class flight controllers
- EdgeTAM on Jetson Orin (closest available silicon to A720+200 TOPS)
- libcamera ISP on Raspberry Pi 5
- Cadence Vision Q on dev boards via the Xtensa toolchain

A stripped-down rescue-bird stack on a Jetson AGX Orin is the most
practical "real silicon" target. Won't match the candidate i.MX-class
chip, but calibrates the analytical model against silicon that
exists.

## What's in scope right now

`tests/unit/` and `tests/golden/` skeletons exist. They're populated
with a starter set of cases enough to validate the framework. Adding
cases as new sliders or KPIs land is a one-liner per case.

Layers 3-6 are documented but not automated yet. They become valuable
once real model weights and silicon are in the picture.
