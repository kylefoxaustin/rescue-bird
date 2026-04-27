"""Drone-specific workload model — per-subsystem demand calculators.

The ``SubsystemDemand`` dataclass and the ``llm_demand`` math live in
``ratchet.engine.demand``. This module supplies the drone-shaped pieces:
``DEFAULT_WORKLOAD``, the per-subsystem demand calculators (perception,
VIO, radar, radar fusion, encode, behavior, comms, ISP, DSP), the
glass-to-glass latency model, and the ``all_demands`` roll-up.

The demand calculators are intentionally simple and inspectable. They're
first-order analytical estimates, not cycle-accurate simulators. The actual
mission telemetry from the SITL run is the ground truth for *measured*
numbers; the workload model provides *projected* numbers for what-if
analysis (see ratchet ADR 001 — two-source model).
"""

from __future__ import annotations

from ratchet.engine.demand import SubsystemDemand, eff_tops, llm_demand


# ──── Default workload parameters (overridden by sliders) ────
DEFAULT_WORKLOAD = {
    "perception": {
        "input_megapixels": 1.0,
        "fps": 30,
        "gmacs_per_inference": 12.5,
        "precision": "bf16",
        "output_kb_per_inference": 1.0,
    },
    "vio": {
        "input_megapixels": 0.3,
        "fps": 30,
        "gmacs_per_inference": 2.0,
        "precision": "fp16",
    },
    "radar": {
        "points_per_frame": 1000,
        "hz": 20,
        "format": "point_cloud",
    },
    "radar_fusion": {
        "mode": "bev_fusion_small",
    },
    "encode": {
        "resolution_multiplier": 2,    # 1=720p, 2=1080p, 4=4K
        "fps": 60,
        "bitrate_mbps": 8,
        "low_latency_mode": True,
    },
    "link": {
        "rtt_ms": 20,
    },
    "llm": {
        "active": False,
        "params_b": 3,
        "tokens_per_sec": 20,
        "precision": "int8",
    },
    "behavior": {
        "tick_hz": 50,
    },
    # ISP workload — multiple camera streams, possibly asymmetric.
    # Each stream has its own resolution, fps, and HDR config. The ISP must
    # sustain the SUM of line rates. This matches reality: a surround camera
    # system has high-res forward + lower-res peripheral cameras.
    "isp": {
        "streams": [
            # Forward stereo pair — drives VIO + obstacle avoidance + FPV
            {"name": "front_left",  "megapixels": 4.0, "fps": 60, "hdr": 1, "purpose": "stereo_vio"},
            {"name": "front_right", "megapixels": 4.0, "fps": 60, "hdr": 1, "purpose": "stereo_vio"},
            # Surround for situational awareness — lower res, lower fps, wider FOV
            {"name": "left",   "megapixels": 2.0, "fps": 30, "hdr": 1, "purpose": "surround"},
            {"name": "right",  "megapixels": 2.0, "fps": 30, "hdr": 1, "purpose": "surround"},
            {"name": "rear",   "megapixels": 2.0, "fps": 30, "hdr": 1, "purpose": "surround"},
            {"name": "down",   "megapixels": 2.0, "fps": 30, "hdr": 1, "purpose": "downward_obstacle"},
        ],
        "bit_depth": 12,           # raw Bayer bit depth, applies to all streams
    },
    # DSP workload — pyramids and warps run on the FORWARD stereo pair only.
    # Surround cameras don't need DSP preprocessing for VIO (they go straight
    # to perception NPU at lower res). This is a deliberate architectural
    # choice — running pyramids on all 6 cameras would burn DSP cycles for
    # no operational benefit.
    "dsp": {
        "input_megapixels": 4.0,       # forward camera res only
        "fps": 60,
        "n_streams": 2,                # forward stereo pair
        "ops": ["lens_distortion", "pyramid_gaussian", "optical_flow_init"],
        "pyramid_levels": 5,
    },
    # Encode workload — also asymmetric. Forward stream gets low-latency
    # mode for FPV; surround streams get high-compression mode for storage
    # and post-flight review. The VPU has to support concurrent streams
    # with different encode profiles.
    "encode_streams": [
        {"name": "fpv_forward", "megapixels": 2.0, "fps": 60, "low_latency": True,  "bitrate_mbps": 8},
        {"name": "surround_l",  "megapixels": 1.0, "fps": 30, "low_latency": False, "bitrate_mbps": 2},
        {"name": "surround_r",  "megapixels": 1.0, "fps": 30, "low_latency": False, "bitrate_mbps": 2},
        {"name": "surround_b",  "megapixels": 1.0, "fps": 30, "low_latency": False, "bitrate_mbps": 2},
    ],
}


