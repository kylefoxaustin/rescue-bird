"""Configurations to lock down with golden-file tests.

Each entry produces one snapshot. Add new ones by appending here, then
running `pytest tests/golden --update-goldens` to seed the JSON.

Naming convention: short, lowercase, underscored. Used as the JSON
snapshot filename.
"""

CONFIGURATIONS = {
    # ── Baseline: the realistic 6-camera 360 surround default ──
    "default_a720": {
        "profile": "rescue_bird_a720",
        "overrides": {},
    },

    # ── Stereo only: minimal config that should easily pass ──
    "stereo_only": {
        "profile": "rescue_bird_a720",
        "overrides": {"camera_config": 0},
    },

    # ── 6-camera true 360 (uniform) ──
    "true_360": {
        "profile": "rescue_bird_a720",
        "overrides": {"camera_config": 3},
    },

    # ── LLM-active variant: triggers memory_bw failure ──
    "llm_7b_active": {
        "profile": "rescue_bird_a720",
        "overrides": {
            "llm_active": 1,
            "llm_model_b_params": 7,
            "llm_tokens_per_sec": 20,
        },
    },

    # ── HDR3 on front cameras: triggers ISP overage ──
    "hdr3_front": {
        "profile": "rescue_bird_a720",
        "overrides": {"hdr_exposures": 3},
    },

    # ── Full stress: heavy perception + LLM + degraded link ──
    "stress_full": {
        "profile": "rescue_bird_a720",
        "overrides": {
            "perception_model_gmacs": 50,
            "perception_fps": 60,
            "fusion_mode": 2,                   # bev_fusion_full
            "llm_active": 1,
            "llm_model_b_params": 7,
            "link_rtt_ms": 100,
        },
    },

    # ── Snapdragon comparison profile (no native BF16) ──
    "snapdragon_baseline": {
        "profile": "snapdragon",
        "overrides": {},
    },

    # ── Minimal NPU sweep point: 50 TOPS ──
    "npu_50_tops": {
        "profile": "rescue_bird_a720",
        "overrides": {"npu_tops_bf16": 50},
    },

    # ── No DSP: model the GPU-fallback case for CV preprocessing ──
    "no_dsp_fallback": {
        "profile": "rescue_bird_a720",
        "overrides": {"dsp_count": 0},
    },

    # ── Single channel LPDDR: how bad does it get? ──
    "single_channel_memory": {
        "profile": "rescue_bird_a720",
        "overrides": {"memory_channels": 1},
    },
}
