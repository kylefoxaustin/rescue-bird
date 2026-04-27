"""Unit tests for slider apply functions."""

from __future__ import annotations
import copy
import pytest
import yaml
from pathlib import Path

from instrumentation.sizing.workload import DEFAULT_WORKLOAD
from instrumentation.sizing.sliders import (
    SLIDERS, default_values, apply_sliders, slider_categories,
)


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


class TestSliderCatalog:
    def test_categories_present(self):
        cats = slider_categories()
        assert "capability" in cats
        assert "workload" in cats
        assert "operating" in cats
        assert "headroom" in cats

    def test_all_sliders_have_clamp_method(self):
        for s in SLIDERS.values():
            assert s.clamp(s.default) == s.default
            assert s.clamp(s.min_val - 100) == s.min_val
            assert s.clamp(s.max_val + 100) == s.max_val

    def test_all_apply_functions_callable(self):
        for s in SLIDERS.values():
            assert s.apply is None or callable(s.apply)


class TestSliderApply:
    def test_npu_tops_slider_mutates_profile(self, a720_profile, default_workload):
        values = default_values()
        values["npu_tops_bf16"] = 50.0
        apply_sliders(a720_profile, default_workload, values)
        assert a720_profile["npu"]["tops_bf16"] == 50.0

    def test_camera_config_preset_changes_streams(self, a720_profile, default_workload):
        values = default_values()
        values["camera_config"] = 0   # stereo only
        apply_sliders(a720_profile, default_workload, values)
        streams = default_workload["isp"]["streams"]
        assert len(streams) == 2
        assert all(s["purpose"] == "stereo_vio" for s in streams)

    def test_camera_config_preset_3_is_6_uniform(self, a720_profile, default_workload):
        values = default_values()
        values["camera_config"] = 3
        apply_sliders(a720_profile, default_workload, values)
        streams = default_workload["isp"]["streams"]
        assert len(streams) == 6

    def test_sensor_megapixels_scale_doubles_resolution(self, a720_profile, default_workload):
        original = [s["megapixels"] for s in default_workload["isp"]["streams"]]
        values = default_values()
        values["sensor_megapixels_scale"] = 2.0
        apply_sliders(a720_profile, default_workload, values)
        for orig, s in zip(original, default_workload["isp"]["streams"]):
            assert s["megapixels"] == pytest.approx(orig * 2)

    def test_hdr_exposures_only_affects_forward_streams(self, a720_profile, default_workload):
        values = default_values()
        values["hdr_exposures"] = 3
        apply_sliders(a720_profile, default_workload, values)
        for s in default_workload["isp"]["streams"]:
            if s["purpose"] == "stereo_vio":
                assert s["hdr"] == 3
            else:
                assert s["hdr"] == 1   # surround stays SDR

    def test_memory_channels_recomputes_bw(self, a720_profile, default_workload):
        values = default_values()
        values["memory_channels"] = 4
        apply_sliders(a720_profile, default_workload, values)
        # Slider sets bw_gbps = 34 × channels
        assert a720_profile["memory"]["bw_gbps"] == pytest.approx(34.0 * 4)

    def test_dsp_count_zero_disables_dsp(self, a720_profile, default_workload):
        values = default_values()
        values["dsp_count"] = 0
        apply_sliders(a720_profile, default_workload, values)
        assert a720_profile["dsp"]["present"] is False

    def test_llm_active_slider_toggles_workload(self, a720_profile, default_workload):
        values = default_values()
        values["llm_active"] = 1
        apply_sliders(a720_profile, default_workload, values)
        assert default_workload["llm"]["active"] is True


class TestDefaultsAreSelfConsistent:
    """Smoke test: applying just the defaults shouldn't break anything."""

    def test_default_values_apply_cleanly(self, a720_profile, default_workload):
        values = default_values()
        # Should not raise
        apply_sliders(a720_profile, default_workload, values)
        # Profile and workload should still be valid dicts
        assert "npu" in a720_profile
        assert "isp" in default_workload
        assert "streams" in default_workload["isp"]
