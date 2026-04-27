# tests

Two layers of automated tests, plus pointers to the manual layers
documented in `docs/testing.md`.

## tests/unit

Pure-math tests on the analytical workload model and KPI evaluator.
Cheap, fast, no I/O. Run with:

```bash
pytest tests/unit -v
```

Add new cases when:
- A new slider is added (test that its `apply` function actually mutates
  the right path)
- A new demand calculator is added (pin a known input → output)
- A KPI's pass/fail boundary moves (test the new boundary)

## tests/golden

Snapshot tests on full-system KPI evaluation. Locks down behavior across
representative configurations so any unintended change to the model is
caught immediately.

Run with:

```bash
pytest tests/golden -v
```

When the change is intentional (e.g. you refined `npu_efficiency_factor`
and the numbers should shift), regenerate snapshots:

```bash
pytest tests/golden --update-goldens
```

Configurations are listed in `tests/golden/configurations.py`. Add a new
configuration, run `--update-goldens`, commit both the config change and
the new snapshot file.

## Layers not in this directory

Higher-cost layers (integration on the SITL stack, calibration runs,
vendor tooling cross-checks, real-hardware validation) are documented
in `docs/testing.md`. They become valuable once real models and silicon
are in the picture.
