# What-If KPIs and Sliders

The what-if engine turns the rescue-bird scaffold from a measurement harness
into a real sizing tool. You can answer questions like *"if we drop the NPU
from 200 TOPS to 100 TOPS, what fails?"* in seconds, without re-running the
mission.

## Two sources of numbers

The system is dual-source by design:

- **Measured** numbers come from real SITL mission runs (Parquet files
  emitted by probes). Use these for ground-truth reporting.
- **Projected** numbers come from the analytical workload model
  (`whatif/workload_model.py`). Use these for what-if exploration.

When you have measurements for a given configuration, the SoC partition
report shows both side-by-side, which lets you continuously refine the
analytical model's constants (`gmacs_per_inference`, `efficiency_factor`,
etc.) so projections stay calibrated to reality.

## The slider catalog

Every assumption knob lives in `whatif/sliders.py`. Categories:

**Capability sliders** (what the chip can do):
`npu_tops_bf16`, `npu_efficiency`, `memory_channels`,
`vpu_min_encode_latency_ms`, `cpu_cores`

**Workload sliders** (what the mission demands):
`perception_input_megapixels`, `perception_fps`, `perception_model_gmacs`,
`radar_points_per_frame`, `radar_hz`,
`encode_resolution`, `encode_fps`, `encode_bitrate_mbps`,
`llm_active`, `llm_model_b_params`, `llm_tokens_per_sec`,
`link_rtt_ms`

**Operating-point sliders** (deployment choices):
`perception_precision`, `fusion_mode`, `encode_low_latency_mode`

**Headroom sliders** (safety margins):
`npu_headroom_pct`, `memory_bw_headroom_pct`, `cpu_headroom_pct`

List them all with:
```bash
python -m instrumentation.analysis.whatif.whatif_cli list
```

## The KPI catalog

KPIs come in three scopes:

**Subsystem KPIs** — does this block fit on its target engine?
- `perception_fits_in_npu`
- `vio_fits_in_npu`
- `radar_fusion_fits_in_npu`
- `llm_fits_in_npu`
- `vpu_pixel_rate`
- `perception_latency`

**Cross-cutting KPIs** — shared resources:
- `npu_concurrent_workload` — sum of all NPU loads vs available
- `cpu_fits` — sum of CPU loads vs effective core budget
- `radar_to_command` — safety-critical latency chain

**Chip-wide KPIs**:
- `memory_bw_total` — the most common chip-wide constraint
- `memory_capacity` — resident-set fits
- `g2g_latency_p99` — tree-dodging budget (<100ms)

## Three modes of use

### Point evaluation

Evaluate at one configuration. Shows pass/fail per KPI plus chip-wide
summary.

```bash
# Default A720 + 200 TOPS, no LLM
python -m instrumentation.analysis.whatif.whatif_cli point

# Bump perception to 4MP @ 60fps with full BEV fusion and active LLM
python -m instrumentation.analysis.whatif.whatif_cli point \
    --set perception_input_megapixels=4 \
    --set perception_fps=60 \
    --set fusion_mode=2 \
    --set llm_active=1 \
    --set llm_model_b_params=7
```

The output is a Markdown table that drops directly into a slide.

### Single-axis sweep

Move one slider across its range, watch when KPIs flip.

```bash
# Where does the NPU run out?
python -m instrumentation.analysis.whatif.whatif_cli sweep \
    --slider npu_tops_bf16 --steps 12

# How does memory bandwidth pressure scale with camera resolution?
python -m instrumentation.analysis.whatif.whatif_cli sweep \
    --slider perception_input_megapixels --steps 10
```

### 2D Pareto sweep

Two sliders, grid of pass/fail. Great for "which is the right combination?"
slides.

```bash
# NPU TOPS × LLM size
python -m instrumentation.analysis.whatif.whatif_cli pareto \
    --x npu_tops_bf16 --y llm_model_b_params \
    --set llm_active=1

# Memory channels × encode resolution
python -m instrumentation.analysis.whatif.whatif_cli pareto \
    --x memory_channels --y encode_resolution
```

## Worked examples for the competitive deck

**"Why we need 200 TOPS, not 100":**
```bash
python -m instrumentation.analysis.whatif.whatif_cli sweep \
    --slider npu_tops_bf16 --steps 10 \
    --set fusion_mode=2 --set llm_active=1 --set llm_model_b_params=7
```
Shows that with full BEV fusion + 7B LLM, the chip becomes non-viable below
~150 TOPS. (The exact numbers depend on `npu_efficiency`, which is itself a
slider — defending the 0.55 default with measured data is part of the work.)

**"Why we need 2 LPDDR5x channels, not 1":**
```bash
python -m instrumentation.analysis.whatif.whatif_cli sweep \
    --slider memory_channels --steps 4 \
    --set perception_input_megapixels=4 --set encode_resolution=4
```
Shows the bandwidth-bound failure at 1 channel with 4K encode + 4MP
perception running concurrently.

**"Why low-latency VPU mode is non-negotiable":**
```bash
python -m instrumentation.analysis.whatif.whatif_cli sweep \
    --slider encode_low_latency_mode --steps 2
```
Two-step sweep that flips the g2g_latency_p99 KPI from PASS to FAIL.

**"BF16 vs FP16 differentiator quantified":**
```bash
python -m instrumentation.analysis.whatif.whatif_cli point \
    --set perception_precision=0   # bf16
python -m instrumentation.analysis.whatif.whatif_cli point \
    --set perception_precision=1   # fp16
```
Compare the perception latency / accuracy notes between the two.

## How the math works

The workload model (`whatif/workload_model.py`) is a first-order analytical
model. For each subsystem it computes:

- **TOPS required** = `2 × GMAC × fps / 1000`, then compared to
  `peak_TOPS × efficiency_factor × (1 - headroom)`
- **Memory bandwidth** = ingress + egress + activation traffic estimate
- **Latency p99** = `MACs / effective_TOPS × tail_factor`
- **Capacity** = working set (weights + activations + KV cache for LLM)

The model is intentionally inspectable — every constant is in the source
and easy to argue about. When measurements come in, the constants get
calibrated. The point is fast iteration, not cycle accuracy.

## Safety margins

The analytical model assumes:

- **NPU efficiency factor** of 0.55 (transformer-heavy workloads). Real
  workloads can range 0.4–0.75; benchmark and refine.
- **Memory controller efficiency** of 0.75 (after refresh and arbitration).
- **Tail latency factor** of 1.4 over mean (p99 is typically 30-50% above
  mean for steady-state workloads).
- **Default headroom** of 25% on NPU and memory BW, 30% on CPU.

All of these are sliders — move them and see what happens.
