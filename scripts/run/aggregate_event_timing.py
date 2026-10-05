#!/usr/bin/env python3
"""Summarise the per event timing files written by the C++ data test.

The test times each call of the pattern finder on its own and writes

    event,nSpacePoints,nBuckets,nPatterns,totalTime_us

so the cost is available as a distribution rather than as a total. That is what
the Sequencer cannot give: it reports one number per component for the whole
run, which this complements rather than repeats.

A run is repeated several times, one file `timing_rNN.csv` per repetition. Two
tables are written. `events.csv` holds every event of every repetition with the
name of the run, for plotting the cost against the occupancy. `summary.csv`
holds one row per repetition:

    run, repetition, events, mean time (us), throughput (events/s),
    median time (us), p90 time (us), max time (us),
    median time per space point (us), empty events, ...

Both the mean and the median are written. They answer different questions and
differ a lot where a few events are far slower than the rest: the mean is the
total time over the events, which is what Athena's PerfMon reports as the average
CPU time per execution, and the median is the typical event. The first event of
each repetition is left out of both, since it pays for cold caches.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

#: timing_r01.csv, as the run script names the repetitions
NAME = re.compile(r"^timing_(?P<repetition>r\d+)\.csv$")


def read_run(path: Path, name: str) -> pd.DataFrame:
    """One repetition's events, tagged with the run name and the repetition."""
    match = NAME.match(path.name)
    if match is None:
        return pd.DataFrame()
    frame = pd.read_csv(path)
    frame["run"] = name
    frame["repetition"] = match["repetition"]
    return frame


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("directory", type=Path, help="Directory of the timing files")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--name", required=True, help="Name of the run")
    args = p.parse_args()

    frames = [read_run(path, args.name)
              for path in sorted(args.directory.glob("timing_r*.csv"))]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        raise SystemExit(f"No timing files in {args.directory}")
    events = pd.concat(frames, ignore_index=True)

    # the first event of a run carries the cost of filling cold caches
    events["isFirst"] = events.groupby(
        ["run", "repetition"])["event"].transform("min") \
        == events["event"]

    # every column of times is summarised, so a run carrying the phases of a
    # GPU beside the total is handled by the same code; the total is the plain
    # "median time" below and is not repeated as a phase
    phases = [c for c in events.columns
              if c.endswith("Time_us") and c != "totalTime_us"]

    def describe(group: pd.DataFrame) -> pd.Series:
        out = {"events": len(group)}
        for phase in phases:
            name = phase.removesuffix("Time_us")
            out[f"{name} median time (us)"] = group[phase].median()
            out[f"{name} p90 time (us)"] = group[phase].quantile(0.9)
        out["mean time (us)"] = group["totalTime_us"].mean()
        # events handled per second of finder time, one event after the other: the
        # inverse of the mean time, so the slowest events weigh as they do in the mean
        out["throughput (events/s)"] = len(group) / (group["totalTime_us"].sum() / 1e6)
        out["median time (us)"] = group["totalTime_us"].median()
        out["p90 time (us)"] = group["totalTime_us"].quantile(0.9)
        out["max time (us)"] = group["totalTime_us"].max()
        out["median space points"] = group["nSpacePoints"].median()
        # an event without space points has no cost to attribute to one, so it
        # is left out of this column only and counted beside it
        occupied = group[group["nSpacePoints"] > 0]
        out["median time per space point (us)"] = (
            (occupied["totalTime_us"] / occupied["nSpacePoints"]).median()
            if len(occupied) else float("nan"))
        out["empty events"] = len(group) - len(occupied)
        out["median patterns"] = group["nPatterns"].median()
        return pd.Series(out)

    warm = events[~events["isFirst"]]
    summary = warm.groupby(["run", "repetition"]).apply(
        describe, include_groups=False).reset_index()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    events.to_csv(args.output_dir / "events.csv", index=False)
    summary.to_csv(args.output_dir / "summary.csv", index=False)

    print(summary.to_string(index=False))
    print(f"\n{len(events)} events, {len(summary)} repetitions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
