"""Drone-specific slider catalog.

The Slider dataclass and apply/default-values machinery live in
``ratchet.engine.slider``. This module supplies the drone-flavored catalog:
the ``SLIDERS`` dict, plus camera/encode preset tables and the helper
functions referenced from slider .apply lambdas.

Sliders fall into four categories:

  1. SoC capability sliders     — change what the chip can do (NPU TOPS, etc.)
  2. Workload sliders           — change what the mission demands (model size,
                                  camera resolution, radar point rate, etc.)
  3. Operating-point sliders    — change deployment choices (precision, fusion
                                  mode, encode preset, link profile, etc.)
  4. Headroom / efficiency      — change the safety margins applied
"""

from __future__ import annotations

from ratchet.engine.slider import Slider, _set_path  # noqa: F401  (re-export _set_path? no — keep internal)


# ──────────────────────────────────────────────────────────────────────
# Encode presets — applied via the encode_preset slider
# ──────────────────────────────────────────────────────────────────────

_ENCODE_PRESETS = {
    0: [   # FPV only — no recording
        {"name": "fpv_forward", "megapixels": 2.0, "fps": 60, "low_latency": True, "bitrate_mbps": 8},
    ],
    1: [   # FPV + one recorded stream (e.g. front camera at full res for review)
        {"name": "fpv_forward", "megapixels": 2.0, "fps": 60, "low_latency": True,  "bitrate_mbps": 8},
        {"name": "record_fwd",  "megapixels": 4.0, "fps": 30, "low_latency": False, "bitrate_mbps": 12},
    ],
    2: [   # DEFAULT: FPV + 3 surround records (for post-flight review / forensics)
        {"name": "fpv_forward", "megapixels": 2.0, "fps": 60, "low_latency": True,  "bitrate_mbps": 8},
        {"name": "surround_l",  "megapixels": 1.0, "fps": 30, "low_latency": False, "bitrate_mbps": 2},
        {"name": "surround_r",  "megapixels": 1.0, "fps": 30, "low_latency": False, "bitrate_mbps": 2},
        {"name": "surround_b",  "megapixels": 1.0, "fps": 30, "low_latency": False, "bitrate_mbps": 2},
    ],
    3: [   # All streams recorded — forensic mode, max VPU pressure
        {"name": "fpv_forward",  "megapixels": 2.0, "fps": 60, "low_latency": True,  "bitrate_mbps": 8},
        {"name": "rec_fwd_l",    "megapixels": 4.0, "fps": 30, "low_latency": False, "bitrate_mbps": 10},
        {"name": "rec_fwd_r",    "megapixels": 4.0, "fps": 30, "low_latency": False, "bitrate_mbps": 10},
        {"name": "rec_left",     "megapixels": 2.0, "fps": 30, "low_latency": False, "bitrate_mbps": 4},
        {"name": "rec_right",    "megapixels": 2.0, "fps": 30, "low_latency": False, "bitrate_mbps": 4},
        {"name": "rec_rear",     "megapixels": 2.0, "fps": 30, "low_latency": False, "bitrate_mbps": 4},
        {"name": "rec_down",     "megapixels": 2.0, "fps": 30, "low_latency": False, "bitrate_mbps": 4},
    ],
}


def _apply_encode_preset(workload: dict, idx: int) -> None:
    streams = _ENCODE_PRESETS.get(idx, _ENCODE_PRESETS[2])
    workload["encode_streams"] = [dict(s) for s in streams]


# ──────────────────────────────────────────────────────────────────────
# Camera config presets — applied via the camera_config slider
# ──────────────────────────────────────────────────────────────────────

