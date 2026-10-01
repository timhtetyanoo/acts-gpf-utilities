#!/usr/bin/env python3
"""Put two timing summaries side by side and divide them.

Reads the `event_summary.csv` that aggregate_event_timing.py writes for each
run and joins them on the sample, giving one row per sample:

    sample, <reference>_ms, <compare>_ms, speedup, ...

The speedup is the reference divided by the compared value, so a number above
one means the compared run is faster.

The two summaries are taken as they are. Where they came from, how they were
produced and what the runs were called inside them makes no difference; the
labels are given on the command line.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

#: Columns compared, as source -> (name in the output, scale, unit)
COLUMNS = {
    "median_us": ("median", 1e-3, "ms"),
    "p90_us": ("p90", 1e-3, "ms"),
    "us_per_spacepoint": ("perSpacePoint", 1.0, "us"),
}


def per_sample(path: Path) -> pd.DataFrame:
    """One row per sample, averaging over whatever runs the summary holds."""
    frame = pd.read_csv(path)
    missing = [c for c in COLUMNS if c not in frame.columns]
    if missing:
        raise SystemExit(f"{path} has no column {missing[0]}")
    return frame.groupby("sample")[list(COLUMNS)].median().reset_index()


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("reference", type=Path, help="event_summary.csv of the reference")
    p.add_argument("compared", type=Path, help="event_summary.csv to compare")
    p.add_argument("--reference-label", default="reference")
    p.add_argument("--compare-label", default="compared")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    reference = per_sample(args.reference)
    compared = per_sample(args.compared)
    joined = reference.merge(compared, on="sample", suffixes=("_ref", "_cmp"))
    if joined.empty:
        raise SystemExit("The two summaries have no sample in common")

    out = pd.DataFrame({"sample": joined["sample"]})
    for column, (name, scale, unit) in COLUMNS.items():
        reference_values = joined[f"{column}_ref"]
        compared_values = joined[f"{column}_cmp"]
        out[f"{name}_{args.reference_label}_{unit}"] = reference_values * scale
        out[f"{name}_{args.compare_label}_{unit}"] = compared_values * scale
        out[f"{name}_speedup"] = reference_values / compared_values

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    print(out.to_string(index=False))
    print(f"\nSpeedup is {args.reference_label} over {args.compare_label}; "
          f"above one means {args.compare_label} is faster")
    return 0


if __name__ == "__main__":
    sys.exit(main())
