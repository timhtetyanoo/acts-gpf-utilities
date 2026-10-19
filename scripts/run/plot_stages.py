#!/usr/bin/env python3
"""Plot where the time of an event goes.

From one or more `events.csv` of aggregate_performance.py:

    left   one bar per run: the median of each stage of the GPU path, stacked;
           a run without stages, such as the CPU, is one bar of its median
           time. The tick on each bar is the median of the whole event, which
           differs from the sum of the stage medians
    right  the share of each stage against the hits the event holds: the
           median of each stage per bin of occupancy, as a fraction of their
           sum, for every run with stages

Each event enters once, with the median of its repetitions.
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

from plot_performance import (MIN_EVENTS_PER_BIN,  # noqa: E402
                              OCCUPANCY_BINS_PER_DECADE)

plt.rcParams.update({"figure.dpi": 150, "font.size": 9,
                     "axes.grid": True, "grid.alpha": 0.3})

#: The stages of the GPU path, in the order they run
STAGES = [
    "host before the GPU (ms)",
    "copy to GPU (ms)",
    "GPU kernels (ms)",
    "copy from GPU (ms)",
    "host after the GPU (ms)",
]
TOTAL = "time (ms)"
#: The colour of a run without stages, which has only its whole event
WHOLE_EVENT_COLOUR = "0.55"


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("events", type=Path, nargs="+", help="events.csv, one per run")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    data = pd.concat([pd.read_csv(f) for f in args.events], ignore_index=True)
    if data.empty:
        raise SystemExit("Nothing to plot")
    columns = [TOTAL] + [s for s in STAGES if s in data.columns]
    events = (data.groupby(["run", "event"], sort=False)
              .agg({"space points": "first", **{c: "median" for c in columns}})
              .reset_index())
    runs = list(dict.fromkeys(events["run"]))
    has_stages = {r: all(s in events.columns
                         and events.loc[events["run"] == r, s].notna().any()
                         for s in STAGES) for r in runs}
    colours = dict(zip(STAGES, plt.get_cmap("tab10").colors))

    fig, (bars, occupancy) = plt.subplots(1, 2, figsize=(10.0, 3.6))
    y = np.arange(len(runs))[::-1]
    labelled = False
    for row, run in zip(y, runs):
        selected = events[events["run"] == run]
        if has_stages[run]:
            left = 0.0
            for stage in STAGES:
                width = selected[stage].median()
                bars.barh(row, width, left=left, color=colours[stage],
                          label=None if labelled else stage.removesuffix(" (ms)"))
                left += width
            labelled = True
        else:
            bars.barh(row, selected[TOTAL].median(), color=WHOLE_EVENT_COLOUR)
        total = selected[TOTAL].median()
        bars.plot([total, total], [row - 0.4, row + 0.4], color="black", lw=1.2)
        bars.annotate(f"{total:.2f} ms", (total, row), xytext=(4, 0),
                      textcoords="offset points", va="center", fontsize=7)
    bars.set_yticks(y, runs, fontsize=7)
    bars.set_xlabel("median time per event [ms]")
    bars.set_xlim(0, events.groupby("run")[TOTAL].median().max() * 1.25)
    if labelled:
        bars.legend(fontsize=7, loc="lower right")

    occupied = events[events["space points"] > 0]
    lo = np.floor(np.log10(occupied["space points"].min()) * OCCUPANCY_BINS_PER_DECADE)
    hi = np.ceil(np.log10(occupied["space points"].max()) * OCCUPANCY_BINS_PER_DECADE)
    edges = 10 ** (np.arange(lo, hi + 1) / OCCUPANCY_BINS_PER_DECADE)
    for run in runs:
        if not has_stages[run]:
            continue
        selected = occupied[occupied["run"] == run]
        index = np.digitize(selected["space points"], edges) - 1
        filled = [b for b in range(len(edges) - 1)
                  if (index == b).sum() >= MIN_EVENTS_PER_BIN]
        if not filled:
            continue
        centres = np.sqrt(edges[filled] * edges[np.array(filled) + 1])
        medians = np.array([[selected.loc[index == b, s].median() for b in filled]
                            for s in STAGES])
        occupancy.stackplot(centres, 100 * medians / medians.sum(axis=0),
                            colors=[colours[s] for s in STAGES], alpha=0.85)
    occupancy.set_xscale("log")
    occupancy.set_ylim(0, 100)
    occupancy.set_xlabel("space points in the event")
    occupancy.set_ylabel("share of the GPU path [%] (median per bin)")
    fig.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output)
    plt.close(fig)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
