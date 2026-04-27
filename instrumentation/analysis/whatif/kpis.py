"""kpis.py — KPI definitions and evaluation.

Each KPI is a named, tested constraint. KPIs come in three scopes:

  1. Per-subsystem KPIs    — does this block fit on its target engine?
  2. Cross-cutting KPIs    — shared resources (memory BW, latency budgets)
  3. Chip-wide KPIs        — is the whole chip viable for the rescue mission?

The evaluator runs every KPI against (profile, workload) and produces a
pass/fail status with margin (positive = headroom, negative = overage). The
final report has a one-line summary like:

    rescue_bird_a720 + default workload : 18/22 KPIs PASS
        FAIL: memory_bw_total_with_llm   (overage 4.2 GB/s of 17 GB/s budget)
        FAIL: g2g_latency_p99            (overage 18 ms of 100 ms budget)

That's the "is this chip viable?" answer in one number.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional
from .workload_model import (
    all_demands, glass_to_glass_ms, SubsystemDemand,
)


@dataclass
class KpiResult:
    name: str
    scope: str                    # subsystem | cross_cutting | chip
    target: str                   # which subsystem / engine
    metric: str
    required: float
    budget: float
    units: str
    status: str                   # PASS | FAIL | WARN
    margin: float                 # budget - required (positive is good)
    margin_pct: float
    notes: list[str] = field(default_factory=list)

    @property
    def emoji(self) -> str:
        return {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(self.status, "·")


def _evaluate(name: str, scope: str, target: str, metric: str,
              required: float, budget: float, units: str,
              warn_at_pct: float = 90.0,
              notes: Optional[list[str]] = None) -> KpiResult:
    """Build a KpiResult from required vs budget."""
    margin = budget - required
    margin_pct = (margin / budget * 100.0) if budget > 0 else 0.0
    if budget <= 0:
        status = "PASS" if required <= 0 else "FAIL"
    elif required > budget:
        status = "FAIL"
    elif required > budget * (warn_at_pct / 100.0):
        status = "WARN"
    else:
        status = "PASS"
    return KpiResult(
        name=name, scope=scope, target=target, metric=metric,
        required=required, budget=budget, units=units,
        status=status, margin=margin, margin_pct=margin_pct,
        notes=notes or [],
    )


# ──────────────────────────────────────────────────────────────────────
# Per-subsystem KPIs
# ──────────────────────────────────────────────────────────────────────

def npu_kpis(profile: dict, demands: list[SubsystemDemand]) -> list[KpiResult]:
    """One per NPU-resident subsystem: does it fit in the NPU's budget?"""
    npu = profile["npu"]
    eff_tops = npu["tops_bf16"] * npu.get("efficiency_factor", 0.55)
    headroom = profile.get("headroom_pct", {}).get("npu", 25)
    available = eff_tops * (1.0 - headroom / 100.0)

    results: list[KpiResult] = []
    npu_demands = [d for d in demands if d.target_engine == "npu"]
    for d in npu_demands:
        if d.tops_required <= 0:
            continue
        results.append(_evaluate(
            name=f"{d.name}_fits_in_npu",
            scope="subsystem", target=d.name,
            metric="TOPS",
            required=d.tops_required,
            budget=available,
            units="TOPS",
            notes=d.notes,
        ))
    # Sum-of-NPU check: do all NPU workloads together fit?
    total = sum(d.tops_required for d in npu_demands)
    results.append(_evaluate(
        name="npu_concurrent_workload",
        scope="cross_cutting", target="npu",
        metric="aggregate_TOPS",
        required=total,
        budget=available,
        units="TOPS",
        notes=["Sum of all NPU-bound workloads running concurrently"],
    ))
    return results


def cpu_kpis(profile: dict, demands: list[SubsystemDemand]) -> list[KpiResult]:
    cpu = profile["cpu"]
    eff_cores = cpu["cores"] * cpu.get("efficiency_factor", 0.7)
    headroom = profile.get("headroom_pct", {}).get("cpu", 30)
    available = eff_cores * (1.0 - headroom / 100.0)
    total = sum(d.cpu_cores_required for d in demands if d.target_engine == "cpu")
    return [_evaluate(
        name="cpu_fits",
        scope="cross_cutting", target="cpu",
        metric="effective_cores",
        required=total,
        budget=available,
        units="cores",
    )]