# Reference resolutions for the encode multiplier
_ENCODE_RESOLUTIONS = {
    1: (1280, 720),
    2: (1920, 1080),
    3: (2560, 1440),
    4: (3840, 2160),
}


# Fusion model MACs (GMAC per fused frame)
_FUSION_GMACS = {
    "late_fusion":      0.05,
    "bev_fusion_small": 8.0,
    "bev_fusion_full":  45.0,
    "transfusion":      120.0,
}


# DSP op cycle costs — must match drone_dsp/dsp_node.py:DSP_OPS
# (cycles_per_output_pixel, pixel_count_factor)
_DSP_OPS = {
    "pyramid_gaussian":   (6,  1.33),
    "pyramid_laplacian":  (9,  1.33),
    "lens_distortion":    (12, 1.0),
    "hdr_merge":          (18, 3.0),
    "optical_flow_init":  (15, 1.33),
    "feature_pre":        (4,  1.0),
}


# ISP per-stage cycles per pixel (must match drone_isp/isp_node.py:ISP_STAGES)
# These are summed for total ns/pixel cost across the pipeline.
_ISP_STAGES_NS_PER_PIXEL = {
    "blc": 0.5, "lsc": 0.5, "dpc": 0.6, "demosaic": 2.5,
    "wb": 0.4, "ccm": 0.6, "hdr_merge": 1.5, "tonemap": 1.2,
    "ldc": 2.0, "nr_2d": 0.8, "nr_3d": 1.2, "sharpen": 0.5,
    "scaler_yuv": 0.7, "formatter": 0.3,
}


def _resolution_pixels(mult: float) -> int:
    w, h = _ENCODE_RESOLUTIONS[int(mult)]
    return w * h


# ──────────────────────────────────────────────────────────────────────
# Per-subsystem demand calculators
# ──────────────────────────────────────────────────────────────────────

def perception_demand(profile: dict, workload: dict) -> SubsystemDemand:
    p = workload["perception"]
    npu = profile["npu"]
    eff = eff_tops(npu, p["precision"])
    # 2 ops per MAC × GMAC × fps → required TOPS
    required = (2 * p["gmacs_per_inference"] * p["fps"]) / 1000.0
    # latency_ms = (2 × GMAC) / eff_TOPS × tail_factor
    if eff > 0:
        latency = (2 * p["gmacs_per_inference"]) / eff * 1.4
    else:
        latency = float("inf")
    # BW: input frame + output + activation traffic estimate (~3× input)
    pixels = p["input_megapixels"] * 1e6
    in_bytes_per_s = pixels * 3 * p["fps"]
    bw = (in_bytes_per_s * 4.0) / 1e9    # ×4 for activations crossing DRAM
    return SubsystemDemand(
        name="perception",
        target_engine="npu",
        tops_required=required,
        memory_bw_gbps=bw,
        memory_capacity_mb=512,           # weights + activations, model-dependent
        latency_ms_p99=latency,
    )


def vio_demand(profile: dict, workload: dict) -> SubsystemDemand:
    v = workload["vio"]
    npu = profile["npu"]
    eff = eff_tops(npu, v["precision"])
    required = (2 * v["gmacs_per_inference"] * v["fps"]) / 1000.0
    pixels = v["input_megapixels"] * 1e6
    bw = (pixels * 1 * v["fps"] * 3.0) / 1e9
    latency = ((2 * v["gmacs_per_inference"]) / eff) * 1.4 if eff > 0 else float("inf")
    return SubsystemDemand(
        name="vio",
        target_engine="npu",
        tops_required=required,
        memory_bw_gbps=bw,
        memory_capacity_mb=128,
        latency_ms_p99=max(5.0, latency),
    )


