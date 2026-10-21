#!/usr/bin/env python3
"""Plot events per second against threads for a CPU and a GPU throughput run.

Reads the `throughput.csv` that run_throughput.sh writes for each run and draws
one line per run on the same axes:

    plot_throughput.py results/<host>/throughput_cpu_pg200 \\
        results/<host>/throughput_cuda_pg200 \\
        --output results/<host>/compare/throughput_pg200.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cpu", type=Path, help="Run directory of the CPU throughput run")
    p.add_argument("gpu", type=Path, help="Run directory of the GPU throughput run")
    p.add_argument("--output", type=Path, required=True, help="Png to write")
    p.add_argument("--title", default="", help="Title, e.g. the sample")
    args = p.parse_args()

    fig, ax = plt.subplots(figsize=(6, 4.2))
    threads = set()
    for run, label in ((args.cpu, "CPU"), (args.gpu, "GPU")):
        data = pd.read_csv(run / "throughput.csv")
        ax.plot(data["threads"], data["eventsPerSecond"], marker="o", label=label)
        threads |= set(data["threads"].tolist())
    ax.set_xlabel("threads (events processed at once)")
    ax.set_ylabel("events per second")
    ax.set_xticks(sorted(threads))
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.3)
    ax.legend()
    if args.title:
        ax.set_title(args.title)
    fig.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=150)
    print(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