def vpu_kpis(profile: dict, demands: list[SubsystemDemand], workload: dict) -> list[KpiResult]:
    """Sums Mpix/s across all encode streams. Real VPUs handle multiple
    concurrent streams; the relevant KPI is total pixel rate."""
    vpu = profile["vpu"]
    headroom = profile.get("headroom_pct", {}).get("vpu", 20)
    available = vpu["h265_max_mpix_per_sec"] * (1.0 - headroom / 100.0)

    streams = workload.get("encode_streams")
    if streams:
        total_mpix = sum((s["megapixels"] * 1e6 * s["fps"]) / 1e6 for s in streams)
        notes = [f"{len(streams)} streams summed"]
    else:
        e = workload["encode"]
        from .workload_model import _resolution_pixels  # type: ignore
        pixels = _resolution_pixels(e["resolution_multiplier"])
        total_mpix = (pixels * e["fps"]) / 1e6
        notes = []

    return [_evaluate(
        name="vpu_pixel_rate",
        scope="subsystem", target="encode",
        metric="Mpix_per_sec",
        required=total_mpix,
        budget=available,
        units="Mpix/s",
        notes=notes,
    )]


def isp_kpis(profile: dict, workload: dict) -> list[KpiResult]:
    """Three KPIs: line-rate fit, CSI-2 lane count, concurrent stream count."""
    isp_p = profile.get("isp", {})
    if not isp_p.get("present", False):
        return []
    isp_w = workload["isp"]
    streams = isp_w.get("streams", [])
    if not streams:
        return []
    bit_depth = isp_w.get("bit_depth", 12)

    # Line rate: sum across all streams
    total_line_rate_mpps = 0.0
    total_csi_gbps = 0.0
    for s in streams:
        pixels = s["megapixels"] * 1e6
        fps = s["fps"]
        hdr = s.get("hdr", 1)
        total_line_rate_mpps += (pixels * fps * hdr) / 1e6
        total_csi_gbps += (pixels * fps * hdr * bit_depth) / 1e9

    headroom = profile.get("headroom_pct", {}).get("isp", 15)
    available = (
        isp_p.get("max_line_rate_mpps", 0)
        * isp_p.get("efficiency_factor", 0.85)
        * (1.0 - headroom / 100.0)
    )
    n_streams = len(streams)

    # Per-stream summary for the report
    stream_summary = ", ".join(
        f"{s['name']}({s['megapixels']:.0f}MP@{s['fps']}fps)"
        + (f"x{s['hdr']}HDR" if s.get("hdr", 1) > 1 else "")
        for s in streams
    )

    results = [_evaluate(
        name="isp_line_rate",
        scope="subsystem", target="isp",
        metric="line_rate",
        required=total_line_rate_mpps,
        budget=available,
        units="Mpix/s",
        notes=[stream_summary],
    )]

    csi_lanes_required = total_csi_gbps / isp_p.get("csi2_max_gbps_per_lane", 4.5)
    results.append(_evaluate(
        name="csi2_lane_count",
        scope="subsystem", target="isp",
        metric="lanes",
        required=csi_lanes_required,
        budget=isp_p.get("csi2_lanes_total", 0),
        units="lanes",
    ))

    results.append(_evaluate(
        name="isp_concurrent_streams",
        scope="subsystem", target="isp",
        metric="streams",
        required=n_streams,
        budget=isp_p.get("max_concurrent_streams", 1),
        units="streams",
    ))

    return results


def dsp_kpis(profile: dict, workload: dict) -> list[KpiResult]:
    """DSP: does the cycle budget cover the configured ops?"""
    dsp_p = profile.get("dsp", {})
    if not dsp_p.get("present", False):
        return []
    dsp_w = workload["dsp"]
    pixels = dsp_w["input_megapixels"] * 1e6
    fps = dsp_w["fps"]
    simd_lanes = dsp_p.get("simd_lanes_int16", 32)

    from .workload_model import _DSP_OPS  # type: ignore
    total_cycles_per_frame = 0
    for op_name in dsp_w.get("ops", []):
        if op_name in _DSP_OPS:
            cpp, pcf = _DSP_OPS[op_name]
            total_cycles_per_frame += (pixels * pcf * cpp) / simd_lanes

    required_gcycles_per_sec = (total_cycles_per_frame * fps) / 1e9
    available = dsp_p.get("giga_cycles_per_sec", 1.0) * dsp_p.get("efficiency_factor", 0.65)
    headroom = profile.get("headroom_pct", {}).get("dsp", 25)
    available_after_headroom = available * (1.0 - headroom / 100.0)

    return [_evaluate(
        name="dsp_cycle_budget",
        scope="subsystem", target="dsp",
        metric="gigacycles_per_sec",
        required=required_gcycles_per_sec,
        budget=available_after_headroom,
        units="Gcyc/s",
        notes=[f"ops={dsp_w.get('ops')}", f"@{dsp_w['input_megapixels']}MP × {fps}fps"],
    )]


