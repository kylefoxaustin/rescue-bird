"""Golden-file regression tests on representative configurations.

Each test runs the analytical model against a named configuration and
diffs against a checked-in JSON snapshot. Any change to model output —
intentional or not — flips the test red until the golden is regenerated.

Run normally:
    pytest tests/golden -v

Regenerate goldens after intentional model changes:
    pytest tests/golden --update-goldens

The diffing is structural and tolerant of small floating-point noise
(±1% by default). If you need exact matches for some fields, see
GOLDEN_TOLERANCES.

Configurations live in `configurations.py` so they're explicit and
diffable. Snapshots live in `snapshots/` as one JSON per config.
"""

from __future__ import annotations
import copy
import json
import math
from pathlib import Path

import pytest
import yaml

from instrumentation.analysis.whatif.workload_model import DEFAULT_WORKLOAD
from instrumentation.analysis.whatif.sliders import default_values, apply_sliders
from instrumentation.analysis.whatif.kpis import evaluate, chip_summary

from .configurations import CONFIGURATIONS


PROFILES_DIR = (
    Path(__file__).parent.parent.parent
    / "instrumentation" / "analysis" / "profiles"
)
SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"
SNAPSHOTS_DIR.mkdir(exist_ok=True)


# Per-field tolerance for floating-point diffs. None = exact match.
GOLDEN_TOLERANCES = {
    "required": 0.01,        # 1% — covers small computation drift
    "budget": 0.01,
    "margin": 0.01,
    "margin_pct": 0.5,       # absolute % point; numbers near zero swing more
}


def _load_profile(name: str) -> dict:
    return yaml.safe_load((PROFILES_DIR / f"{name}.yaml").read_text())


def _build_state(profile_name: str, overrides: dict) -> tuple[dict, dict]:
    profile = _load_profile(profile_name)
    workload = copy.deepcopy(DEFAULT_WORKLOAD)
    values = default_values()
    values.update(overrides)
    apply_sliders(profile, workload, values)
    return profile, workload


def _kpi_to_dict(r) -> dict:
    """Serialize a KpiResult to a plain dict, dropping things that diff badly."""
    return {
        "name": r.name,
        "scope": r.scope,
        "target": r.target,
        "metric": r.metric,
        "required": round(r.required, 4) if isinstance(r.required, float) else r.required,
        "budget":   round(r.budget,   4) if isinstance(r.budget,   float) else r.budget,
        "margin":   round(r.margin,   4) if isinstance(r.margin,   float) else r.margin,
        "margin_pct": round(r.margin_pct, 2),
        "units": r.units,
        "status": r.status,
    }


def _evaluate_config(profile_name: str, overrides: dict) -> dict:
    profile, workload = _build_state(profile_name, overrides)
    results = evaluate(profile, workload)
    return {
        "profile": profile_name,
        "overrides": overrides,
        "summary": chip_summary(results),
        "kpis": [_kpi_to_dict(r) for r in results],
    }


def _diff_dicts(actual: dict, expected: dict, path: str = "") -> list[str]:
    """Walk both dicts; return a list of differences."""
    diffs: list[str] = []

    if isinstance(actual, list) and isinstance(expected, list):
        if len(actual) != len(expected):
            diffs.append(f"{path}: length differs (actual={len(actual)}, expected={len(expected)})")
            return diffs
        for i, (a, e) in enumerate(zip(actual, expected)):
            diffs.extend(_diff_dicts(a, e, f"{path}[{i}]"))
        return diffs

    if isinstance(actual, dict) and isinstance(expected, dict):
        for k in set(actual) | set(expected):
            if k not in actual:
                diffs.append(f"{path}.{k}: missing in actual")
            elif k not in expected:
                diffs.append(f"{path}.{k}: extra in actual ({actual[k]!r})")
            else:
                diffs.extend(_diff_dicts(actual[k], expected[k], f"{path}.{k}"))
        return diffs

    if isinstance(actual, float) and isinstance(expected, float):
        # Pull tolerance from the field name (last segment of path)
        last = path.rsplit(".", 1)[-1]
        tol = GOLDEN_TOLERANCES.get(last)
        if tol is None:
            if actual != expected:
                diffs.append(f"{path}: {actual!r} != {expected!r}")
        else:
            if expected == 0:
                if abs(actual) > tol:
                    diffs.append(f"{path}: {actual!r} != {expected!r} (abs diff > {tol})")
            elif not math.isclose(actual, expected, rel_tol=tol, abs_tol=tol):
                diffs.append(f"{path}: {actual!r} != {expected!r} (>{tol*100:.1f}%)")
        return diffs

    if actual != expected:
        diffs.append(f"{path}: {actual!r} != {expected!r}")
    return diffs


@pytest.mark.parametrize("name,config", list(CONFIGURATIONS.items()))
def test_golden(name: str, config: dict, request):
    """For each named configuration: assert KPI output matches the snapshot."""
    actual = _evaluate_config(config["profile"], config["overrides"])
    snapshot_path = SNAPSHOTS_DIR / f"{name}.json"

    if request.config.getoption("--update-goldens") or not snapshot_path.exists():
        snapshot_path.write_text(json.dumps(actual, indent=2, sort_keys=True))
        if not snapshot_path.exists():
            pytest.fail(f"Created new snapshot at {snapshot_path}; rerun without --update-goldens")
        return

    expected = json.loads(snapshot_path.read_text())
    diffs = _diff_dicts(actual, expected)
    if diffs:
        msg = f"\nGolden mismatch for '{name}'. {len(diffs)} differences:\n"
        msg += "\n".join(f"  {d}" for d in diffs[:20])
        if len(diffs) > 20:
            msg += f"\n  ... and {len(diffs) - 20} more"
        msg += f"\n\nIf this change is intentional, regenerate with:\n  pytest tests/golden --update-goldens"
        pytest.fail(msg)
