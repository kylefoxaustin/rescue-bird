"""Unit tests for the KPI evaluator.

KPIs are pass/fail — these tests pin the failure boundaries.
"""

from __future__ import annotations
import copy
import pytest
import yaml
from pathlib import Path

from instrumentation.analysis.whatif.workload_model import DEFAULT_WORKLOAD
from instrumentation.analysis.whatif.kpis import (
    evaluate, chip_summary,
    npu_kpis, cpu_kpis, vpu_kpis,
    isp_kpis, dsp_kpis,
    memory_bw_kpi, memory_capacity_kpi,
    g2g_latency_kpi,
)
from instrumentation.analysis.whatif.workload_model import all_demands


PROFILES_DIR = (
    Path(__file__).parent.parent.parent
    / "instrumentation" / "analysis" / "profiles"
)


@pytest.fixture
def a720_profile() -> dict:
    return yaml.safe_load((PROFILES_DIR / "rescue_bird_a720.yaml").read_text())


@pytest.fixture
def default_workload() -> dict:
    return copy.deepcopy(DEFAULT_WORKLOAD)


class TestDefaultConfig:
    """The default A720 profile + default workload should pass all KPIs."""

    def test_all_pass(self, a720_profile, default_workload):
        results = evaluate(a720_profile, default_workload)
        summary = chip_summary(results)
        assert summary["fail"] == 0, (
            f"Defaults should pass; got failures: {summary['failures']}"
        )

    def test_chip_marked_viable(self, a720_profile, default_workload):
        summary = chip_summary(evaluate(a720_profile, default_workload))
        assert summary["viable"] is True


class TestStressConfig:
    """A high-load config should produce specific known failures."""

    def test_8mp_60fps_hdr3_breaks_isp(self, a720_profile, default_workload):
        # Apply scale factors equivalent to the stress slider config
        default_workload["isp"]["streams"] = [
            {"name": "front_left", "megapixels": 8.0, "fps": 60, "hdr": 3, "purpose": "stereo_vio"},
            {"name": "front_right", "megapixels": 8.0, "fps": 60, "hdr": 3, "purpose": "stereo_vio"},
            {"name": "left", "megapixels": 4.0, "fps": 30, "hdr": 1, "purpose": "surround"},
            {"name": "right", "megapixels": 4.0, "fps": 30, "hdr": 1, "purpose": "surround"},
            {"name": "rear", "megapixels": 4.0, "fps": 30, "hdr": 1, "purpose": "surround"},
            {"name": "down", "megapixels": 4.0, "fps": 30, "hdr": 1, "purpose": "downward_obstacle"},
        ]
        results = evaluate(a720_profile, default_workload)
        failed_names = {r.name for r in results if r.status == "FAIL"}
        assert "isp_line_rate" in failed_names

    def test_7b_llm_active_breaks_memory_bw(self, a720_profile, default_workload):
        default_workload["llm"] = {
            "active": True, "params_b": 7, "tokens_per_sec": 20, "precision": "int8",
        }
        results = evaluate(a720_profile, default_workload)
        # 140 GB/s LLM > 36 GB/s available; memory_bw_total should fail
        failed_names = {r.name for r in results if r.status == "FAIL"}
        assert "memory_bw_total" in failed_names


class TestNpuKpis:
    def test_perception_fits_in_npu_at_default(self, a720_profile, default_workload):
        demands = all_demands(a720_profile, default_workload)
        results = npu_kpis(a720_profile, demands)
        perception_result = next(
            r for r in results if r.name == "perception_fits_in_npu"
        )
        assert perception_result.status == "PASS"

    def test_dropping_npu_to_20_tops_breaks_perception(self, a720_profile, default_workload):
        # Heavy perception model
        default_workload["perception"]["gmacs_per_inference"] = 200
        a720_profile["npu"]["tops_bf16"] = 20
        demands = all_demands(a720_profile, default_workload)
        results = npu_kpis(a720_profile, demands)
        perception_result = next(
            r for r in results if r.name == "perception_fits_in_npu"
        )
        assert perception_result.status == "FAIL"


class TestG2gKpi:
    def test_default_passes(self, a720_profile, default_workload):
        result = g2g_latency_kpi(a720_profile, default_workload)
        assert result.status in ("PASS", "WARN")

    def test_long_link_fails(self, a720_profile, default_workload):
        default_workload["link"]["rtt_ms"] = 200
        result = g2g_latency_kpi(a720_profile, default_workload)
        assert result.status == "FAIL"


class TestIspKpis:
    def test_concurrent_streams_kpi_present(self, a720_profile, default_workload):
        results = isp_kpis(a720_profile, default_workload)
        names = {r.name for r in results}
        assert "isp_concurrent_streams" in names
        assert "isp_line_rate" in names
        assert "csi2_lane_count" in names

    def test_too_many_streams_fails(self, a720_profile, default_workload):
        # Add 4 more cameras to default 6
        for i in range(4):
            default_workload["isp"]["streams"].append({
                "name": f"extra_{i}", "megapixels": 1.0, "fps": 15, "hdr": 1,
                "purpose": "surround",
            })
        results = isp_kpis(a720_profile, default_workload)
        streams_kpi = next(r for r in results if r.name == "isp_concurrent_streams")
        # Default profile has max_concurrent_streams: 8; we now have 10
        assert streams_kpi.status == "FAIL"


class TestChipSummary:
    def test_summary_counts_match(self, a720_profile, default_workload):
        results = evaluate(a720_profile, default_workload)
        summary = chip_summary(results)
        assert summary["pass"] + summary["warn"] + summary["fail"] == summary["total"]

    def test_failure_list_populated_on_fail(self, a720_profile, default_workload):
        # Force a failure
        a720_profile["npu"]["tops_bf16"] = 1
        default_workload["perception"]["gmacs_per_inference"] = 100
        results = evaluate(a720_profile, default_workload)
        summary = chip_summary(results)
        if summary["fail"] > 0:
            assert len(summary["failures"]) == summary["fail"]
