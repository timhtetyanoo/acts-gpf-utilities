#!/usr/bin/env python3
"""Put two timing summaries side by side and divide them.

Reads the `summary.csv` that aggregate_event_timing.py writes for each run and
reduces each to its median over the repetitions, giving one row:

    mean time, <reference> (ms) | mean time, <compare> (ms) | mean time speedup | ...

The speedup is the reference divided by the compared value, so a number above
one means the compared run is faster.

The two summaries are taken as they are; the labels are given on the command
line.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

#: Columns compared, as source column -> (name in the output, scale, unit)
COLUMNS = {
    "mean time (us)": ("mean time", 1e-3, "ms"),
    "median time (us)": ("median time", 1e-3, "ms"),
    "p90 time (us)": ("p90 time", 1e-3, "ms"),
    "median time per space point (us)": ("time per space point", 1.0, "us"),
}


def per_run(path: Path) -> pd.Series:
    """The median over the repetitions the summary holds."""
    frame = pd.read_csv(path)
    missing = [c for c in COLUMNS if c not in frame.columns]
    if missing:
        raise SystemExit(f"{path} has no column {missing[0]}")
    return frame[list(COLUMNS)].median()


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

    row = {}
    for column, (name, scale, unit) in COLUMNS.items():
        row[f"{name}, {args.reference_label} ({unit})"] = reference[column] * scale
        row[f"{name}, {args.compare_label} ({unit})"] = compared[column] * scale
        row[f"{name} speedup"] = reference[column] / compared[column]
    out = pd.DataFrame([row])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    print(out.to_string(index=False))
    print(f"\nSpeedup is {args.reference_label} over {args.compare_label}; "
          f"above one means {args.compare_label} is faster")
    return 0


if __name__ == "__main__":
    sys.exit(main())
