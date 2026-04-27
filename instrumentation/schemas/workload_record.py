"""Workload record schema.

Every probe in the system emits records with this shape. They land in Parquet files
under ./runs/<timestamp>/ and are aggregated by analysis/soc_partition_report.py.

Design philosophy: capture what matters for SoC partitioning, not what's easy to
collect. The fields below are chosen so that, given enough records across enough
mission scenarios, you can answer:

  - Per logical block: peak/sustained TOPS, memory footprint, bandwidth in/out
  - Per data path: tensor sizes and rates between blocks (= NoC requirements)
  - Per phase (search vs. acquire vs. track): duty cycle on each block
  - Per precision (BF16 vs FP16 vs INT8): accuracy delta and compute delta

The schema is deliberately wide and sparse. Probes fill in only the fields they
can measure cheaply.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Optional, Dict, Any
import time
import uuid


# Subsystem labels - these are what eventually map to silicon blocks. Keep stable.
SUBSYSTEM_PERCEPTION = "perception"
SUBSYSTEM_VIO = "vio"
SUBSYSTEM_VIDEO_ENCODE = "video_encode"
SUBSYSTEM_BEHAVIOR = "behavior"
SUBSYSTEM_COMMS = "comms"
SUBSYSTEM_FLIGHT_CONTROL = "flight_control"
SUBSYSTEM_SENSOR_INGEST = "sensor_ingest"
SUBSYSTEM_RADAR = "radar"                 # mmWave radar processing pipeline
SUBSYSTEM_RADAR_FUSION = "radar_fusion"   # camera+radar fusion (NPU workload)
SUBSYSTEM_LLM = "llm"                     # on-device LLM (mission reasoning, voice)
SUBSYSTEM_OCCUPANCY = "occupancy"         # 3D occupancy grid update
SUBSYSTEM_ISP = "isp"                     # Image Signal Processor pipeline
SUBSYSTEM_DSP = "dsp"                     # Cadence-class vision DSP (pyramids, HDR, etc.)

# Mission phase labels - duty-cycle analysis uses these.
PHASE_IDLE = "idle"
PHASE_TRANSIT = "transit"
PHASE_SEARCH = "search"
PHASE_ACQUIRE = "acquire"      # target detected, validating
PHASE_TRACK = "track"          # locked, following
PHASE_RTH = "return_to_home"


@dataclass
class WorkloadRecord:
    """Single observation from a probe.

    Records are append-only. Probes emit one per work unit (e.g. one inference,
    one encoded frame, one MAVLink batch). The aggregator buckets and rolls up
    later.
    """

    # ──── Identity ────
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = ""                  # ties all records in one mission run together
    t_wall_ns: int = field(default_factory=time.time_ns)
    t_sim_ns: Optional[int] = None    # sim clock, if available

    # ──── What was measured ────
    subsystem: str = ""               # one of SUBSYSTEM_*
    operation: str = ""               # free-form, e.g. "edgetam_decoder", "h265_encode"
    phase: str = PHASE_IDLE

    # ──── Compute ────
    latency_ns: Optional[int] = None
    macs: Optional[int] = None        # multiply-accumulates for this op (for TOPS calc)
    flops: Optional[int] = None
    precision: Optional[str] = None   # bf16 | fp16 | fp32 | int8 | int4 | mixed

    # ──── GPU resource snapshot at op time ────
    gpu_util_pct: Optional[float] = None
    gpu_mem_used_mb: Optional[float] = None
    gpu_mem_bw_gbps: Optional[float] = None    # measured or estimated DRAM BW
    sm_active_pct: Optional[float] = None
    tensor_core_active_pct: Optional[float] = None
    nvenc_util_pct: Optional[float] = None
    nvdec_util_pct: Optional[float] = None

    # ──── Data movement ────
    input_bytes: Optional[int] = None    # size of input tensor/frame
    output_bytes: Optional[int] = None   # size of output tensor/frame
    input_shape: Optional[str] = None    # e.g. "1x3x1024x1024"
    output_shape: Optional[str] = None

    # ──── Source/sink (for path analysis) ────
    src_subsystem: Optional[str] = None  # who produced the input
    dst_subsystem: Optional[str] = None  # who consumes the output

    # ──── Encode-specific ────
    encode_codec: Optional[str] = None
    encode_bitrate_kbps: Optional[float] = None
    encode_frame_size_bytes: Optional[int] = None
    encode_keyframe: Optional[bool] = None

    # ──── Comms-specific ────
    link_profile: Optional[str] = None   # wifi_suburban | 5g_lte | degraded
    link_rtt_ms: Optional[float] = None
    link_loss_pct: Optional[float] = None
    link_throughput_mbps: Optional[float] = None

    # ──── Flight-specific ────
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None
    pos_z: Optional[float] = None
    target_locked: Optional[bool] = None

    # ──── Radar-specific ────
    radar_n_points: Optional[int] = None        # points per frame
    radar_n_clusters: Optional[int] = None      # after clustering
    radar_n_tracks: Optional[int] = None        # tracked objects
    radar_format: Optional[str] = None          # raw_adc | range_doppler | point_cloud | tracks

    # ──── Glass-to-glass latency (end-to-end pilot path) ────
    # These are emitted by a dedicated end-to-end probe that timestamps a frame
    # at every stage. Only the final stage record fills all fields.
    g2g_capture_ns: Optional[int] = None        # camera shutter close
    g2g_isp_done_ns: Optional[int] = None
    g2g_encode_done_ns: Optional[int] = None
    g2g_tx_done_ns: Optional[int] = None
    g2g_rx_done_ns: Optional[int] = None
    g2g_decode_done_ns: Optional[int] = None
    g2g_display_ns: Optional[int] = None
    g2g_total_ms: Optional[float] = None

    # ──── LLM-specific (for on-device reasoning / voice command) ────
    llm_prompt_tokens: Optional[int] = None
    llm_output_tokens: Optional[int] = None
    llm_kv_cache_mb: Optional[float] = None
    llm_tokens_per_sec: Optional[float] = None

    # ──── ISP-specific ────
    isp_stage: Optional[str] = None                  # demosaic | blc | awb | tonemap | ldc | hdr_merge | scaler
    isp_input_format: Optional[str] = None           # bayer_rggb | bayer_grbg | yuv422 | rgb888
    isp_output_format: Optional[str] = None          # nv12 | yuv420 | rgb888 | tensor_chw
    isp_line_rate_mpps: Optional[float] = None       # megapixels/sec sustained
    isp_pixels_processed: Optional[int] = None
    isp_lanes_used: Optional[int] = None             # MIPI CSI-2 lanes consumed
    isp_hdr_exposures: Optional[int] = None          # 1 = SDR, 2-4 = HDR merge

    # ──── DSP-specific (Cadence Vision Q-class) ────
    dsp_op: Optional[str] = None                     # pyramid_build | warp | flow_init | hdr_merge | distortion
    dsp_pyramid_levels: Optional[int] = None
    dsp_kernel_size: Optional[int] = None
    dsp_simd_lanes: Optional[int] = None
    dsp_cycles: Optional[int] = None                 # cycle count if available
    dsp_clock_mhz: Optional[float] = None

    # ──── Free-form ────
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Schema for the PyArrow table - keeps Parquet writes consistent across probes.
# (Defined here so probes can import a single source of truth.)
import pyarrow as pa

WORKLOAD_SCHEMA = pa.schema([
    ("record_id", pa.string()),
    ("run_id", pa.string()),
    ("t_wall_ns", pa.int64()),
    ("t_sim_ns", pa.int64()),
    ("subsystem", pa.string()),
    ("operation", pa.string()),
    ("phase", pa.string()),
    ("latency_ns", pa.int64()),
    ("macs", pa.int64()),
    ("flops", pa.int64()),
    ("precision", pa.string()),
    ("gpu_util_pct", pa.float32()),
    ("gpu_mem_used_mb", pa.float32()),
    ("gpu_mem_bw_gbps", pa.float32()),
    ("sm_active_pct", pa.float32()),
    ("tensor_core_active_pct", pa.float32()),
    ("nvenc_util_pct", pa.float32()),
    ("nvdec_util_pct", pa.float32()),
    ("input_bytes", pa.int64()),
    ("output_bytes", pa.int64()),
    ("input_shape", pa.string()),
    ("output_shape", pa.string()),
    ("src_subsystem", pa.string()),
    ("dst_subsystem", pa.string()),
    ("encode_codec", pa.string()),
    ("encode_bitrate_kbps", pa.float32()),
    ("encode_frame_size_bytes", pa.int64()),
    ("encode_keyframe", pa.bool_()),
    ("link_profile", pa.string()),
    ("link_rtt_ms", pa.float32()),
    ("link_loss_pct", pa.float32()),
    ("link_throughput_mbps", pa.float32()),
    ("pos_x", pa.float32()),
    ("pos_y", pa.float32()),
    ("pos_z", pa.float32()),
    ("target_locked", pa.bool_()),
    # Radar
    ("radar_n_points", pa.int64()),
    ("radar_n_clusters", pa.int64()),
    ("radar_n_tracks", pa.int64()),
    ("radar_format", pa.string()),
    # Glass-to-glass
    ("g2g_capture_ns", pa.int64()),
    ("g2g_isp_done_ns", pa.int64()),
    ("g2g_encode_done_ns", pa.int64()),
    ("g2g_tx_done_ns", pa.int64()),
    ("g2g_rx_done_ns", pa.int64()),
    ("g2g_decode_done_ns", pa.int64()),
    ("g2g_display_ns", pa.int64()),
    ("g2g_total_ms", pa.float32()),
    # LLM
    ("llm_prompt_tokens", pa.int64()),
    ("llm_output_tokens", pa.int64()),
    ("llm_kv_cache_mb", pa.float32()),
    ("llm_tokens_per_sec", pa.float32()),
    # ISP
    ("isp_stage", pa.string()),
    ("isp_input_format", pa.string()),
    ("isp_output_format", pa.string()),
    ("isp_line_rate_mpps", pa.float32()),
    ("isp_pixels_processed", pa.int64()),
    ("isp_lanes_used", pa.int64()),
    ("isp_hdr_exposures", pa.int64()),
    # DSP
    ("dsp_op", pa.string()),
    ("dsp_pyramid_levels", pa.int64()),
    ("dsp_kernel_size", pa.int64()),
    ("dsp_simd_lanes", pa.int64()),
    ("dsp_cycles", pa.int64()),
    ("dsp_clock_mhz", pa.float32()),
])
