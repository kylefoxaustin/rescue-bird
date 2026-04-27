"""soc_partition_report.py — turn a run directory into an SoC partitioning report.

Inputs : a run directory containing per-subsystem Parquet files emitted by probes.
Outputs: a Markdown report + CSV summary that answers the silicon questions.

Sections of the report:

    1. Per-subsystem compute envelope
       - peak / p99 / mean latency per operation
       - peak / p99 / mean concurrent SM% (for blocks running on GPU today)
       - effective TOPS (BF16-equivalent) from MAC counts and latencies
       - memory footprint high-water mark

    2. Inter-subsystem bandwidth
       - bytes/sec on each src→dst edge
       - peak burst rate (1ms / 10ms / 100ms windows)
       - implications for the SoC NoC (chip interconnect)

    3. Phase breakdown (idle / transit / search / acquire / track)
       - duty cycle on each subsystem per phase
       - the "during PHASE_ACQUIRE, perception ran at X%" tables

    4. Precision sensitivity
       - if multiple precisions were measured, report per-precision
         {latency, accuracy proxy, energy proxy} so BF16-vs-FP16 is data-driven

    5. Candidate SoC fit
       - pluggable target profile (e.g. i.MX 95 class) loaded from yaml
       - flags any subsystem that would exceed its budget

Usage:
    python soc_partition_report.py runs/2026-04-25T14-12-09/
    python soc_partition_report.py runs/<run>/ --target imx95
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


# ──────────────────────────────────────────────────────────────────────
# Loading
# ──────────────────────────────────────────────────────────────────────

def load_run(run_dir: Path) -> pd.DataFrame:
    """Concatenate every *.parquet in run_dir into a single DataFrame."""
    files = sorted(run_dir.glob("*.parquet"))
    if not files:
        print(f"No parquet files in {run_dir}", file=sys.stderr)
        sys.exit(1)
    frames = [pq.read_table(f).to_pandas() for f in files]
    df = pd.concat(frames, ignore_index=True)
    return df


# ──────────────────────────────────────────────────────────────────────
# Section 1: Per-subsystem compute envelope
# ──────────────────────────────────────────────────────────────────────

def compute_envelope(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (subsystem, operation): latency stats + TOPS estimate."""
    g = df.dropna(subset=["latency_ns"]).groupby(["subsystem", "operation"])
    rows = []
    for (sub, op), group in g:
        lat = group["latency_ns"].astype(np.int64)
        macs = group["macs"].dropna()
        # TOPS (peak): 2 * MACs / latency, then convert to TOPS (1e12)
        tops_peak = None
        tops_p99 = None
        if not macs.empty and not lat.empty:
            n = min(len(macs), len(lat))
            ops_per_sec = (2 * macs.iloc[:n].values) / (lat.iloc[:n].values / 1e9)
            tops_peak = float(np.max(ops_per_sec) / 1e12)
            tops_p99 = float(np.percentile(ops_per_sec, 99) / 1e12)
        rows.append({
            "subsystem": sub,
            "operation": op,
            "n_obs": len(group),
            "latency_ms_mean": float(lat.mean() / 1e6),
            "latency_ms_p50":  float(np.percentile(lat, 50) / 1e6),
            "latency_ms_p99":  float(np.percentile(lat, 99) / 1e6),
            "latency_ms_max":  float(lat.max() / 1e6),
            "tops_peak":       tops_peak,
            "tops_p99":        tops_p99,
            "precision":       group["precision"].dropna().mode().iloc[0] if not group["precision"].dropna().empty else None,
        })
    return pd.DataFrame(rows).sort_values(["subsystem", "operation"]).reset_index(drop=True)


# ──────────────────────────────────────────────────────────────────────
# Section 2: Inter-subsystem bandwidth
# ──────────────────────────────────────────────────────────────────────

def edge_bandwidth(df: pd.DataFrame, window_ms: int = 100) -> pd.DataFrame:
    """Bytes/sec on each src→dst edge, plus peak burst rates."""
    sub = df.dropna(subset=["src_subsystem", "dst_subsystem", "output_bytes"]).copy()
    if sub.empty:
        return pd.DataFrame()
    # Bin into windows for burst calculation
    sub["t_ms"] = sub["t_wall_ns"] // 1_000_000
    sub["bin"]  = sub["t_ms"] // window_ms
    rows = []
    for (src, dst), g in sub.groupby(["src_subsystem", "dst_subsystem"]):
        per_bin = g.groupby("bin")["output_bytes"].sum()
        # bytes/window → bytes/sec
        bps = per_bin * (1000.0 / window_ms)
        rows.append({
            "src": src,
            "dst": dst,
            "n_obs": len(g),
            "mbps_mean": float(bps.mean() * 8 / 1e6),
            "mbps_peak": float(bps.max() * 8 / 1e6),
            "total_mb":  float(g["output_bytes"].sum() / 1e6),
        })
    return pd.DataFrame(rows).sort_values("mbps_peak", ascending=False).reset_index(drop=True)


# ──────────────────────────────────────────────────────────────────────
# Section 3: Phase breakdown
# ──────────────────────────────────────────────────────────────────────

