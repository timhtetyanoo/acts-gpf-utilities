#!/usr/bin/env python3
"""Summarise the per event timing files written by the C++ data test.

The test times each call of the pattern finder on its own and writes one row per
event, in microseconds, with the GPU test adding the time of each stage and what
the event held.

A run is repeated several times, one file `timing_rNN.csv` per repetition. Two
tables are written, with the times in milliseconds and columns that say what
they hold:

  events.csv   every event of every repetition, with the name of the run, for
               plotting the cost against the occupancy
  summary.csv  one row per repetition: the mean, median, p90 and slowest event,
               and the median and p90 of each stage of the GPU path

Both the mean and the median are written. They answer different questions and
differ a lot where a few events are far slower than the rest: the mean is the
total time over the events, which is what Athena's PerfMon reports as the average
CPU time per execution, and the median is the typical event. The first event of
each repetition is left out of the summary, since it pays for cold caches.
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
    first = events.groupby(["run", "repetition"])["event"].transform("min") \
        == events["event"]

    ms = 1e-3  # microseconds of the raw files to milliseconds
    # the stages of the GPU path, as the timing files name them
    stages = {
        "treeTime_us": "host: positions and search tree",
        "fillTime_us": "host: candidate lists",
        # the experimental branch: the search on the GPU
        "usedHitsTime_us": "host: used hits and bucket transforms",
        "columnsTime_us": "host: hit columns",
        "searchTime_us": "GPU: search and candidate lists",
        "uploadTime_us": "copy to GPU",
        "kernelTime_us": "GPU kernels",
        "seedTime_us": "GPU kernels: seed checks",
        "buildTime_us": "GPU kernels: pattern building",
        "overlapTime_us": "GPU kernels: overlaps and compaction",
        "downloadTime_us": "copy from GPU",
        "tailTime_us": "host: phi-only hits and output",
    }
    stages = {raw: name for raw, name in stages.items() if raw in events}

    # events.csv: every event, the times in milliseconds
    table = pd.DataFrame({
        "run": events["run"],
        "repetition": events["repetition"],
        "event": events["event"],
        "first of the repetition (left out of the summary)": first,
        "space points": events["nSpacePoints"],
        "buckets": events["nBuckets"],
        "patterns": events["nPatterns"],
        "time (ms)": events["totalTime_us"] * ms,
    })
    for raw, name in stages.items():
        table[f"{name} (ms)"] = events[raw] * ms
    gpu_columns = {
        "nSeeds": "seeds",
        "nCandidates": "candidate hits of all seeds",
        "nPatternsInEta": "patterns kept on the GPU",
        "capacityPerSeed": "patterns a seed had room for",
        "largestBeam": "most patterns a seed held at once",
        "overflow": ("overflow (0 none; +1 a seed's patterns; +2 a pattern's "
                     "hits; +4 the event's patterns)"),
    }
    for raw, name in gpu_columns.items():
        if raw in events:
            table[name] = events[raw]

    def describe(group: pd.DataFrame) -> pd.Series:
        time = group["time (ms)"]
        out = {"events (first left out)": len(group)}
        out["mean time per event (ms)"] = time.mean()
        out["median time per event (ms)"] = time.median()
        out["p90 time per event (ms)"] = time.quantile(0.9)
        out["slowest event (ms)"] = time.max()
        # events handled per second of finder time, one event after the other: the
        # inverse of the mean time, so the slowest events weigh as they do in the mean
        out["throughput (events/s)"] = len(group) / (time.sum() / 1e3)
        for name in stages.values():
            out[f"{name} (median ms)"] = group[f"{name} (ms)"].median()
            out[f"{name} (p90 ms)"] = group[f"{name} (ms)"].quantile(0.9)
        out["median space points per event"] = group["space points"].median()
        # an event without space points has no cost to attribute to one, so it
        # is left out of this column only and counted beside it
        occupied = group[group["space points"] > 0]
        out["median time per space point (ms)"] = (
            (occupied["time (ms)"] / occupied["space points"]).median()
            if len(occupied) else float("nan"))
        out["events without space points"] = len(group) - len(occupied)
        out["median patterns per event"] = group["patterns"].median()
        if "overflow" in events:
            out["events with an overflow"] = int((group[gpu_columns["overflow"]] != 0).sum())
        return pd.Series(out)

    warm = table[~first]
    summary = warm.groupby(["run", "repetition"]).apply(
        describe, include_groups=False).reset_index()
    counts = [c for c in summary.columns
              if c.startswith(("events", "median space points",
                               "median patterns"))]
    summary[counts] = summary[counts].round().astype(int)
    # microseconds are the finest the timing files hold
    # four significant digits, so that small times keep their precision
    times = [c for c in summary.columns if "ms" in c]
    summary[times] = summary[times].map(lambda v: float(f"{v:.4g}"))
    summary["throughput (events/s)"] = summary["throughput (events/s)"].round(1)
    table[[c for c in table.columns if "(ms)" in c]] = \
        table[[c for c in table.columns if "(ms)" in c]].round(3)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.output_dir / "events.csv", index=False)
    summary.to_csv(args.output_dir / "summary.csv", index=False)

    print(summary.to_string(index=False))
    print(f"\n{len(events)} events, {len(summary)} repetitions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
