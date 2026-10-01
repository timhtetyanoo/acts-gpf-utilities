#!/usr/bin/env python3
"""Collect the Sequencer's timing files of a benchmark run into one table.

The Sequencer writes one file per run holding one row per component:

    identifier,time_total_s,time_perevent_s

so the conditions of the run are not in the file, only in its name. This reads
every file of a directory, recovers the conditions from the name, and writes one
tidy table:

    sample, events, threads, repetition, component, time_total_s, time_perevent_s

The ACTS benchmarking scripts pull the number they want out of the timing file
with `grep` and `awk`. The file is a csv, so it is parsed as one here instead:
the same scripts still read `timing.tsv` and split on tabs, which the Sequencer
stopped writing.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

#: timing_<sample>_e<events>_t<threads>_r<repetition>.csv
NAME = re.compile(r"^timing_(?P<sample>.+)_e(?P<events>\d+)"
                  r"_t(?P<threads>\d+)_r(?P<repetition>\d+)\.csv$")


def rows_of(path: Path) -> list[dict]:
    """The rows of one timing file, with the conditions from its name."""
    match = NAME.match(path.name)
    if match is None:
        return []
    conditions = {
        "sample": match["sample"],
        "events": int(match["events"]),
        "threads": int(match["threads"]),
        "repetition": int(match["repetition"]),
    }
    rows = []
    with path.open() as handle:
        for row in csv.DictReader(handle):
            # the sequencer leaves a blank line at the end
            if not row.get("identifier"):
                continue
            rows.append({
                **conditions,
                "component": row["identifier"],
                "time_total_s": float(row["time_total_s"]),
                "time_perevent_s": float(row["time_perevent_s"]),
            })
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("directory", type=Path, help="Directory of the timing files")
    p.add_argument("--output", type=Path, required=True, help="Csv to write")
    args = p.parse_args()

    collected = []
    for path in sorted(args.directory.glob("timing_*.csv")):
        found = rows_of(path)
        if not found:
            print(f"Skipping {path.name}, the name does not say what was run")
            continue
        collected.extend(found)

    if not collected:
        raise SystemExit(f"No timing files found in {args.directory}")

    with args.output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(collected[0]))
        writer.writeheader()
        writer.writerows(collected)

    runs = {(r["sample"], r["events"], r["threads"], r["repetition"])
            for r in collected}
    print(f"Collected {len(collected)} rows from {len(runs)} runs "
          f"into {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