def phase_duty_cycle(df: pd.DataFrame) -> pd.DataFrame:
    """% of time each subsystem was active during each mission phase."""
    if "phase" not in df.columns or df["phase"].isna().all():
        return pd.DataFrame()
    sub = df.dropna(subset=["phase", "subsystem"])
    return (
        sub.groupby(["phase", "subsystem"])
           .agg(
               n_obs=("record_id", "count"),
               sm_active_pct_mean=("sm_active_pct", "mean"),
               sm_active_pct_p99=("sm_active_pct", lambda s: float(np.percentile(s.dropna(), 99)) if s.dropna().size else None),
               nvenc_util_pct_mean=("nvenc_util_pct", "mean"),
               gpu_mem_used_mb_max=("gpu_mem_used_mb", "max"),
           )
           .reset_index()
    )


# ──────────────────────────────────────────────────────────────────────
# Section 4: Precision sensitivity
# ──────────────────────────────────────────────────────────────────────

def precision_compare(df: pd.DataFrame) -> pd.DataFrame:
    """Compare latency across precisions for the same subsystem/operation."""
    sub = df.dropna(subset=["precision", "latency_ns"])
    if sub["precision"].nunique() < 2:
        return pd.DataFrame()
    return (
        sub.groupby(["subsystem", "operation", "precision"])["latency_ns"]
           .agg(["count", "mean", lambda s: np.percentile(s, 99)])
           .rename(columns={"<lambda_0>": "p99"})
           .reset_index()
    )


# ──────────────────────────────────────────────────────────────────────
# Section 5: Candidate SoC fit (stub — load profile from yaml)
# ──────────────────────────────────────────────────────────────────────

def soc_fit(envelope: pd.DataFrame, target_profile: Optional[dict]) -> List[str]:
    """Return human-readable findings: which subsystems exceed which budgets.

    Profile schema (yaml):
        npu_tops_bf16: 4.5
        cpu_cores: 6
        memory_bw_gbps: 25.6
        vpu_h265_max_mpix_per_sec: 80
    """
    if target_profile is None:
        return []
    findings: List[str] = []
    npu_budget = target_profile.get("npu_tops_bf16")
    if npu_budget is not None:
        nn = envelope[envelope["subsystem"].isin(["perception", "vio"])]
        for _, row in nn.iterrows():
            if row["tops_peak"] is not None and row["tops_peak"] > npu_budget:
                findings.append(
                    f"NPU OVERAGE: {row['subsystem']}/{row['operation']} "
                    f"peak {row['tops_peak']:.2f} TOPS exceeds budget {npu_budget} TOPS"
                )
    return findings


# ──────────────────────────────────────────────────────────────────────
# Report assembly
# ──────────────────────────────────────────────────────────────────────

def write_report(run_dir: Path, out: Path, target_profile: Optional[dict] = None) -> None:
    df = load_run(run_dir)
    env = compute_envelope(df)
    bw  = edge_bandwidth(df)
    duty = phase_duty_cycle(df)
    prec = precision_compare(df)
    fit = soc_fit(env, target_profile)

    lines: List[str] = []
    add = lines.append
    add(f"# SoC Partitioning Report")
    add(f"\nRun: `{run_dir}`  ·  Records: **{len(df):,}**\n")

    add("## 1. Per-subsystem compute envelope\n")
    add(env.to_markdown(index=False) if not env.empty else "_no compute observations_")

    add("\n## 2. Inter-subsystem bandwidth (src → dst)\n")
    add(bw.to_markdown(index=False) if not bw.empty else "_no bandwidth observations_")

    add("\n## 3. Phase duty cycle\n")
    add(duty.to_markdown(index=False) if not duty.empty else "_no phase data_")

    add("\n## 4. Precision sensitivity\n")
    add(prec.to_markdown(index=False) if not prec.empty else "_only one precision measured_")

    add("\n## 5. Target SoC fit\n")
    if not fit:
        add("_no target profile provided, or all subsystems within budget_")
    else:
        for f in fit:
            add(f"- ⚠️ {f}")

    out.write_text("\n".join(lines))
    print(f"Report written: {out}")

    # Also dump the envelope as CSV for quick spreadsheet work
    csv_out = out.with_suffix(".csv")
    env.to_csv(csv_out, index=False)
    print(f"Envelope CSV: {csv_out}")


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", type=Path, help="Run directory (e.g. runs/2026-04-25T14-12-09)")
    p.add_argument("--target", type=str, default=None,
                   help="Target SoC profile name from instrumentation/analysis/profiles/")
    p.add_argument("--out", type=Path, default=None,
                   help="Output report path. Defaults to <run_dir>/report.md")
    args = p.parse_args()

    profile = None
    if args.target:
        import yaml
        prof_path = Path(__file__).parent / "profiles" / f"{args.target}.yaml"
        profile = yaml.safe_load(prof_path.read_text())

    out = args.out or (args.run_dir / "report.md")
    write_report(args.run_dir, out, profile)


if __name__ == "__main__":
    main()
