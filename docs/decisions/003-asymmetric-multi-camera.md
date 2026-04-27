# ADR 003: Asymmetric multi-camera as the realistic default

**Status:** Accepted
**Date:** 2026-04
**Supersedes:** earlier "uniform N×8MP" defaults

## Context

Initial scaffold defaulted to uniform camera config (N cameras × same MP ×
same fps). That produced unrealistic load numbers — the "8MP × 120fps × 6
cameras for 360° surround" stress case demanded 11 Gpix/s of ISP, which is
not what a real rescue drone uses.

Real autonomous platforms (Tesla, BMW surround systems, modern military
drones) use **asymmetric resolution and frame rate per camera role**:
- Forward stereo or fisheye: high res (4-8MP), high fps (60), often HDR
- Surround / peripheral: lower res (1-3MP), lower fps (15-30), SDR
- Downward (takeoff/landing safety): mid res (2MP), 30fps
- Sometimes upward (only during specific maneuvers)

The pilot only sees the forward stream in real time; surround cameras feed
the AI for situational awareness ("did something move behind us") and
post-flight forensic review. They don't need the same encode latency or
quality budget.

## Decision

Default workload uses six asymmetric streams:
- 2× forward (4MP @ 60fps, HDR-capable) — drives VIO + obstacle avoidance + FPV
- 4× surround/down (2MP @ 30fps, SDR) — situational awareness only

Encode is also asymmetric:
- 1× FPV forward in low-latency mode (8 Mbps, 60fps)
- 3× surround in normal mode (2 Mbps, 30fps)

DSP preprocessing (pyramids, optical flow, lens distortion) runs only on
the forward stereo pair. Surround cameras skip DSP and go straight to
perception NPU at lower resolution. This is a deliberate architectural
choice — running pyramids on all 6 cameras would burn ~6× the DSP cycles
for no operational benefit.

Sliders preserve the ability to stress-test:
- `camera_config` (0-4): preset selection (stereo / +down / +surround / 6cam-true360 / 8cam-dense)
- `sensor_megapixels_scale`, `sensor_fps_scale`: multiplicative knobs
- `hdr_exposures`: applies only to forward streams
- `encode_preset` (0-3): asymmetric encode configuration

## Alternatives considered

- **Uniform N×same**: rejected as unrealistic. Inflates ISP and BW
  requirements without operational benefit.
- **Single configurable stream**: rejected. Real systems are inherently
  multi-stream with mixed configs; the workload model has to reflect
  that.

## Consequences

- ISP demand calculation iterates over a list of streams, each with its
  own resolution/fps/HDR. Likewise encode.
- The "BoM ask" the chip team gets is more honest: 1200 Mpix/s ISP line
  rate with 8 concurrent streams (not "ridiculous 8MP-everywhere
  budgets").
- The partition report now shows per-stream contribution to ISP load
  and per-stream encode settings, which makes the asymmetric design
  legible.
