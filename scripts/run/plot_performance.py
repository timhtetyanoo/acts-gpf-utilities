#!/usr/bin/env python3
"""Plot the per event timings of the C++ data test.

Two panels, from one or more `events.csv` of aggregate_performance.py:

    left   the cost of an event against the hits it holds, which separates a
           busier event from a slower one
    right  the distribution of the cost, whose tail is what a mean would hide

Each event enters once, with the median of its repetitions. The time axis is
logarithmic over a fixed range, so plots of different runs share their bins;
events beyond the range are counted in the last bin and noted in the legend.
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

plt.rcParams.update({"figure.dpi": 150, "font.size": 9,
                     "axes.grid": True, "grid.alpha": 0.3})

T_MIN_MS = 0.1
T_MAX_MS = 2.0e4
BINS_PER_DECADE = 10


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("events", type=Path, nargs="+", help="events.csv, one per run")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    data = pd.concat([pd.read_csv(f) for f in args.events], ignore_index=True)
    if data.empty:
        raise SystemExit("Nothing to plot")
    events = (data.groupby(["run", "event"], sort=False)
              .agg(time_ms=("time (ms)", "median"),
                   space_points=("space points", "first"))
              .reset_index())

    n_bins = int(round(np.log10(T_MAX_MS / T_MIN_MS) * BINS_PER_DECADE))
    edges = np.logspace(np.log10(T_MIN_MS), np.log10(T_MAX_MS), n_bins + 1)

    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.4))
    for name, run in events.groupby("run", sort=False):
        times = run["time_ms"]
        above = int((times > T_MAX_MS).sum())
        axes[0].plot(run["space_points"], times, ".", ms=2, alpha=0.5,
                     label=name)
        label = f"{name}: median {times.median():.2f} ms"
        if above:
            label += f", {above} above {T_MAX_MS / 1e3:.0f} s"
        axes[1].hist(times.clip(T_MIN_MS, T_MAX_MS * 0.999), bins=edges,
                     histtype="step", lw=1.3, label=label)

    axes[0].set_xlabel("space points in the event")
    axes[0].set_ylabel("time per event [ms]")
    axes[0].set_yscale("log")
    axes[0].set_ylim(T_MIN_MS, T_MAX_MS)
    axes[0].legend(fontsize=7, markerscale=4)
    axes[1].set_xlabel("time per event [ms]")
    axes[1].set_ylabel("events")
    axes[1].set_xscale("log")
    axes[1].set_yscale("log")
    axes[1].set_xlim(T_MIN_MS, T_MAX_MS)
    axes[1].legend(fontsize=7, loc="lower center", bbox_to_anchor=(0.5, 1.0),
                   frameon=False)
    fig.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output)
    plt.close(fig)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
