#!/usr/bin/env python3
"""Summarise the per event timing files written by the C++ data test.

The test times each call of the pattern finder on its own and writes

    event,nSpacePoints,nBuckets,nPatterns,totalTime_us

so the cost is available as a distribution rather than as a total. That is what
the Sequencer cannot give: it reports one number per component for the whole
run, which this complements rather than repeats.

Two tables are written. `event_timings.csv` holds every event of every run with
its sample, for plotting the cost against the occupancy. `event_summary.csv`
holds one row per run:

    sample, events, median_us, p90_us, median_us_per_spacepoint, ...

The median is quoted rather than the mean: the first event of a run pays for
cold caches and would drag a mean with it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

#: timing_<sample>_<implementation><suffix>.csv, as the run script names them
NAME = re.compile(r"^timing_(?P<sample>[^_]+)_(?P<implementation>[^_.]+)"
                  r"(?P<suffix>.*)\.csv$")


def read_run(path: Path) -> pd.DataFrame:
    """One run's events, with the sample and implementation from the name."""
    match = NAME.match(path.name)
    if match is None:
        return pd.DataFrame()
    frame = pd.read_csv(path)
    frame["sample"] = match["sample"]
    frame["implementation"] = match["implementation"]
    frame["suffix"] = match["suffix"]
    return frame


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("directory", type=Path, help="Directory of the timing files")
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()

    frames = [read_run(path)
              for path in sorted(args.directory.glob("timing_*.csv"))]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        raise SystemExit(f"No timing files in {args.directory}")
    events = pd.concat(frames, ignore_index=True)

    # the first event of a run carries the cost of filling cold caches
    events["isFirst"] = events.groupby(
        ["sample", "implementation", "suffix"])["event"].transform("min") \
        == events["event"]

    # every column of times is summarised, so a run carrying the phases of a
    # GPU beside the total is handled by the same code
    phases = [c for c in events.columns if c.endswith("Time_us")]

    def describe(group: pd.DataFrame) -> pd.Series:
        out = {"events": len(group)}
        for phase in phases:
            name = phase.removesuffix("Time_us")
            out[f"{name}_median_us"] = group[phase].median()
            out[f"{name}_p90_us"] = group[phase].quantile(0.9)
        out["median_us"] = group["totalTime_us"].median()
        out["p90_us"] = group["totalTime_us"].quantile(0.9)
        out["max_us"] = group["totalTime_us"].max()
        out["median_spacepoints"] = group["nSpacePoints"].median()
        out["us_per_spacepoint"] = (
            (group["totalTime_us"] / group["nSpacePoints"]).median()
            if (group["nSpacePoints"] > 0).all() else float("nan"))
        out["median_patterns"] = group["nPatterns"].median()
        return pd.Series(out)

    warm = events[~events["isFirst"]]
    summary = warm.groupby(["sample", "implementation", "suffix"]).apply(
        describe, include_groups=False).reset_index()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    events.to_csv(args.output_dir / "event_timings.csv", index=False)
    summary.to_csv(args.output_dir / "event_summary.csv", index=False)

    print(summary.to_string(index=False))
    print(f"\n{len(events)} events, {len(summary)} runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