def radar_demand(profile: dict, workload: dict) -> SubsystemDemand:
    r = workload["radar"]
    # ARM compute: clustering + tracking. Model as fraction of 1 core.
    # ~0.5ms at 1000 points → at 20Hz is 1% of a core.
    points_per_sec = r["points_per_frame"] * r["hz"]
    cpu_cores = points_per_sec / 2_000_000     # 2M points/sec/core empirical
    # BW depends on format
    if r["format"] == "point_cloud":
        bw = points_per_sec * 16 * 4 / 1e9     # ×4 for processing passes
    elif r["format"] == "range_doppler":
        # 256 range × 128 doppler × 16 chirps × 2 bytes per cell
        bw = 256 * 128 * 16 * 2 * r["hz"] / 1e9
    else:  # raw_adc
        bw = 4 * 1e9                            # ~GB/s, big number
    return SubsystemDemand(
        name="radar",
        target_engine="cpu",
        cpu_cores_required=cpu_cores,
        memory_bw_gbps=bw,
        memory_capacity_mb=64,
        latency_ms_p99=15.0,
    )


def radar_fusion_demand(profile: dict, workload: dict) -> SubsystemDemand:
    rf = workload["radar_fusion"]
    r = workload["radar"]
    npu = profile["npu"]
    gmacs = _FUSION_GMACS.get(rf["mode"], 8.0)
    eff = eff_tops(npu, "bf16")
    required = (2 * gmacs * r["hz"]) / 1000.0
    latency = ((2 * gmacs) / eff) * 1.4 if eff > 0 else float("inf")
    bw = (r["points_per_frame"] * 16 + 1024 * 1024 * 3) * r["hz"] / 1e9
    return SubsystemDemand(
        name="radar_fusion",
        target_engine="npu",
        tops_required=required,
        memory_bw_gbps=bw,
        memory_capacity_mb=256,
        latency_ms_p99=latency,
    )


def encode_demand(profile: dict, workload: dict) -> SubsystemDemand:
    """Encode: handles either the legacy single-stream ``encode`` config or the
    multi-stream ``encode_streams`` list. The multi-stream case is the
    realistic one — FPV forward + lower-priority surround streams running
    on the same VPU with different latency/quality settings.

    The KPI that matters is total VPU pixel rate (sum across streams) and
    the worst-case (lowest) latency among streams that need low-latency
    mode (typically just the FPV stream).
    """
    vpu = profile["vpu"]
    streams = workload.get("encode_streams")

    if streams:
        # Multi-stream path
        total_pixel_rate_mpix = 0.0
        total_bw = 0.0
        worst_low_latency_ms = 0.0
        worst_normal_latency_ms = 0.0
        notes = []
        for s in streams:
            pixels = s["megapixels"] * 1e6
            fps = s["fps"]
            total_pixel_rate_mpix += (pixels * fps) / 1e6
            total_bw += (pixels * 3 * fps) / 1e9
            if s.get("low_latency", False):
                lat = vpu["min_encode_latency_ms"]
                worst_low_latency_ms = max(worst_low_latency_ms, lat)
            else:
                lat = vpu.get("typical_encode_latency_ms", 30)
                worst_normal_latency_ms = max(worst_normal_latency_ms, lat)
        # Reported latency is the FPV (low-latency) stream's, as that's the
        # one that matters for tree-dodging
        latency = worst_low_latency_ms if worst_low_latency_ms > 0 else worst_normal_latency_ms
        notes.append(f"{len(streams)} streams: " + ", ".join(
            f"{s['name']}({s['megapixels']:.0f}MP@{s['fps']}{'·LL' if s.get('low_latency') else ''})"
            for s in streams
        ))
        return SubsystemDemand(
            name="encode",
            target_engine="vpu",
            memory_bw_gbps=total_bw,
            memory_capacity_mb=64,
            latency_ms_p99=latency * 1.5,
            notes=notes,
        )

    # Legacy single-stream path
    e = workload["encode"]
    pixels = _resolution_pixels(e["resolution_multiplier"])
    if e["low_latency_mode"]:
        latency = vpu["min_encode_latency_ms"]
    else:
        latency = vpu.get("typical_encode_latency_ms", 30)
    bw = (pixels * 3 * e["fps"]) / 1e9
    notes = []
    if e["resolution_multiplier"] >= 4 and e["fps"] >= 60:
        notes.append("4Kp60 — verify VPU peak Mpix/s headroom")
    return SubsystemDemand(
        name="encode",
        target_engine="vpu",
        memory_bw_gbps=bw,
        memory_capacity_mb=64,
        latency_ms_p99=latency * 1.5,
        notes=notes,
    )


