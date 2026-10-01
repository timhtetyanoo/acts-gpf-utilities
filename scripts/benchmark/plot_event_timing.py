#!/usr/bin/env python3
"""Plot the per event timings of the C++ data test.

Two panels, from `event_timings.csv` of aggregate_event_timing.py:

    left   the cost of an event against the hits it holds, which separates a
           busier event from a slower one
    right  the distribution of the cost, whose tail is what a mean would hide

The first event of each run is left out: it pays for cold caches.
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


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("events", type=Path, help="event_timings.csv")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    data = pd.read_csv(args.events)
    data = data[~data["isFirst"]]
    if data.empty:
        raise SystemExit("Nothing to plot")
    data["totalTime_ms"] = data["totalTime_us"] / 1e3

    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.4))
    for label, run in data.groupby(["sample", "implementation"]):
        name = " ".join(label)
        axes[0].plot(run["nSpacePoints"], run["totalTime_ms"], ".", ms=2,
                     alpha=0.5, label=name)
        axes[1].hist(run["totalTime_ms"], bins=40, histtype="step", lw=1.3,
                     label=f"{name}: median {run['totalTime_ms'].median():.2f} ms")

    axes[0].set_xlabel("space points in the event")
    axes[0].set_ylabel("time per event [ms]")
    axes[0].legend(fontsize=7, markerscale=4)
    axes[1].set_xlabel("time per event [ms]")
    axes[1].set_ylabel("events")
    axes[1].set_yscale("log")
    axes[1].legend(fontsize=7)
    fig.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output)
    plt.close(fig)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