def memory_bw_kpi(profile: dict, demands: list[SubsystemDemand]) -> KpiResult:
    mem = profile["memory"]
    eff = mem.get("controller_efficiency", 0.75)
    refresh = mem.get("refresh_overhead_pct", 5) / 100.0
    headroom = profile.get("headroom_pct", {}).get("memory_bw", 25)
    available = mem["bw_gbps"] * eff * (1.0 - refresh) * (1.0 - headroom / 100.0)
    total = sum(d.memory_bw_gbps for d in demands)
    return _evaluate(
        name="memory_bw_total",
        scope="chip", target="memory",
        metric="aggregate_BW",
        required=total,
        budget=available,
        units="GB/s",
        notes=["Sum across ALL subsystems concurrently. The most common chip-wide constraint."],
    )


def memory_capacity_kpi(profile: dict, demands: list[SubsystemDemand]) -> KpiResult:
    cap_gb = profile["memory"].get("capacity_gb_max", 16)
    total_mb = sum(d.memory_capacity_mb for d in demands)
    return _evaluate(
        name="memory_capacity",
        scope="chip", target="memory",
        metric="resident_set",
        required=total_mb,
        budget=cap_gb * 1024,
        units="MB",
    )


def g2g_latency_kpi(profile: dict, workload: dict) -> KpiResult:
    g = glass_to_glass_ms(profile, workload)
    budget = profile.get("latency_budgets_ms", {}).get("glass_to_glass_p99", 100)
    breakdown = "  •  ".join(f"{k}: {v:.1f}ms" for k, v in g.items() if k != "total_ms")
    return _evaluate(
        name="g2g_latency_p99",
        scope="chip", target="pilot_path",
        metric="end_to_end_latency",
        required=g["total_ms"],
        budget=budget,
        units="ms",
        notes=[f"Tree-dodging needs <100ms. Stages: {breakdown}"],
    )


def perception_latency_kpi(profile: dict, demands: list[SubsystemDemand]) -> KpiResult:
    perc = next((d for d in demands if d.name == "perception"), None)
    budget = profile.get("latency_budgets_ms", {}).get("perception_inference_p99", 50)
    required = perc.latency_ms_p99 if perc else 0
    return _evaluate(
        name="perception_latency",
        scope="subsystem", target="perception",
        metric="p99_latency",
        required=required,
        budget=budget,
        units="ms",
    )


def radar_to_command_kpi(profile: dict, demands: list[SubsystemDemand]) -> KpiResult:
    radar = next((d for d in demands if d.name == "radar"), None)
    fusion = next((d for d in demands if d.name == "radar_fusion"), None)
    behavior = next((d for d in demands if d.name == "behavior"), None)
    chain = sum(d.latency_ms_p99 for d in [radar, fusion, behavior] if d)
    budget = profile.get("latency_budgets_ms", {}).get("radar_to_command_p99", 30)
    return _evaluate(
        name="radar_to_command",
        scope="cross_cutting", target="obstacle_avoidance",
        metric="latency_chain",
        required=chain,
        budget=budget,
        units="ms",
        notes=["Safety-critical: radar detection → behavior → flight command"],
    )


# ──────────────────────────────────────────────────────────────────────
# Top-level evaluator
# ──────────────────────────────────────────────────────────────────────

def evaluate(profile: dict, workload: dict) -> list[KpiResult]:
    demands = all_demands(profile, workload)
    results: list[KpiResult] = []
    results.extend(isp_kpis(profile, workload))
    results.extend(dsp_kpis(profile, workload))
    results.extend(npu_kpis(profile, demands))
    results.extend(cpu_kpis(profile, demands))
    results.extend(vpu_kpis(profile, demands, workload))
    results.append(memory_bw_kpi(profile, demands))
    results.append(memory_capacity_kpi(profile, demands))
    results.append(g2g_latency_kpi(profile, workload))
    results.append(perception_latency_kpi(profile, demands))
    results.append(radar_to_command_kpi(profile, demands))
    return results


def chip_summary(results: list[KpiResult]) -> dict:
    """One-line health number."""
    n_total = len(results)
    n_pass = sum(1 for r in results if r.status == "PASS")
    n_warn = sum(1 for r in results if r.status == "WARN")
    n_fail = sum(1 for r in results if r.status == "FAIL")
    fails = [r for r in results if r.status == "FAIL"]
    return {
        "total": n_total,
        "pass": n_pass,
        "warn": n_warn,
        "fail": n_fail,
        "viable": n_fail == 0,
        "failures": [
            {
                "name": r.name,
                "metric": r.metric,
                "overage": -r.margin,
                "units": r.units,
            } for r in fails
        ],
    }
