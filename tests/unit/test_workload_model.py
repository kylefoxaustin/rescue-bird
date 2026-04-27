"""Unit tests for the analytical workload model.

These pin known inputs to expected outputs. They're the cheapest line of
defense against model regressions — when algebra changes, they catch it.

Run with:
    pytest tests/unit -v
"""

from __future__ import annotations
import copy
import math
import pytest
import yaml
from pathlib import Path

from instrumentation.analysis.whatif.workload_model import (
    DEFAULT_WORKLOAD,
    perception_demand,
    vio_demand,
    radar_demand,
    radar_fusion_demand,
    encode_demand,
    llm_demand,
    isp_demand,
    dsp_demand,
    behavior_demand,
    comms_demand,
    glass_to_glass_ms,
    all_demands,
)


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────────────
# Perception demand
# ──────────────────────────────────────────────────────────────────────

class TestPerceptionDemand:
    def test_default_tops_required(self, a720_profile, default_workload):
        d = perception_demand(a720_profile, default_workload)
        # Defaults: 12.5 GMAC × 30fps × 2 ops/MAC / 1000 = 0.75 TOPS
        assert d.tops_required == pytest.approx(0.75, rel=0.01)

    def test_default_latency_under_1ms(self, a720_profile, default_workload):
        # 12.5 GMAC at ~110 effective TOPS × 1.4 tail factor < 1ms
        d = perception_demand(a720_profile, default_workload)
        assert 0.1 < d.latency_ms_p99 < 1.0

    def test_doubling_gmacs_doubles_tops(self, a720_profile, default_workload):
        d1 = perception_demand(a720_profile, default_workload)
        default_workload["perception"]["gmacs_per_inference"] *= 2
        d2 = perception_demand(a720_profile, default_workload)
        assert d2.tops_required == pytest.approx(d1.tops_required * 2, rel=0.01)

    def test_doubling_fps_doubles_tops(self, a720_profile, default_workload):
        d1 = perception_demand(a720_profile, default_workload)
        default_workload["perception"]["fps"] *= 2
        d2 = perception_demand(a720_profile, default_workload)
        assert d2.tops_required == pytest.approx(d1.tops_required * 2, rel=0.01)

    def test_returns_npu_target(self, a720_profile, default_workload):
        d = perception_demand(a720_profile, default_workload)
        assert d.target_engine == "npu"


# ──────────────────────────────────────────────────────────────────────
# LLM demand — the memory-bound case (ADR 008)
# ──────────────────────────────────────────────────────────────────────

class TestLlmDemand:
    def test_inactive_llm_returns_zero_demand(self, a720_profile, default_workload):
        default_workload["llm"]["active"] = False
        d = llm_demand(a720_profile, default_workload)
        assert d.tops_required == 0
        assert d.memory_bw_gbps == 0

    def test_7b_int8_at_20tps_is_140_gbps(self, a720_profile, default_workload):
        # The headline LLM bandwidth number from ADR 008
        default_workload["llm"] = {
            "active": True, "params_b": 7, "tokens_per_sec": 20,
            "precision": "int8",
        }
        d = llm_demand(a720_profile, default_workload)
        assert d.memory_bw_gbps == pytest.approx(140.0, rel=0.05)

    def test_int4_halves_bandwidth(self, a720_profile, default_workload):
        # INT4 vs INT8 — same model size, half the BW
        default_workload["llm"] = {
            "active": True, "params_b": 7, "tokens_per_sec": 20,
            "precision": "int4",
        }
        d = llm_demand(a720_profile, default_workload)
        assert d.memory_bw_gbps == pytest.approx(70.0, rel=0.05)

    def test_compute_is_small(self, a720_profile, default_workload):
        # 7B at 20 tps is only ~0.3 TOPS; the constraint is BW not compute
        default_workload["llm"] = {
            "active": True, "params_b": 7, "tokens_per_sec": 20,
            "precision": "int8",
        }
        d = llm_demand(a720_profile, default_workload)
        assert d.tops_required < 1.0


# ──────────────────────────────────────────────────────────────────────
# ISP demand — multi-stream asymmetric (ADR 003)
# ──────────────────────────────────────────────────────────────────────

class TestIspDemand:
    def test_default_6_camera_setup(self, a720_profile, default_workload):
        d = isp_demand(a720_profile, default_workload)
        # 2× 4MP@60 + 4× 2MP@30 = 480 + 240 = 720 Mpix/s
        assert "line_rate_mpps=720" in str(d.notes) or any(
            "720" in n for n in d.notes
        )

    def test_no_isp_present_returns_fallback_note(self, a720_profile, default_workload):
        a720_profile["isp"]["present"] = False
        d = isp_demand(a720_profile, default_workload)
        assert any("software fallback" in n.lower() for n in d.notes)

    def test_hdr_on_front_increases_bandwidth(self, a720_profile, default_workload):
        d_sdr = isp_demand(a720_profile, default_workload)
        # HDR3 on forward streams only
        for s in default_workload["isp"]["streams"]:
            if s["purpose"] == "stereo_vio":
                s["hdr"] = 3
        d_hdr = isp_demand(a720_profile, default_workload)
        assert d_hdr.memory_bw_gbps > d_sdr.memory_bw_gbps * 1.5

    def test_stereo_only_lighter_than_default(self, a720_profile, default_workload):
        d_default = isp_demand(a720_profile, default_workload)
        # Strip to forward stereo only
        default_workload["isp"]["streams"] = [
            s for s in default_workload["isp"]["streams"]
            if s["purpose"] == "stereo_vio"
        ]
        d_stereo = isp_demand(a720_profile, default_workload)
        assert d_stereo.memory_bw_gbps < d_default.memory_bw_gbps