# Each preset is a list of streams (forward stereo first, then surround).
# Convention: forward streams have purpose="stereo_vio" and drive DSP load.
_CAMERA_PRESETS = {
    0: [   # stereo only — minimal "see forward"
        {"name": "front_left",  "megapixels": 4.0, "fps": 60, "hdr": 1, "purpose": "stereo_vio"},
        {"name": "front_right", "megapixels": 4.0, "fps": 60, "hdr": 1, "purpose": "stereo_vio"},
    ],
    1: [   # stereo + downward — adds takeoff/landing safety
        {"name": "front_left",  "megapixels": 4.0, "fps": 60, "hdr": 1, "purpose": "stereo_vio"},
        {"name": "front_right", "megapixels": 4.0, "fps": 60, "hdr": 1, "purpose": "stereo_vio"},
        {"name": "down",        "megapixels": 2.0, "fps": 30, "hdr": 1, "purpose": "downward_obstacle"},
    ],
    2: [   # stereo + 4 surround — DEFAULT for rescue bird (current setting)
        {"name": "front_left",  "megapixels": 4.0, "fps": 60, "hdr": 1, "purpose": "stereo_vio"},
        {"name": "front_right", "megapixels": 4.0, "fps": 60, "hdr": 1, "purpose": "stereo_vio"},
        {"name": "left",        "megapixels": 2.0, "fps": 30, "hdr": 1, "purpose": "surround"},
        {"name": "right",       "megapixels": 2.0, "fps": 30, "hdr": 1, "purpose": "surround"},
        {"name": "rear",        "megapixels": 2.0, "fps": 30, "hdr": 1, "purpose": "surround"},
        {"name": "down",        "megapixels": 2.0, "fps": 30, "hdr": 1, "purpose": "downward_obstacle"},
    ],
    3: [   # 6-cam true 360 — all uniform, useful for full-coverage surveillance
        {"name": f"cam{i}", "megapixels": 3.0, "fps": 30, "hdr": 1,
         "purpose": "stereo_vio" if i < 2 else "surround"} for i in range(6)
    ],
    4: [   # 8-cam dense — surround + stereo + up + down
        {"name": "front_left",  "megapixels": 4.0, "fps": 60, "hdr": 1, "purpose": "stereo_vio"},
        {"name": "front_right", "megapixels": 4.0, "fps": 60, "hdr": 1, "purpose": "stereo_vio"},
        {"name": "left_front",  "megapixels": 2.0, "fps": 30, "hdr": 1, "purpose": "surround"},
        {"name": "left_rear",   "megapixels": 2.0, "fps": 30, "hdr": 1, "purpose": "surround"},
        {"name": "right_front", "megapixels": 2.0, "fps": 30, "hdr": 1, "purpose": "surround"},
        {"name": "right_rear",  "megapixels": 2.0, "fps": 30, "hdr": 1, "purpose": "surround"},
        {"name": "up",          "megapixels": 1.5, "fps": 15, "hdr": 1, "purpose": "surround"},
        {"name": "down",        "megapixels": 2.0, "fps": 30, "hdr": 1, "purpose": "downward_obstacle"},
    ],
}


def _apply_camera_preset(workload: dict, idx: int) -> None:
    """Switch the camera stream list to a named preset, and update DSP n_streams
    to match the count of stereo_vio streams (the ones that need pyramids etc)."""
    streams = _CAMERA_PRESETS.get(idx, _CAMERA_PRESETS[2])
    # Deep copy so subsequent scale operations don't mutate the preset
    workload.setdefault("isp", {})["streams"] = [dict(s) for s in streams]
    forward = [s for s in streams if s.get("purpose") == "stereo_vio"]
    workload.setdefault("dsp", {})["n_streams"] = len(forward)
    if forward:
        workload["dsp"]["input_megapixels"] = forward[0]["megapixels"]
        workload["dsp"]["fps"] = forward[0]["fps"]


def _scale_streams(workload: dict, field: str, factor: float) -> None:
    """Multiply ``field`` by factor across all camera streams."""
    streams = workload.get("isp", {}).get("streams", [])
    for s in streams:
        if field in s:
            s[field] = s[field] * factor
    # Keep DSP in sync
    if field == "megapixels":
        forward = [s for s in streams if s.get("purpose") == "stereo_vio"]
        if forward:
            workload.setdefault("dsp", {})["input_megapixels"] = forward[0]["megapixels"]
    elif field == "fps":
        forward = [s for s in streams if s.get("purpose") == "stereo_vio"]
        if forward:
            workload.setdefault("dsp", {})["fps"] = forward[0]["fps"]


