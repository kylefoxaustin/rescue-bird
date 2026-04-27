"""Drone-specific what-if sizing — slider catalog, demand calculators, KPIs.

This package is the drone-vocabulary half of the original ``analysis/whatif``.
It depends on ratchet for engine primitives (Slider/SubsystemDemand/KpiResult
dataclasses, generic NPU/CPU/memory KPIs, llm_demand math, WhatifRunner).
"""
from .sliders import SLIDERS
from .workload import (
    DEFAULT_WORKLOAD,
    perception_demand,
    vio_demand,
    radar_demand,
    radar_fusion_demand,
    encode_demand,
    behavior_demand,
    comms_demand,
    isp_demand,
    dsp_demand,
    glass_to_glass_ms,
    all_demands,
)
from .kpis import (
    evaluate,
    isp_kpis,
    dsp_kpis,
    vpu_kpis,
    g2g_latency_kpi,
    perception_latency_kpi,
    radar_to_command_kpi,
)

__all__ = [
    "SLIDERS",
    "DEFAULT_WORKLOAD",
    "perception_demand",
    "vio_demand",
    "radar_demand",
    "radar_fusion_demand",
    "encode_demand",
    "behavior_demand",
    "comms_demand",
    "isp_demand",
    "dsp_demand",
    "glass_to_glass_ms",
    "all_demands",
    "evaluate",
    "isp_kpis",
    "dsp_kpis",
    "vpu_kpis",
    "g2g_latency_kpi",
    "perception_latency_kpi",
    "radar_to_command_kpi",
]
