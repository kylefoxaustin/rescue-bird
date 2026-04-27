"""Drone-specific subsystem and phase string constants.

These were previously colocated with WorkloadRecord but the record schema
moved to ratchet, which is site-agnostic. The labels themselves remain
nightjar-specific (a video sizer wouldn't have SUBSYSTEM_RADAR; an agentic
AI sizer wouldn't have PHASE_RTH).

Subsystem labels — these are what eventually map to silicon blocks in the
drone use case. Keep stable: probe records use these strings as the
``subsystem`` field, and the partition report groups by them.
"""

# Drone subsystem labels
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

# Mission phase labels — duty-cycle analysis uses these.
PHASE_IDLE = "idle"
PHASE_TRANSIT = "transit"
PHASE_SEARCH = "search"
PHASE_ACQUIRE = "acquire"      # target detected, validating
PHASE_TRACK = "track"          # locked, following
PHASE_RTH = "return_to_home"


__all__ = [
    "SUBSYSTEM_PERCEPTION", "SUBSYSTEM_VIO", "SUBSYSTEM_VIDEO_ENCODE",
    "SUBSYSTEM_BEHAVIOR", "SUBSYSTEM_COMMS", "SUBSYSTEM_FLIGHT_CONTROL",
    "SUBSYSTEM_SENSOR_INGEST",
    "SUBSYSTEM_RADAR", "SUBSYSTEM_RADAR_FUSION", "SUBSYSTEM_LLM",
    "SUBSYSTEM_OCCUPANCY", "SUBSYSTEM_ISP", "SUBSYSTEM_DSP",
    "PHASE_IDLE", "PHASE_TRANSIT", "PHASE_SEARCH",
    "PHASE_ACQUIRE", "PHASE_TRACK", "PHASE_RTH",
]
