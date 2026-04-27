# ADR 004: Dedicated ISP block, not GPU/CPU fallback

**Status:** Accepted
**Date:** 2026-04

## Context

The image signal processor (Bayer demosaic, BLC, AWB, tone map, lens
distortion correction, NR, scaler) can in principle run on:

1. **Dedicated ISP block** (the standard answer in application processors)
2. **GPU/NPU as compute kernels** (some research / Jetson configs do this)
3. **CPU SIMD** (RPi-class fallback)

For a rescue drone running 6 concurrent camera streams at 60fps, options
2 and 3 are wrong — but they're surprisingly common in initial
architectures because "we already have a GPU, why pay for ISP silicon?"

## Decision

The default profile and workload model assume a dedicated ISP block. The
SoC profile carries `isp.present: true`, `isp.max_line_rate_mpps`,
`isp.csi2_lanes_total`, and so on. The partition report flags ISP fit
as a primary KPI.

A user can set `isp.present: false` in a profile to model the GPU-fallback
case. The model reroutes ISP work onto the GPU and the report shows
the cost — typically dramatic.

## Alternatives considered

- **Assume GPU fallback by default.** Rejected: misleads the chip-spec
  conversation. Real edge SoCs in this class always have an ISP; the
  question is how big.
- **Hide the ISP entirely (treat camera input as already-RGB).** Rejected:
  it's a significant fraction of total memory bandwidth (the v3 update
  showed default BW jumping from 0.84 GB/s to 8.99 GB/s when ISP was
  modeled). Ignoring it understates chip pressure.

## Why the ISP can't reasonably be GPU/NPU

- **Line-rate determinism**: the ISP must consume CSI-2 at exact sensor
  line rate, with bounded jitter. GPU scheduling jitter (hundreds of
  microseconds, sometimes more) drops lines.
- **Fixed-point datapaths**: ISP stages are 12-16 bit fixed point. Doing
  this on a float GPU wastes 2-4× the energy.
- **Format conversion**: real ISPs have hardware demosaic, format
  converters (Bayer → YUV, RGB → CHW tensor), and color space conversion
  matrices. Software equivalents are 5-10× the energy.
- **DMA paths**: dedicated ISPs can write directly to other engines'
  preferred buffer formats (NV12 to VPU, CHW tensor to NPU) without
  intermediate copies. Software ISP forces extra DRAM round-trips.

## Consequences

- The `drone_isp` ROS 2 node simulates the pipeline, with per-stage probes
  matching real ISP datasheet stages (BLC, LSC, DPC, demosaic, WB, CCM,
  HDR merge, tonemap, LDC, NR2D, NR3D, sharpen, scaler, formatter).
- The SoC profile's `isp` block carries enough detail (line rate, lane
  count, concurrent streams, HDR support, LDC support) to drive multiple
  KPIs.
- The competitive story for any chip lacking a real ISP becomes
  quantified, not hand-waved.

## Worth knowing

The most-likely-stale constants are the per-stage `ns_per_pixel` values
in `isp_node.py`'s `ISP_STAGES` table. They're calibrated to "modern
application-processor ISPs" generically. NXP, Mobileye, Ambarella, and
Apple all publish enough data to refine this for specific designs.
