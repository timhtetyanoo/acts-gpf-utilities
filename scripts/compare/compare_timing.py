#!/usr/bin/env python3
"""Put two timing summaries side by side and divide them.

Reads the `summary.csv` that aggregate_event_timing.py writes for each run and
reduces each to its median over the repetitions, giving one row:

    mean time per event, <reference> (ms) | ..., <compare> (ms) | ... speedup | ...

The speedup is the reference divided by the compared value for a time and the
compared divided by the reference for a throughput, so a number above one always
means the compared run is faster.

The two summaries are taken as they are; the labels are given on the command
line.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

#: Columns compared, as source column -> (name in the output, unit, higher is
#: better). A time is better when it is smaller, a throughput when it is larger
COLUMNS = {
    "mean time per event (ms)": ("mean time per event", "ms", False),
    "median time per event (ms)": ("median time per event", "ms", False),
    "p90 time per event (ms)": ("p90 time per event", "ms", False),
    "median time per space point (ms)": ("time per space point", "ms", False),
    "throughput (events/s)": ("throughput", "events/s", True),
}
#: The names of the same columns in summaries written before they were renamed
OLD_NAMES = {
    "mean time per event (ms)": ["mean time (ms)", "mean time (us)"],
    "median time per event (ms)": ["median time (ms)", "median time (us)"],
    "p90 time per event (ms)": ["p90 time (ms)", "p90 time (us)"],
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
    for column, (name, unit, higher_is_better) in COLUMNS.items():
        row[f"{name}, {args.reference_label} ({unit})"] = reference[column]
        row[f"{name}, {args.compare_label} ({unit})"] = compared[column]
        # above one always means the compared run is better
        row[f"{name} speedup"] = (compared[column] / reference[column]
                                  if higher_is_better
                                  else reference[column] / compared[column])
    out = pd.DataFrame([row])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    print(out.to_string(index=False))
    print(f"\nSpeedup is {args.reference_label} over {args.compare_label}; "
          f"above one means {args.compare_label} is faster")
    return 0


if __name__ == "__main__":
    sys.exit(main())
