#!/usr/bin/env python3
"""Plot the collected Sequencer timings.

Reads the table written by collect_timing.py and draws the time per event of
each component, one group per sample, with the spread over the repetitions as
the error bar.

The counterpart in ACTS, Examples/Scripts/Benchmarking/CKF_timing_vs_mu.py,
plots against the pile-up as a continuous axis because it scans seven values of
it. Two samples is a comparison and not a scan, so the samples are categories
here.
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
    p.add_argument("timings", type=Path, help="Csv written by collect_timing.py")
    p.add_argument("--output", type=Path, required=True, help="Figure to write")
    p.add_argument("--component", default="",
                   help="Draw only the components whose name contains this")
    args = p.parse_args()

    data = pd.read_csv(args.timings)
    if args.component:
        data = data[data["component"].str.contains(args.component)]
    if data.empty:
        raise SystemExit("Nothing to plot")

    # the median over the repetitions, and the spread as the uncertainty on it
    if "implementation" not in data.columns:
        data["implementation"] = ""
    data["series"] = (data["implementation"] + " " + data["component"]).str.strip()
    grouped = data.groupby(["sample", "series"])["time_perevent_s"]
    summary = grouped.agg(["median", "std", "size"]).reset_index()
    summary["std"] = summary["std"].fillna(0.0)

    samples = sorted(summary["sample"].unique())
    series = sorted(summary["series"].unique())
    width = 0.8 / max(len(series), 1)

    fig, ax = plt.subplots(figsize=(1.8 + 1.6 * len(samples), 3.6))
    for i, name in enumerate(series):
        rows = summary[summary["series"] == name].set_index("sample")
        centres = np.arange(len(samples)) + i * width
        values = [rows["median"].get(s, np.nan) * 1e3 for s in samples]
        errors = [rows["std"].get(s, 0.0) * 1e3 for s in samples]
        ax.bar(centres, values, width=width, yerr=errors, capsize=3,
               label=name)

    repetitions = int(data.groupby(
        ["sample", "series"]).size().max()) if len(data) else 0
    ax.set_xticks(np.arange(len(samples)) + 0.4 - width / 2)
    ax.set_xticklabels(samples)
    ax.set_ylabel("time per event [ms]")
    ax.set_title(f"median of {repetitions} runs, error bar is the spread",
                 fontsize=8)
    ax.legend(fontsize=7)
    fig.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output)
    plt.close(fig)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