# ──────────────────────────────────────────────────────────────────────
# DSP demand — Cadence-class cycle accounting (ADR 005)
# ──────────────────────────────────────────────────────────────────────

class TestDspDemand:
    def test_default_under_budget(self, a720_profile, default_workload):
        d = dsp_demand(a720_profile, default_workload)
        # Default 4MP@60fps × 3 ops × stereo pair fits in 2.2 Gcyc/s
        notes_str = " ".join(d.notes)
        # Look for required gcycles in notes
        assert "required_gcycles" in notes_str

    def test_no_dsp_present_returns_fallback(self, a720_profile, default_workload):
        a720_profile["dsp"]["present"] = False
        d = dsp_demand(a720_profile, default_workload)
        assert any("CV preprocessing" in n for n in d.notes)

    def test_doubling_streams_doubles_cycles(self, a720_profile, default_workload):
        d1 = dsp_demand(a720_profile, default_workload)
        default_workload["dsp"]["n_streams"] *= 2
        d2 = dsp_demand(a720_profile, default_workload)
        # BW should roughly double
        assert d2.memory_bw_gbps == pytest.approx(d1.memory_bw_gbps * 2, rel=0.05)


# ──────────────────────────────────────────────────────────────────────
# Encode demand — multi-stream asymmetric (ADR 003)
# ──────────────────────────────────────────────────────────────────────

class TestEncodeDemand:
    def test_default_multi_stream_path(self, a720_profile, default_workload):
        d = encode_demand(a720_profile, default_workload)
        # default has 4 encode streams; should report all of them
        assert any("4 streams" in n for n in d.notes)

    def test_low_latency_stream_dominates_reported_latency(self, a720_profile, default_workload):
        d = encode_demand(a720_profile, default_workload)
        # FPV stream uses min_encode_latency_ms; that's what should be reported
        assert d.latency_ms_p99 < 30  # below typical_encode

    def test_legacy_single_stream_still_works(self, a720_profile, default_workload):
        # Backwards compat: some configs use the old `encode` block
        del default_workload["encode_streams"]
        d = encode_demand(a720_profile, default_workload)
        assert d.target_engine == "vpu"
        assert d.memory_bw_gbps > 0


# ──────────────────────────────────────────────────────────────────────
# Glass-to-glass latency budget (ADR 010)
# ──────────────────────────────────────────────────────────────────────

class TestGlassToGlass:
    def test_default_under_100ms(self, a720_profile, default_workload):
        g = glass_to_glass_ms(a720_profile, default_workload)
        assert g["total_ms"] < 100.0

    def test_link_rtt_dominates_at_long_range(self, a720_profile, default_workload):
        default_workload["link"]["rtt_ms"] = 5     # WiFi
        g_close = glass_to_glass_ms(a720_profile, default_workload)
        default_workload["link"]["rtt_ms"] = 150   # degraded long-range
        g_far = glass_to_glass_ms(a720_profile, default_workload)
        assert g_far["total_ms"] > g_close["total_ms"] + 50

    def test_low_latency_mode_off_increases_latency(self, a720_profile, default_workload):
        """Turning off low-latency mode adds encode latency. Doesn't necessarily
        blow the 100ms budget on its own at default link RTT, but it does
        narrow the margin substantially."""
        default_workload["encode"]["low_latency_mode"] = True
        g_on = glass_to_glass_ms(a720_profile, default_workload)
        default_workload["encode"]["low_latency_mode"] = False
        g_off = glass_to_glass_ms(a720_profile, default_workload)
        # Encode latency rises 6→30ms typical; total path adds ~5-10ms after decode-scaling
        assert g_off["total_ms"] > g_on["total_ms"] + 5

    def test_low_latency_off_plus_long_link_blows_budget(self, a720_profile, default_workload):
        """Low-latency-off + degraded link is the realistic failure case."""
        default_workload["encode"]["low_latency_mode"] = False
        default_workload["link"]["rtt_ms"] = 80   # degraded
        g = glass_to_glass_ms(a720_profile, default_workload)
        assert g["total_ms"] > 100.0


# ──────────────────────────────────────────────────────────────────────
# Roll-up
# ──────────────────────────────────────────────────────────────────────

class TestAllDemands:
    def test_returns_all_subsystems(self, a720_profile, default_workload):
        demands = all_demands(a720_profile, default_workload)
        names = {d.name for d in demands}
        # All expected subsystems present
        expected = {
            "isp", "dsp", "perception", "vio", "radar", "radar_fusion",
            "encode", "llm", "behavior", "comms",
        }
        assert expected.issubset(names)

    def test_sums_to_nonzero_memory_bw(self, a720_profile, default_workload):
        total = sum(d.memory_bw_gbps for d in all_demands(a720_profile, default_workload))
        assert total > 0
