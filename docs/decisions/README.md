# Architectural Decision Records

These are short writeups (200-500 words each) capturing the *why* behind key
design choices. They're meant for someone joining the project later who needs
to understand "why did we decide X" without having to reverse-engineer it
from the code.

Format follows the lightweight ADR convention: each file describes one
decision, what alternatives were considered, what we chose, and why.

| #   | Decision                                          | Status   |
|-----|---------------------------------------------------|----------|
| 001 | Two-source model: measured + projected            | Accepted |
| 002 | Per-subsystem ROS 2 nodes for partition fidelity  | Accepted |
| 003 | Asymmetric multi-camera as the realistic default  | Accepted |
| 004 | Dedicated ISP block, not GPU/CPU fallback         | Accepted |
| 005 | Cadence-class DSPs for classical CV preprocessing | Accepted |
| 006 | Cortex-M companion core for flight control        | Accepted |
| 007 | Native BF16 on NPU as competitive differentiator  | Accepted |
| 008 | LLM workload modeled as memory-BW-bound           | Accepted |
| 009 | NPU efficiency factor of 0.55 default             | Accepted |
| 010 | Glass-to-glass <100ms for tree-dodging            | Accepted |

Add new ADRs by copying the format of an existing one. Don't edit accepted
ADRs in place — supersede them with a new one if a decision changes.
