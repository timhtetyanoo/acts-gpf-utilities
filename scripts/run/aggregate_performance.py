#!/usr/bin/env python3
"""Summarise the performance of a run: the per event timing files written by
the C++ data test, and the resources the run script recorded.

The test times each call of the pattern finder on its own and writes one row per
event, in microseconds, with the GPU test adding the time of each stage and what
the event held.

A run is repeated several times, one file `timing_rNN.csv` per repetition. Two
tables are written, with the times in milliseconds and columns that say what
they hold:

  events.csv   every event of every repetition, with the name of the run, for
               plotting the cost against the occupancy
  summary.csv  one row per repetition: the mean, median, p90 and slowest event,
               and the median and p90 of each of the five stages of the GPU
               path: host before, copy to GPU, kernels, copy back, host after;
               with --logs, also the one-off setup before the first event that
               the GPU test prints, which no event pays; and the resources,
               where they were recorded: the finder process's wall time, CPU
               cores in use and peak memory (process_rNN.txt of /usr/bin/time),
               and the GPU's utilisation, memory, power and SM clock
               (gpu_rNN.csv of nvidia-smi), taken from the first to the last
               sample in which the GPU was busy

Both the mean and the median are written. They answer different questions and
differ a lot where a few events are far slower than the rest: the mean is the
total time over the events, which is what Athena's PerfMon reports as the average
CPU time per execution, and the median is the typical event. Every event counts,
the first included: the one-off setup is timed apart from the events.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

#: timing_r01.csv, as the run script names the repetitions
NAME = re.compile(r"^timing_(?P<repetition>r\d+)\.csv$")
#: the line of the GPU test's log that gives its one-off setup
SETUP = re.compile(r"^Setup time: (?P<ms>[0-9.eE+-]+) ms", re.MULTILINE)
SETUP_COLUMN = "setup before the first event (ms)"


def setup_times(logs: Path | None) -> dict[str, float]:
    """The setup time of each repetition, from logs/rNN.log, if printed"""
    times = {}
    if logs is None:
        return times
    for log in sorted(logs.glob("r*.log")):
        match = SETUP.search(log.read_text(errors="replace"))
        if match:
            times[log.stem] = float(match["ms"])
    return times


def process_resources(directory: Path) -> dict[str, dict[str, float]]:
    """Wall time, CPU cores in use and peak memory of each repetition's process"""
    out = {}
    for path in sorted(directory.glob("process_r*.txt")):
        # /usr/bin/time writes '%e %U %S %M' last, after a line on a failure
        lines = path.read_text().split("\n")
        fields = [line.split() for line in lines if line.strip()][-1]
        wall, user, system, rss_kb = (float(v) for v in fields)
        out[path.stem.removeprefix("process_")] = {
            "process wall time (s)": wall,
            "CPU cores in use by the process (mean)":
                (user + system) / wall if wall > 0 else float("nan"),
            "peak memory of the process (MiB)": rss_kb / 1024,
        }
    return out


def gpu_resources(directory: Path) -> dict[str, dict[str, float]]:
    """Utilisation, memory, power and SM clock of the GPU in each repetition"""
    out = {}
    for path in sorted(directory.glob("gpu_r*.csv")):
        samples = pd.read_csv(path, skipinitialspace=True)
        if samples.empty:
            continue
        samples.columns = [c.split(" [")[0] for c in samples.columns]
        busy = samples.index[samples["utilization.gpu"] > 0]
        window = (samples.loc[busy[0]:busy[-1]] if len(busy) else
                  samples.iloc[0:0])
        out[path.stem.removeprefix("gpu_")] = {
            "GPU utilisation while busy (mean %)":
                window["utilization.gpu"].mean(),
            "GPU memory used (peak MiB)": samples["memory.used"].max(),
            "GPU power while busy (mean W)": window["power.draw"].mean(),
            "GPU SM clock while busy (median MHz)": window["clocks.current.sm"].median(),
        }
    return out


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
    p.add_argument("--logs", type=Path, default=None,
                   help="Directory of the run's logs, rNN.log")
    args = p.parse_args()

    frames = [read_run(path, args.name)
              for path in sorted(args.directory.glob("timing_r*.csv"))]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        raise SystemExit(f"No timing files in {args.directory}")
    events = pd.concat(frames, ignore_index=True)

    ms = 1e-3  # microseconds of the raw files to milliseconds
    # the stages of the GPU path, as the timing files name them, in order
    stages = {
        "hostPreTime_us": "host before the GPU",
        "uploadTime_us": "copy to GPU",
        "kernelTime_us": "GPU kernels",
        "downloadTime_us": "copy from GPU",
        "hostPostTime_us": "host after the GPU",
    }
    stages = {raw: name for raw, name in stages.items() if raw in events}

    # events.csv: every event, the times in milliseconds
    table = pd.DataFrame({
        "run": events["run"],
        "repetition": events["repetition"],
        "event": events["event"],
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
        "overflow": ("overflow (0 none; +1 a seed's patterns; +2 a pattern's "
                     "hits; +4 the event's patterns)"),
    }
    for raw, name in gpu_columns.items():
        if raw in events:
            table[name] = events[raw]
    # device memory of each event: all of it, and the pattern building's share
    mib = 1. / (1 << 20)
    memory_columns = {
        "device_bytes": "GPU memory of the event (MiB)",
        "workspaceUsed_bytes": "GPU memory of the pattern building (MiB)",
    }
    memory_columns = {raw: name for raw, name in memory_columns.items()
                      if raw in events}
    for raw, name in memory_columns.items():
        table[name] = events[raw] * mib

    def describe(group: pd.DataFrame) -> pd.Series:
        time = group["time (ms)"]
        out = {"events": len(group)}
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
        for name in memory_columns.values():
            base = name.removesuffix(" (MiB)")
            out[f"{base} (median MiB)"] = group[name].median()
            out[f"{base} (peak MiB)"] = group[name].max()
        return pd.Series(out)

    summary = table.groupby(["run", "repetition"]).apply(
        describe, include_groups=False).reset_index()
    counts = [c for c in summary.columns
              if c.startswith(("events", "median space points",
                               "median patterns"))]
    summary[counts] = summary[counts].round().astype(int)
    setups = setup_times(args.logs)
    if setups:
        summary[SETUP_COLUMN] = summary["repetition"].map(setups)
    resources = process_resources(args.directory)
    for repetition, values in gpu_resources(args.directory).items():
        resources.setdefault(repetition, {}).update(values)
    resource_columns = sorted({c for v in resources.values() for c in v},
                              key=lambda c: (c.startswith("GPU"), c))
    for column in resource_columns:
        summary[column] = summary["repetition"].map(
            lambda r, c=column: resources.get(r, {}).get(c, float("nan")))
        summary[column] = summary[column].map(lambda v: float(f"{v:.4g}"))
    # microseconds are the finest the timing files hold
    # four significant digits, so that small times keep their precision
    times = [c for c in summary.columns if "ms" in c or "MiB" in c]
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
