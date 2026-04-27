# Architectural Decision Records

These are short writeups (200-500 words each) capturing the *why* behind key
design choices specific to **nightjar** (the drone software stack +
edge-SoC sizer). Engine-level ADRs that apply to any sizer consuming
ratchet have been moved to the ratchet repository — stubs are preserved
here at their original numbers so historical references remain navigable.

Format follows the lightweight ADR convention: each file describes one
decision, what alternatives were considered, what we chose, and why.

| #   | Decision                                          | Status                            |
|-----|---------------------------------------------------|-----------------------------------|
| 001 | Two-source model: measured + projected            | Moved → ratchet ADR 001           |
| 002 | Per-subsystem ROS 2 nodes for partition fidelity  | Moved → ratchet ADR 002 (renamed) |
| 003 | Asymmetric multi-camera as the realistic default  | Accepted (drone-specific)         |
| 004 | Dedicated ISP block, not GPU/CPU fallback         | Accepted (drone-specific)         |
| 005 | Cadence-class DSPs for classical CV preprocessing | Accepted (drone-specific)         |
| 006 | Cortex-M companion core for flight control        | Accepted (drone-specific)         |
| 007 | Native BF16 on NPU as competitive differentiator  | Moved → ratchet ADR 003           |
| 008 | LLM workload modeled as memory-BW-bound           | Moved → ratchet ADR 004           |
| 009 | NPU efficiency factor of 0.55 default             | Moved → ratchet ADR 005           |
| 010 | Glass-to-glass <100ms for tree-dodging            | Accepted (drone-specific)         |
| 011 | Trajectory-driven test harness pattern            | Pattern → ratchet ADR 006; drone-specific instantiation stays here |

Add new ADRs by copying the format of an existing one. Don't edit accepted
ADRs in place — supersede them with a new one if a decision changes.
