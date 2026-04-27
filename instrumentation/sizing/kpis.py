"""Drone-specific KPI evaluator.

Generic engine KPIs (NPU/CPU/memory budget checks, KpiResult, evaluate_budget,
chip_summary, vpu_pixel_rate_kpi) live in ``ratchet.engine.kpi``. This module
adds the drone-specific KPIs (ISP line-rate fit, DSP cycle budget, glass-to-
glass latency, perception inference deadline, radar-to-command chain) and
wires them all together via the top-level ``evaluate()`` function.
"""

from __future__ import annotations

from ratchet.engine.kpi import (
    KpiResult,
    evaluate_budget,
    npu_kpis,
    cpu_kpis,
    vpu_pixel_rate_kpi,
    memory_bw_kpi,
    memory_capacity_kpi,
    chip_summary,                       # noqa: F401  (re-exported for callers)
)
from ratchet.engine.demand import SubsystemDemand

from .workload import (
    all_demands,
    glass_to_glass_ms,
    _DSP_OPS,
    _resolution_pixels,
)


# ──────────────────────────────────────────────────────────────────────
# Drone-specific KPIs
# ──────────────────────────────────────────────────────────────────────

def vpu_kpis(profile: dict, demands: list[SubsystemDemand], workload: dict) -> list[KpiResult]:
    """Sums Mpix/s across all encode streams. Real VPUs handle multiple
    concurrent streams; the relevant KPI is total pixel rate."""
    streams = workload.get("encode_streams")
    if streams:
        total_mpix = sum((s["megapixels"] * 1e6 * s["fps"]) / 1e6 for s in streams)
        notes = [f"{len(streams)} streams summed"]
    else:
        e = workload["encode"]
        pixels = _resolution_pixels(e["resolution_multiplier"])
        total_mpix = (pixels * e["fps"]) / 1e6
        notes = []

    headroom = profile.get("headroom_pct", {}).get("vpu", 20)
    return [vpu_pixel_rate_kpi(
        profile["vpu"],
        total_mpix_per_sec=total_mpix,
        headroom_pct=headroom,
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

    stream_summary = ", ".join(
        f"{s['name']}({s['megapixels']:.0f}MP@{s['fps']}fps)"
        + (f"x{s['hdr']}HDR" if s.get("hdr", 1) > 1 else "")
        for s in streams
    )

    results = [evaluate_budget(
        name="isp_line_rate",
        scope="subsystem", target="isp",
        metric="line_rate",
        required=total_line_rate_mpps,
        budget=available,
        units="Mpix/s",
        notes=[stream_summary],
    )]

    csi_lanes_required = total_csi_gbps / isp_p.get("csi2_max_gbps_per_lane", 4.5)
    results.append(evaluate_budget(
        name="csi2_lane_count",
        scope="subsystem", target="isp",
        metric="lanes",
        required=csi_lanes_required,
        budget=isp_p.get("csi2_lanes_total", 0),
        units="lanes",
    ))

    results.append(evaluate_budget(
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

    total_cycles_per_frame = 0
    for op_name in dsp_w.get("ops", []):
        if op_name in _DSP_OPS:
            cpp, pcf = _DSP_OPS[op_name]
            total_cycles_per_frame += (pixels * pcf * cpp) / simd_lanes

    required_gcycles_per_sec = (total_cycles_per_frame * fps) / 1e9
    available = dsp_p.get("giga_cycles_per_sec", 1.0) * dsp_p.get("efficiency_factor", 0.65)
    headroom = profile.get("headroom_pct", {}).get("dsp", 25)
    available_after_headroom = available * (1.0 - headroom / 100.0)

    return [evaluate_budget(
        name="dsp_cycle_budget",
        scope="subsystem", target="dsp",
        metric="gigacycles_per_sec",
        required=required_gcycles_per_sec,
        budget=available_after_headroom,
        units="Gcyc/s",
        notes=[f"ops={dsp_w.get('ops')}", f"@{dsp_w['input_megapixels']}MP × {fps}fps"],
    )]


def g2g_latency_kpi(profile: dict, workload: dict) -> KpiResult:
    g = glass_to_glass_ms(profile, workload)
    budget = profile.get("latency_budgets_ms", {}).get("glass_to_glass_p99", 100)
    breakdown = "  •  ".join(f"{k}: {v:.1f}ms" for k, v in g.items() if k != "total_ms")
    return evaluate_budget(
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
    return evaluate_budget(
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
    return evaluate_budget(
        name="radar_to_command",
        scope="cross_cutting", target="obstacle_avoidance",
        metric="latency_chain",
        required=chain,
        budget=budget,
        units="ms",
        notes=["Safety-critical: radar detection → behavior → flight command"],
    )


# ──────────────────────────────────────────────────────────────────────
# Top-level evaluator — wires drone demands + drone KPIs + engine KPIs
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
