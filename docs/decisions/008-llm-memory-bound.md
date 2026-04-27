# ADR 008: LLM workload modeled as memory-BW-bound

**Status:** Accepted
**Date:** 2026-04

## Context

When the LLM workload was first added, it was tempting to size it by
TOPS (the way a perception model is sized). That's wrong for LLM
inference at edge token rates.

LLM inference, in practice:
- For each output token, every parameter is read from memory once
- Compute per token is small (~2 × params × ops = ~14 GFLOPs for a 7B
  model, trivial)
- Memory bandwidth per token = params × bytes-per-param (e.g. 7 GB
  for 7B at INT8)

At 20 tokens/sec, a 7B INT8 model needs **140 GB/s** sustained memory
bandwidth, which is more than most edge SoCs can supply even
before perception/encode/comms run concurrently.

The compute side (~0.3 TOPS for the same case) is negligible — any NPU
sized for transformer perception has compute headroom for LLM. The
binding constraint is bandwidth.

## Decision

The `llm_demand` calculator computes:
- TOPS required = 2 × params(B) × tokens_per_sec / 1000  (small, ~0.3)
- Memory BW = params × bytes_per_param × tokens_per_sec  (the constraint)
- Memory capacity = params × bytes_per_param  (resident weights)

The KPI report shows LLM TOPS pass and LLM memory-BW often fail —
which is the right story.

## Alternatives considered

- **Skip LLM entirely.** Rejected: on-device reasoning ("is this a
  person or a backpack?", voice command interpretation) is a real
  feature ask for rescue applications. Pretending it doesn't exist
  produces an under-spec'd chip.
- **Size by TOPS like other workloads.** Rejected for the reasons
  above. Produces a chip that has all the compute and none of the
  bandwidth — which is what early edge-LLM products shipped with and
  is precisely why they ran at 3-5 tokens/sec.

## Consequences

- Memory bandwidth becomes the most-watched chip-wide KPI when LLM is
  active. The "do we need 2× LPDDR5x channels or 4×" conversation
  hinges on this.
- The `llm_active`, `llm_model_b_params`, `llm_tokens_per_sec`, and
  `precision` sliders give the executive lever to ask "what if we
  put a 3B / 7B / 13B LLM on this thing." The answers are
  immediately legible.
- Quantization (INT8 vs INT4) becomes a 2× lever on memory pressure.
  INT4 makes a 7B model's bandwidth pressure equivalent to INT8 of
  3.5B, which can flip "fails" to "passes." Worth noting in the
  competitive story.

## Worth knowing

The model assumes single-stream inference (one token at a time, no
batching). For voice command use cases this is right — there's only
one user. For multi-pilot fleet operations or simultaneous
voice+vision queries the math gets more complex; the model would
need a `concurrent_streams` knob and KV-cache contention modeling.
Defer until the use case actually shows up.
