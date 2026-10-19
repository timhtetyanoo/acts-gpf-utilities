#!/usr/bin/env python3
"""Plot the per event timings of the C++ data test.

From one or more `events.csv` of aggregate_performance.py:

    left    the cost of an event against the hits it holds, which separates a
            busier event from a slower one; the line is the median per bin of
            occupancy
    middle  with --pair only: the speedup of one run over another against the
            hits, the median per bin of the ratio of their times on the same
            event; where it crosses one, the faster run changes
    right   the distribution of the cost, whose tail is what a mean would hide

Each event enters once, with the median of its repetitions. The time axis is
logarithmic over a fixed range, so plots of different runs share their bins;
events beyond the range are counted in the last bin and noted in the legend.
The occupancy axis is logarithmic too, so that runs of samples as different as
PG0 and PG200 fit on one plot; events without space points are left out of the
two occupancy panels.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import ticker  # noqa: E402

plt.rcParams.update({"figure.dpi": 150, "font.size": 9,
                     "axes.grid": True, "grid.alpha": 0.3})

T_MIN_MS = 0.1
T_MAX_MS = 2.0e4
BINS_PER_DECADE = 10
OCCUPANCY_BINS_PER_DECADE = 8
#: Fewer events than this in an occupancy bin draw no median there
MIN_EVENTS_PER_BIN = 20


def binned_median(space_points: pd.Series, values: pd.Series,
                  edges: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The median of the values in each occupancy bin that holds enough events,
    at the geometric centre of the bin"""
    index = np.digitize(space_points, edges) - 1
    centres, medians = [], []
    for b in range(len(edges) - 1):
        selected = values[index == b]
        if len(selected) >= MIN_EVENTS_PER_BIN:
            centres.append(np.sqrt(edges[b] * edges[b + 1]))
            medians.append(selected.median())
    return np.array(centres), np.array(medians)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("events", type=Path, nargs="+", help="events.csv, one per run")
    p.add_argument("--pair", nargs=2, action="append", default=[],
                   metavar=("REFERENCE", "COMPARED"),
                   help="draw the speedup of run COMPARED over run REFERENCE; "
                        "repeat for several pairs")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    data = pd.concat([pd.read_csv(f) for f in args.events], ignore_index=True)
    if data.empty:
        raise SystemExit("Nothing to plot")
    events = (data.groupby(["run", "event"], sort=False)
              .agg(time_ms=("time (ms)", "median"),
                   space_points=("space points", "first"))
              .reset_index())
    runs = set(events["run"])
    for pair in args.pair:
        missing = [r for r in pair if r not in runs]
        if missing:
            raise SystemExit(f"--pair names a run with no events: {missing}")

    n_bins = int(round(np.log10(T_MAX_MS / T_MIN_MS) * BINS_PER_DECADE))
    edges = np.logspace(np.log10(T_MIN_MS), np.log10(T_MAX_MS), n_bins + 1)
    occupied = events[events["space_points"] > 0]
    lo = np.floor(np.log10(occupied["space_points"].min()) * OCCUPANCY_BINS_PER_DECADE)
    hi = np.ceil(np.log10(occupied["space_points"].max()) * OCCUPANCY_BINS_PER_DECADE)
    occupancy_edges = 10 ** (np.arange(lo, hi + 1) / OCCUPANCY_BINS_PER_DECADE)

    n_panels = 3 if args.pair else 2
    fig, axes = plt.subplots(1, n_panels, figsize=(4.5 * n_panels, 3.4))
    cost, distribution = axes[0], axes[-1]
    for name, run in events.groupby("run", sort=False):
        times = run["time_ms"]
        above = int((times > T_MAX_MS).sum())
        run_occupied = run[run["space_points"] > 0]
        points = cost.plot(run_occupied["space_points"], run_occupied["time_ms"],
                           ".", ms=2, alpha=0.3)[0]
        centres, medians = binned_median(run_occupied["space_points"],
                                         run_occupied["time_ms"], occupancy_edges)
        cost.plot(centres, medians, "-", lw=1.5, color=points.get_color(),
                  label=name)
        label = f"{name}: median {times.median():.2f} ms"
        if above:
            label += f", {above} above {T_MAX_MS / 1e3:.0f} s"
        distribution.hist(times.clip(T_MIN_MS, T_MAX_MS * 0.999), bins=edges,
                          histtype="step", lw=1.3, color=points.get_color(),
                          label=label)

    if args.pair:
        speedup_axis = axes[1]
        for reference, compared in args.pair:
            joined = (events[events["run"] == reference]
                      .merge(events[events["run"] == compared], on="event",
                             suffixes=("_ref", "_cmp")))
            joined = joined[(joined["space_points_ref"] > 0)
                            & (joined["time_ms_cmp"] > 0)]
            ratio = joined["time_ms_ref"] / joined["time_ms_cmp"]
            centres, medians = binned_median(joined["space_points_ref"], ratio,
                                             occupancy_edges)
            speedup_axis.plot(centres, medians, "o-", ms=3, lw=1.3,
                              label=f"{compared} over {reference}")
        speedup_axis.axhline(1.0, color="black", lw=0.8)
        speedup_axis.set_xscale("log")
        speedup_axis.set_yscale("log")
        speedup_axis.yaxis.set_major_locator(
            ticker.LogLocator(base=10, subs=(1.0, 2.0, 5.0)))
        speedup_axis.yaxis.set_major_formatter(ticker.FormatStrFormatter("%g"))
        speedup_axis.yaxis.set_minor_formatter(ticker.NullFormatter())
        speedup_axis.set_xlabel("space points in the event")
        speedup_axis.set_ylabel("speedup (median per bin)")
        speedup_axis.legend(fontsize=7)

    cost.set_xlabel("space points in the event")
    cost.set_ylabel("time per event [ms]")
    cost.set_xscale("log")
    cost.set_yscale("log")
    cost.set_ylim(T_MIN_MS, T_MAX_MS)
    cost.legend(fontsize=7, title="line: median per bin", title_fontsize=7)
    distribution.set_xlabel("time per event [ms]")
    distribution.set_ylabel("events")
    distribution.set_xscale("log")
    distribution.set_yscale("log")
    distribution.set_xlim(T_MIN_MS, T_MAX_MS)
    distribution.legend(fontsize=7, loc="lower center",
                        bbox_to_anchor=(0.5, 1.0), frameon=False)
    fig.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output)
    plt.close(fig)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