def behavior_demand(profile: dict, workload: dict) -> SubsystemDemand:
    return SubsystemDemand(
        name="behavior",
        target_engine="cpu",
        cpu_cores_required=0.05,         # FSM tick is cheap
        memory_bw_gbps=0.01,
        memory_capacity_mb=8,
        latency_ms_p99=2.0,
    )


def comms_demand(profile: dict, workload: dict) -> SubsystemDemand:
    e = workload["encode"]
    return SubsystemDemand(
        name="comms",
        target_engine="cpu",
        cpu_cores_required=0.3,           # MAVLink + RTSP packetization
        memory_bw_gbps=e["bitrate_mbps"] / 1000.0,
        memory_capacity_mb=32,
        latency_ms_p99=5.0,
    )


def isp_demand(profile: dict, workload: dict) -> SubsystemDemand:
    """ISP: line-rate-bound pipeline. Pass means the ISP can sustain the
    summed sensor pixel rate across all camera streams without dropping
    frames.

    Required line rate = Σ (W × H × fps × HDR_exposures) over all streams.
    Budget = ISP max_line_rate_mpps × efficiency × (1 - headroom).

    Bandwidth: Bayer ingest + intermediate buffers + output, summed across
    streams. Asymmetric multi-camera setups (high-res front + low-res
    surround) are common and correctly accounted for here.
    """
    isp_w = workload["isp"]
    isp_p = profile.get("isp", {})
    if not isp_p.get("present", False):
        return SubsystemDemand(
            name="isp", target_engine="isp",
            notes=["No ISP in profile; using software fallback (CPU/GPU)"],
        )

    streams = isp_w.get("streams", [])
    if not streams:
        return SubsystemDemand(name="isp", target_engine="isp",
                               notes=["No camera streams configured"])

    bit_depth = isp_w.get("bit_depth", 12)
    total_line_rate_mpps = 0.0
    total_bytes_per_sec = 0.0
    n_cameras = len(streams)
    for s in streams:
        pixels = s["megapixels"] * 1e6
        fps = s["fps"]
        hdr = s.get("hdr", 1)
        # Line rate
        total_line_rate_mpps += (pixels * fps * hdr) / 1e6
        # Bandwidth: raw in + RGB intermediate + NV12 out, ×HDR for merge
        total_bytes_per_sec += (
            pixels * fps * (bit_depth / 8.0 + 3.0 + 1.5) * hdr
        )

    bw = total_bytes_per_sec / 1e9

    # Latency: ISP is fully pipelined regardless of stream count.
    # Slight increase for many concurrent streams due to arbitration.
    latency = 3.0 + 0.2 * max(0, n_cameras - 2)

    notes = [f"line_rate_mpps={total_line_rate_mpps:.1f}"]
    if n_cameras > 2:
        notes.append(f"{n_cameras} streams: " + ", ".join(
            f"{s['name']}({s['megapixels']:.0f}MP@{s['fps']})" for s in streams
        ))

    return SubsystemDemand(
        name="isp",
        target_engine="isp",
        memory_bw_gbps=bw,
        memory_capacity_mb=n_cameras * 12,
        latency_ms_p99=latency,
        notes=notes,
    )


