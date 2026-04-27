"""whatif_cli.py — drone-specific CLI for the what-if sizing tool.

The what-if engine (point/sweep/pareto runner) lives in ``ratchet.whatif``.
This module wires the drone slider catalog, drone evaluate function, drone
DEFAULT_WORKLOAD, and the drone profile loader into a ``WhatifRunner``,
then prints the results in the same Markdown format as before.

Examples:
    # Default A720 + 200 TOPS, no LLM
    python -m instrumentation.sizing.whatif_cli point

    # Try with the LLM active and 7B params
    python -m instrumentation.sizing.whatif_cli point \\
        --set llm_active=1 --set llm_model_b_params=7

    # How does perception fit as we drop NPU TOPS?
    python -m instrumentation.sizing.whatif_cli sweep \\
        --slider npu_tops_bf16 --steps 10

    # Pareto: NPU TOPS × LLM size
    python -m instrumentation.sizing.whatif_cli pareto \\
        --x npu_tops_bf16 --y llm_model_b_params --set llm_active=1

    # Show all available sliders
    python -m instrumentation.sizing.whatif_cli list
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import yaml

from ratchet.whatif import WhatifRunner

from .sliders import SLIDERS
from .workload import DEFAULT_WORKLOAD
from .kpis import evaluate
from ratchet.engine.slider import slider_categories as _slider_categories


PROFILES_DIR = (
    Path(__file__).parent.parent / "analysis" / "profiles"
)


def _load_profile(name: str) -> dict:
    """Load a SoC profile by name from instrumentation/analysis/profiles/."""
    profile_path = PROFILES_DIR / f"{name}.yaml"
    if not profile_path.exists():
        print(f"Profile not found: {profile_path}", file=sys.stderr)
        sys.exit(1)
    return yaml.safe_load(profile_path.read_text())


def _build_runner() -> WhatifRunner:
    return WhatifRunner(
        sliders=SLIDERS,
        evaluate_fn=evaluate,
        default_workload_factory=lambda: DEFAULT_WORKLOAD,
        profile_loader=_load_profile,
    )


def _parse_set_args(set_args: list[str]) -> dict[str, float]:
    """Parse --set name=value pairs."""
    out: dict[str, float] = {}
    for s in set_args:
        if "=" not in s:
            print(f"Bad --set: {s} (expected name=value)", file=sys.stderr)
            sys.exit(1)
        k, v = s.split("=", 1)
        if k not in SLIDERS:
            print(f"Unknown slider: {k}", file=sys.stderr)
            sys.exit(1)
        out[k] = float(v)
    return out


# ──────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────

def cmd_list(args) -> None:
    cats = _slider_categories(SLIDERS)
    for cat in ["capability", "workload", "operating", "headroom"]:
        sliders = cats.get(cat, [])
        if not sliders:
            continue
        print(f"\n## {cat.upper()} sliders\n")
        for s in sliders:
            print(f"  {s.name:35s}  default={s.default:<8g} range=[{s.min_val}..{s.max_val}]  ({s.units})")
            print(f"    {s.description}")


def cmd_point(args) -> None:
    overrides = _parse_set_args(args.set or [])
    runner = _build_runner()
    result = runner.point(args.profile, overrides)
    summary = result.summary

    print(f"\n# What-if Point Evaluation")
    print(f"\nProfile: **{args.profile}**")
    if overrides:
        print(f"\nOverrides:")
        for k, v in overrides.items():
            print(f"  - {k} = {v}")

    print(f"\n## Chip viability\n")
    icon = "✅" if summary["viable"] else "❌"
    print(f"{icon} **{summary['pass']}/{summary['total']} KPIs PASS**  "
          f"({summary['warn']} warn, {summary['fail']} fail)")

    if summary["failures"]:
        print(f"\nFailures:")
        for f in summary["failures"]:
            print(f"  - **{f['name']}**: overage {f['overage']:.2f} {f['units']}")

    print(f"\n## All KPIs\n")
    print(f"| status | scope | target | metric | required | budget | margin | units |")
    print(f"|--------|-------|--------|--------|---------:|-------:|-------:|-------|")
    for r in result.kpis:
        print(f"| {r.emoji} {r.status} | {r.scope} | {r.target} | {r.metric} | "
              f"{r.required:.2f} | {r.budget:.2f} | {r.margin_pct:+.0f}% | {r.units} |")

    if args.json:
        out = {
            "profile": args.profile,
            "overrides": overrides,
            "summary": summary,
            "kpis": [r.__dict__ for r in result.kpis],
        }
        Path(args.json).write_text(json.dumps(out, indent=2))
        print(f"\nJSON written to {args.json}")


def cmd_sweep(args) -> None:
    overrides = _parse_set_args(args.set or [])
    if args.slider not in SLIDERS:
        print(f"Unknown slider: {args.slider}", file=sys.stderr); sys.exit(1)

    runner = _build_runner()
    result = runner.sweep(args.profile, args.slider, args.steps, overrides)

    print(f"\n# Sweep: {args.slider}")
    s = SLIDERS[args.slider]
    print(f"\nProfile: **{args.profile}**  ·  range [{s.min_val}, {s.max_val}]  ·  {len(result.rows)} steps\n")

    print(f"| {args.slider} | viable | PASS | WARN | FAIL | top failure |")
    print(f"|----:|:------:|:----:|:----:|:----:|:-----------|")
    for row in result.rows:
        summary = row.summary
        top_fail = summary["failures"][0]["name"] if summary["failures"] else "—"
        viable_icon = "✅" if summary["viable"] else "❌"
        print(f"| {row.value:.2f} | {viable_icon} | {summary['pass']} | {summary['warn']} | "
              f"{summary['fail']} | {top_fail} |")


def cmd_pareto(args) -> None:
    overrides = _parse_set_args(args.set or [])
    runner = _build_runner()
    result = runner.pareto(
        args.profile, args.x, args.y, args.steps_x, args.steps_y, overrides,
    )

    print(f"\n# Pareto: {args.x} × {args.y}")
    print(f"\nProfile: **{args.profile}**\n")
    print(f"Cell shows # of failing KPIs (0 = viable). y-axis is {args.y}, x-axis is {args.x}.\n")

    header = "| " + args.y + r" \ " + args.x + " | " + " | ".join(f"{x:.1f}" for x in result.xs) + " |"
    sep = "|" + "---|" * (len(result.xs) + 1)
    print(header); print(sep)
    for j, y in enumerate(result.ys):
        cells = [f"**{y:.1f}**"]
        for cell_summary in result.cells[j]:
            n_fail = cell_summary["fail"]
            icon = "✅" if n_fail == 0 else f"❌{n_fail}"
            cells.append(icon)
        print("| " + " | ".join(cells) + " |")


# ──────────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="What-if sizing tool for the rescue-bird/nightjar drone SoC")
    ap.add_argument("--profile", default="rescue_bird_a720",
                    help="SoC profile name (under instrumentation/analysis/profiles/)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list all sliders")

    p = sub.add_parser("point", help="evaluate KPIs at one configuration")
    p.add_argument("--set", action="append", help="slider=value override (repeatable)")
    p.add_argument("--json", help="optional JSON output path")

    p = sub.add_parser("sweep", help="sweep one slider")
    p.add_argument("--slider", required=True)
    p.add_argument("--steps", type=int, default=10)
    p.add_argument("--set", action="append", help="other slider overrides")

    p = sub.add_parser("pareto", help="2D sweep — Pareto grid")
    p.add_argument("--x", required=True)
    p.add_argument("--y", required=True)
    p.add_argument("--steps-x", type=int, default=6)
    p.add_argument("--steps-y", type=int, default=6)
    p.add_argument("--set", action="append", help="other slider overrides")

    args = ap.parse_args()
    {"list": cmd_list, "point": cmd_point, "sweep": cmd_sweep, "pareto": cmd_pareto}[args.cmd](args)


if __name__ == "__main__":
    main()
