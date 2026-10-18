#!/usr/bin/env python3
"""Put two performance summaries side by side.

Reads the `summary.csv` that aggregate_performance.py writes for each run,
reduces each to its median over the repetitions and writes one row per measure:

    measure | <reference> | <compared> | speedup

The speedup is the reference divided by the compared value for a time and the
compared divided by the reference for a throughput, so a number above one always
means the compared run is faster. The stages of the GPU path are listed when
both runs have them, and the resources each run recorded follow, without a
speedup.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

#: Measures of every run, in the order they are listed; a throughput is better
#: when larger, everything else is a time
MEASURES = [
    "mean time per event (ms)",
    "median time per event (ms)",
    "p90 time per event (ms)",
    "slowest event (ms)",
    "median time per space point (ms)",
    "throughput (events/s)",
]
#: Resources, listed as they are; a run without a GPU has none of the GPU ones
RESOURCES = [
    "process wall time (s)",
    "CPU cores in use by the process (mean)",
    "peak memory of the process (MiB)",
    "GPU utilisation while busy (mean %)",
    "GPU memory used (peak MiB)",
    "GPU power while busy (mean W)",
    "GPU SM clock while busy (median MHz)",
]
#: The names of the same columns in summaries written before they were renamed
OLD_NAMES = {
    "mean time per event (ms)": ["mean time (ms)", "mean time (us)"],
    "median time per event (ms)": ["median time (ms)", "median time (us)"],
    "p90 time per event (ms)": ["p90 time (ms)", "p90 time (us)"],
    "slowest event (ms)": ["max time (ms)", "max time (us)"],
    "median time per space point (ms)": ["median time per space point (us)"],
}


def per_run(path: Path) -> pd.Series:
    """The median over the repetitions the summary holds. Older summaries
    name the columns differently, and the oldest have microseconds"""
    frame = pd.read_csv(path)
    for column, old_names in OLD_NAMES.items():
        for old in old_names:
            if column not in frame.columns and old in frame.columns:
                scale = 1e-3 if old.endswith("(us)") else 1.0
                frame[column] = frame[old] * scale
    return frame.select_dtypes("number").median()


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("reference", type=Path, help="summary.csv of the reference")
    p.add_argument("compared", type=Path, help="summary.csv to compare")
    p.add_argument("--reference-label", default="reference")
    p.add_argument("--compare-label", default="compared")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    reference = per_run(args.reference)
    compared = per_run(args.compared)
    stages = [c for c in reference.index
              if c.endswith("(median ms)") and c in compared.index]
    measures = [m for m in MEASURES
                if m in reference.index and m in compared.index] + stages
    resources = [c for c in RESOURCES
                 if c in reference.index or c in compared.index]

    rows = []
    for measure in measures:
        ref, cmp = reference[measure], compared[measure]
        speedup = cmp / ref if "events/s" in measure else ref / cmp
        rows.append({"measure": measure,
                     args.reference_label: float(f"{ref:.4g}"),
                     args.compare_label: float(f"{cmp:.4g}"),
                     f"speedup (above 1: {args.compare_label} is faster)":
                         float(f"{speedup:.3g}")})
    for measure in resources:
        ref = reference.get(measure, float("nan"))
        cmp = compared.get(measure, float("nan"))
        rows.append({"measure": measure,
                     args.reference_label: float(f"{ref:.4g}"),
                     args.compare_label: float(f"{cmp:.4g}")})
    out = pd.DataFrame(rows)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    print(out.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