def dsp_demand(profile: dict, workload: dict) -> SubsystemDemand:
    """DSP: cycle-bound. Sum cycles for all configured ops per frame, multiply
    by fps × n_streams (DSP runs the pipeline once per camera that needs
    preprocessing — typically the forward stereo pair, not surround cams).

    Required cycles/sec = Σ (pixels × pixel_count_factor × cpp / simd_lanes)
                          × fps × n_streams
    """
    dsp_w = workload["dsp"]
    dsp_p = profile.get("dsp", {})
    if not dsp_p.get("present", False):
        return SubsystemDemand(
            name="dsp", target_engine="dsp",
            notes=["No DSP in profile; CV preprocessing falls to CPU/GPU"],
        )
    pixels = dsp_w["input_megapixels"] * 1e6
    fps = dsp_w["fps"]
    n_streams = dsp_w.get("n_streams", 1)
    simd_lanes = dsp_p.get("simd_lanes_int16", 32)

    total_cycles_per_frame = 0
    bw_bytes_per_frame = 0
    notes = []
    for op_name in dsp_w.get("ops", []):
        if op_name not in _DSP_OPS:
            notes.append(f"Unknown DSP op: {op_name}")
            continue
        cpp, pcf = _DSP_OPS[op_name]
        op_cycles = (pixels * pcf * cpp) / simd_lanes
        total_cycles_per_frame += op_cycles
        bw_bytes_per_frame += pixels * pcf * 6

    # Multiply by streams — each forward camera runs the full pipeline
    total_cycles_per_frame *= n_streams
    bw_bytes_per_frame *= n_streams

    required_gcycles_per_sec = (total_cycles_per_frame * fps) / 1e9
    bw = (bw_bytes_per_frame * fps) / 1e9

    available = dsp_p.get("giga_cycles_per_sec", 1.0) * dsp_p.get("efficiency_factor", 0.65)
    headroom = profile.get("headroom_pct", {}).get("dsp", 25)
    available_after_headroom = available * (1.0 - headroom / 100.0)

    clock_mhz = dsp_p.get("clock_mhz", 1000)
    count = dsp_p.get("count", 1)
    latency = (total_cycles_per_frame / (clock_mhz * 1e6 * count)) * 1000.0

    return SubsystemDemand(
        name="dsp",
        target_engine="dsp",
        memory_bw_gbps=bw,
        memory_capacity_mb=64,
        latency_ms_p99=latency,
        notes=notes + [
            f"required_gcycles/s={required_gcycles_per_sec:.2f}",
            f"available_gcycles/s={available_after_headroom:.2f}",
            f"streams={n_streams} @ {dsp_w['input_megapixels']}MP × {fps}fps",
        ],
    )


# ──────────────────────────────────────────────────────────────────────
# Glass-to-glass latency model (for tree-dodging)
# ──────────────────────────────────────────────────────────────────────

def glass_to_glass_ms(profile: dict, workload: dict) -> dict:
    """Sum all stages of the pilot path."""
    e = workload["encode"]
    vpu = profile["vpu"]
    pixels = _resolution_pixels(e["resolution_multiplier"])
    capture_isp = max(8, 1000.0 / e["fps"] + 4)
    encode_ms = vpu["min_encode_latency_ms"] if e["low_latency_mode"] else vpu.get("typical_encode_latency_ms", 30)
    # Encode also scales with pixel count
    encode_ms = encode_ms * (pixels / (1920 * 1080))
    tx_ms = workload["link"]["rtt_ms"] / 2 + 5
    decode_ms = encode_ms * 0.6
    display_pilot_ms = 35
    total = capture_isp + encode_ms + tx_ms + decode_ms + display_pilot_ms
    return {
        "capture_isp_ms": capture_isp,
        "encode_ms": encode_ms,
        "tx_ms": tx_ms,
        "decode_ms": decode_ms,
        "display_pilot_ms": display_pilot_ms,
        "total_ms": total,
    }


# ──────────────────────────────────────────────────────────────────────
# Roll-up
# ──────────────────────────────────────────────────────────────────────

def all_demands(profile: dict, workload: dict) -> list[SubsystemDemand]:
    return [
        isp_demand(profile, workload),
        dsp_demand(profile, workload),
        perception_demand(profile, workload),
        vio_demand(profile, workload),
        radar_demand(profile, workload),
        radar_fusion_demand(profile, workload),
        encode_demand(profile, workload),
        llm_demand(profile, workload),
        behavior_demand(profile, workload),
        comms_demand(profile, workload),
    ]