def _set_front_hdr(workload: dict, exposures: int) -> None:
    """HDR applies only to forward (FPV) streams — surround stays SDR."""
    streams = workload.get("isp", {}).get("streams", [])
    for s in streams:
        if s.get("purpose") == "stereo_vio":
            s["hdr"] = exposures


# ──────────────────────────────────────────────────────────────────────
# The catalog
# ──────────────────────────────────────────────────────────────────────

SLIDERS: dict[str, Slider] = {

    # ─── Capability sliders ──────────────────────────────────────────
    "npu_tops_bf16": Slider(
        name="npu_tops_bf16",
        description="Peak NPU BF16 TOPS",
        category="capability",
        units="TOPS",
        default=200, min_val=20, max_val=400, step=10,
        affects=["perception", "radar_fusion", "llm", "chip"],
        apply=lambda p, w, v: _set_path(p, "npu.tops_bf16", v),
    ),
    "npu_efficiency": Slider(
        name="npu_efficiency",
        description="Realized NPU utilization vs peak (transformer workloads rarely hit >60%)",
        category="capability",
        units="fraction",
        default=0.55, min_val=0.30, max_val=0.90, step=0.05,
        affects=["perception", "radar_fusion", "llm"],
        apply=lambda p, w, v: _set_path(p, "npu.efficiency_factor", v),
    ),
    "memory_channels": Slider(
        name="memory_channels",
        description="Number of LPDDR5x memory channels (each ~17 Gbps usable per channel)",
        category="capability",
        units="channels",
        default=2, min_val=1, max_val=4, step=1,
        affects=["memory_bw", "chip"],
        apply=lambda p, w, v: (
            _set_path(p, "memory.channels", int(v)),
            _set_path(p, "memory.bw_gbps", 34.0 * int(v)),
        ),
    ),
    "vpu_min_encode_latency_ms": Slider(
        name="vpu_min_encode_latency_ms",
        description="Minimum achievable encode latency in low-latency mode at 1080p",
        category="capability",
        units="ms",
        default=6, min_val=2, max_val=30, step=1,
        affects=["g2g_latency", "vpu", "chip"],
        apply=lambda p, w, v: _set_path(p, "vpu.min_encode_latency_ms", v),
    ),
    "cpu_cores": Slider(
        name="cpu_cores",
        description="Number of A720-class application cores",
        category="capability",
        units="cores",
        default=8, min_val=4, max_val=16, step=1,
        affects=["cpu", "behavior", "comms", "radar"],
        apply=lambda p, w, v: _set_path(p, "cpu.cores", int(v)),
    ),
    "isp_max_line_rate_mpps": Slider(
        name="isp_max_line_rate_mpps",
        description="ISP peak sustained line rate (Mpix/s)",
        category="capability",
        units="Mpix/s",
        default=1200, min_val=100, max_val=2400, step=100,
        affects=["isp", "chip"],
        apply=lambda p, w, v: _set_path(p, "isp.max_line_rate_mpps", v),
    ),
    "isp_concurrent_streams": Slider(
        name="isp_concurrent_streams",
        description="Max concurrent camera streams the ISP can handle",
        category="capability",
        units="streams",
        default=8, min_val=1, max_val=12, step=1,
        affects=["isp"],
        apply=lambda p, w, v: _set_path(p, "isp.max_concurrent_streams", int(v)),
    ),
    "csi2_lanes": Slider(
        name="csi2_lanes",
        description="Total MIPI CSI-2 lanes available across all cameras",
        category="capability",
        units="lanes",
        default=16, min_val=2, max_val=32, step=2,
        affects=["isp"],
        apply=lambda p, w, v: _set_path(p, "isp.csi2_lanes_total", int(v)),
    ),
    "dsp_count": Slider(
        name="dsp_count",
        description="Number of Cadence Vision Q-class DSPs",
        category="capability",
        units="cores",
        default=2, min_val=0, max_val=4, step=1,
        affects=["dsp", "chip"],
        apply=lambda p, w, v: (
            _set_path(p, "dsp.count", int(v)),
            _set_path(p, "dsp.giga_cycles_per_sec", int(v) * (p.get("dsp", {}).get("clock_mhz", 1100) / 1000.0)),
            _set_path(p, "dsp.present", int(v) > 0),
        ),
    ),
    "dsp_clock_mhz": Slider(
        name="dsp_clock_mhz",
        description="Vision DSP clock frequency",
        category="capability",
        units="MHz",
        default=1100, min_val=600, max_val=1500, step=100,
        affects=["dsp"],
        apply=lambda p, w, v: (
            _set_path(p, "dsp.clock_mhz", v),
            _set_path(p, "dsp.giga_cycles_per_sec",
                      p.get("dsp", {}).get("count", 1) * v / 1000.0),
        ),
    ),
    "dsp_simd_lanes": Slider(
        name="dsp_simd_lanes",
        description="DSP SIMD output lanes per cycle (int16). Q6=16, Q7=32, Q8=64.",
        category="capability",
        units="lanes",
        default=32, min_val=8, max_val=64, step=8,
        affects=["dsp"],
        apply=lambda p, w, v: _set_path(p, "dsp.simd_lanes_int16", int(v)),
    ),

    # ─── Workload sliders ────────────────────────────────────────────
    "perception_input_megapixels": Slider(
        name="perception_input_megapixels",
        description="Perception input resolution (MP)",
        category="workload",
        units="MP",
        default=1.0, min_val=0.3, max_val=12.0, step=0.5,
        affects=["perception", "memory_bw", "g2g_latency"],
        apply=lambda p, w, v: _set_path(w, "perception.input_megapixels", v),
    ),
    "perception_fps": Slider(
        name="perception_fps",
        description="Perception inference rate",
        category="workload",
        units="fps",
        default=30, min_val=5, max_val=120, step=5,
        affects=["perception", "memory_bw"],
        apply=lambda p, w, v: _set_path(w, "perception.fps", v),
    ),
    "perception_model_gmacs": Slider(
        name="perception_model_gmacs",
        description="Perception model MACs per inference (billions)",
        category="workload",
        units="GMAC",
        default=12.5, min_val=1, max_val=200, step=1,
        affects=["perception", "npu"],
        apply=lambda p, w, v: _set_path(w, "perception.gmacs_per_inference", v),
    ),
    "radar_points_per_frame": Slider(
        name="radar_points_per_frame",
        description="Radar points per frame (forest scene varies)",
        category="workload",
        units="points",
        default=1000, min_val=100, max_val=10000, step=100,
        affects=["radar", "memory_bw"],
        apply=lambda p, w, v: _set_path(w, "radar.points_per_frame", int(v)),
    ),
    "radar_hz": Slider(
        name="radar_hz",
        description="Radar frame rate",
        category="workload",
        units="Hz",
        default=20, min_val=5, max_val=50, step=5,
        affects=["radar", "memory_bw"],
        apply=lambda p, w, v: _set_path(w, "radar.hz", v),
    ),
    "encode_resolution": Slider(
        name="encode_resolution",
        description="Encoded video resolution (1=720p, 2=1080p, 4=4K)",
        category="workload",
        units="multiplier",
        default=2, min_val=1, max_val=4, step=1,
        affects=["vpu", "memory_bw", "g2g_latency"],
        apply=lambda p, w, v: _set_path(w, "encode.resolution_multiplier", v),
    ),
    "encode_fps": Slider(
        name="encode_fps",
        description="Encoded video frame rate",
        category="workload",
        units="fps",
        default=60, min_val=15, max_val=120, step=15,
        affects=["vpu", "memory_bw", "g2g_latency"],
        apply=lambda p, w, v: _set_path(w, "encode.fps", v),
    ),
    "encode_bitrate_mbps": Slider(
        name="encode_bitrate_mbps",
        description="Encoded video bitrate",
        category="workload",
        units="Mbps",
        default=8, min_val=1, max_val=50, step=1,
        affects=["link", "vpu"],
        apply=lambda p, w, v: _set_path(w, "encode.bitrate_mbps", v),
    ),
    "llm_active": Slider(
        name="llm_active",
        description="On-device LLM active (1=yes, 0=no). Adds load to NPU and memory.",
        category="workload",
        units="bool",
        default=0, min_val=0, max_val=1, step=1,
        affects=["llm", "npu", "memory_bw"],
        apply=lambda p, w, v: _set_path(w, "llm.active", bool(int(v))),
    ),
    "llm_model_b_params": Slider(
        name="llm_model_b_params",
        description="LLM model size in billions of parameters",
        category="workload",
        units="B",
        default=3, min_val=0.5, max_val=13, step=0.5,
        affects=["llm", "npu", "memory_bw"],
        apply=lambda p, w, v: _set_path(w, "llm.params_b", v),
    ),
    "llm_tokens_per_sec": Slider(
        name="llm_tokens_per_sec",
        description="Required LLM throughput",
        category="workload",
        units="tok/s",
        default=20, min_val=5, max_val=100, step=5,
        affects=["llm", "npu", "memory_bw"],
        apply=lambda p, w, v: _set_path(w, "llm.tokens_per_sec", v),
    ),
    "link_rtt_ms": Slider(
        name="link_rtt_ms",
        description="Wireless link RTT",
        category="workload",
        units="ms",
        default=20, min_val=5, max_val=200, step=5,
        affects=["g2g_latency", "comms"],
        apply=lambda p, w, v: _set_path(w, "link.rtt_ms", v),
    ),
    "camera_config": Slider(
        name="camera_config",
        description="Camera preset (0=stereo, 1=stereo+down, 2=stereo+4_surround, 3=6cam_360, 4=8cam_dense)",
        category="workload",
        units="enum",
        default=2, min_val=0, max_val=4, step=1,
        affects=["isp", "dsp", "memory_bw"],
        apply=lambda p, w, v: _apply_camera_preset(w, int(v)),
    ),
    "sensor_megapixels_scale": Slider(
        name="sensor_megapixels_scale",
        description="Multiplier on per-stream sensor MP (1.0=as configured, 2.0=double everything)",
        category="workload",
        units="multiplier",
        default=1.0, min_val=0.25, max_val=4.0, step=0.25,
        affects=["isp", "dsp", "memory_bw"],
        apply=lambda p, w, v: _scale_streams(w, "megapixels", v),
    ),
    "sensor_fps_scale": Slider(
        name="sensor_fps_scale",
        description="Multiplier on per-stream sensor fps",
        category="workload",
        units="multiplier",
        default=1.0, min_val=0.25, max_val=2.0, step=0.25,
        affects=["isp", "dsp", "memory_bw"],
        apply=lambda p, w, v: _scale_streams(w, "fps", v),
    ),
    "hdr_exposures": Slider(
        name="hdr_exposures",
        description="HDR exposures per FRONT camera (1=SDR, 3=HDR3 — surround stays SDR)",
        category="workload",
        units="exposures",
        default=1, min_val=1, max_val=4, step=1,
        affects=["isp", "memory_bw"],
        apply=lambda p, w, v: _set_front_hdr(w, int(v)),
    ),

    # ─── Operating-point sliders ─────────────────────────────────────
    "perception_precision": Slider(
        name="perception_precision",
        description="Perception precision (0=bf16, 1=fp16, 2=int8). Drives NPU effective TOPS.",
        category="operating",
        units="enum",
        default=0, min_val=0, max_val=2, step=1,
        affects=["perception", "npu"],
        apply=lambda p, w, v: _set_path(w, "perception.precision", ["bf16", "fp16", "int8"][int(v)]),
    ),
    "fusion_mode": Slider(
        name="fusion_mode",
        description="Camera+radar fusion mode (0=late, 1=bev_small, 2=bev_full, 3=transfusion)",
        category="operating",
        units="enum",
        default=1, min_val=0, max_val=3, step=1,
        affects=["radar_fusion", "npu"],
        apply=lambda p, w, v: _set_path(w, "radar_fusion.mode",
                                         ["late_fusion", "bev_fusion_small",
                                          "bev_fusion_full", "transfusion"][int(v)]),
    ),
    "encode_low_latency_mode": Slider(
        name="encode_low_latency_mode",
        description="Use VPU low-latency mode (1=yes, 0=no). Required for FPV.",
        category="operating",
        units="bool",
        default=1, min_val=0, max_val=1, step=1,
        affects=["g2g_latency", "vpu"],
        apply=lambda p, w, v: _set_path(w, "encode.low_latency_mode", bool(int(v))),
    ),
    "encode_preset": Slider(
        name="encode_preset",
        description="Encode streams (0=fpv_only, 1=fpv+1record, 2=fpv+3surround_record, 3=all_streams_recorded)",
        category="operating",
        units="enum",
        default=2, min_val=0, max_val=3, step=1,
        affects=["vpu", "memory_bw", "g2g_latency"],
        apply=lambda p, w, v: _apply_encode_preset(w, int(v)),
    ),

    # ─── Headroom sliders ────────────────────────────────────────────
    "npu_headroom_pct": Slider(
        name="npu_headroom_pct",
        description="Reserved NPU headroom (thermal + spike safety)",
        category="headroom",
        units="%",
        default=25, min_val=0, max_val=50, step=5,
        affects=["chip"],
        apply=lambda p, w, v: _set_path(p, "headroom_pct.npu", v),
    ),
    "memory_bw_headroom_pct": Slider(
        name="memory_bw_headroom_pct",
        description="Reserved memory bandwidth headroom",
        category="headroom",
        units="%",
        default=25, min_val=0, max_val=50, step=5,
        affects=["chip"],
        apply=lambda p, w, v: _set_path(p, "headroom_pct.memory_bw", v),
    ),
    "cpu_headroom_pct": Slider(
        name="cpu_headroom_pct",
        description="Reserved CPU headroom",
        category="headroom",
        units="%",
        default=30, min_val=0, max_val=60, step=5,
        affects=["chip"],
        apply=lambda p, w, v: _set_path(p, "headroom_pct.cpu", v),
    ),
    "isp_headroom_pct": Slider(
        name="isp_headroom_pct",
        description="Reserved ISP line-rate headroom",
        category="headroom",
        units="%",
        default=15, min_val=0, max_val=40, step=5,
        affects=["chip"],
        apply=lambda p, w, v: _set_path(p, "headroom_pct.isp", v),
    ),
    "dsp_headroom_pct": Slider(
        name="dsp_headroom_pct",
        description="Reserved DSP cycle headroom",
        category="headroom",
        units="%",
        default=25, min_val=0, max_val=50, step=5,
        affects=["chip"],
        apply=lambda p, w, v: _set_path(p, "headroom_pct.dsp", v),
    ),
}


# Backward-compat shims for sites that called the engine catalog helpers
# without the catalog argument. The unit tests still use these patterns.

def default_values() -> dict[str, float]:
    """Drone slider defaults."""
    from ratchet.engine.slider import default_values as _dv
    return _dv(SLIDERS)


def slider_categories() -> dict:
    """Drone slider catalog grouped by category."""
    from ratchet.engine.slider import slider_categories as _sc
    return _sc(SLIDERS)


def apply_sliders(profile: dict, workload: dict, values: dict[str, float]) -> None:
    """Apply drone slider overrides in-place."""
    from ratchet.engine.slider import apply_sliders as _apply
    _apply(SLIDERS, profile, workload, values)
