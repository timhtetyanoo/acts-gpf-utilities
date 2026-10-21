#!/usr/bin/env python3
"""Add the GPU's load during each timed pass to a throughput table.

run_throughput.sh samples the GPU with nvidia-smi while the throughput test
runs; the test records when each timed pass started and ended (passStart_s,
passEnd_s, seconds since the epoch). The samples inside each pass give its
mean utilisation and power, median SM clock and peak memory, appended to every
row of throughput.csv:

    throughput_gpu.py results/<host>/<run>/throughput.csv results/<host>/<run>/gpu.csv
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("throughput", type=Path, help="throughput.csv of the test")
    p.add_argument("samples", type=Path, help="nvidia-smi samples of the run")
    args = p.parse_args()

    table = pd.read_csv(args.throughput)
    samples = pd.read_csv(args.samples, skipinitialspace=True)
    samples.columns = [c.split(" [")[0] for c in samples.columns]
    # nvidia-smi writes local time; the test writes seconds since the epoch
    local = pd.to_datetime(samples["timestamp"], format="%Y/%m/%d %H:%M:%S.%f")
    samples["epoch"] = ((local - pd.Timestamp(0)).dt.total_seconds()
                        - time.localtime().tm_gmtoff)

    columns = {
        "gpuUtilisation_pct": ("utilization.gpu", "mean"),
        "gpuPower_W": ("power.draw", "mean"),
        "gpuClock_MHz": ("clocks.current.sm", "median"),
        "gpuMemory_MiB": ("memory.used", "max"),
    }
    for name in columns:
        table[name] = float("nan")
    for index, row in table.iterrows():
        inside = samples[(samples["epoch"] >= row["passStart_s"])
                         & (samples["epoch"] <= row["passEnd_s"])]
        if inside.empty:
            continue
        for name, (source, how) in columns.items():
            table.loc[index, name] = round(float(inside[source].agg(how)), 1)
    table.to_csv(args.throughput, index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
