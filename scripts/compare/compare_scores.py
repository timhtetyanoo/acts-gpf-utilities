#!/usr/bin/env python3
"""Put the validation scores of two runs side by side.

Reads the `scores.csv` of each run's validation and writes one row per metric:

    metric | <reference> | <compared> | difference

The difference is the compared value minus the reference value; text columns
(the sample, the run) have none.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


def difference(ref, cmp):
    """Compared minus reference: whole for counts, four significant digits for
    fractions"""
    if pd.api.types.is_integer(ref) and pd.api.types.is_integer(cmp):
        return int(cmp - ref)
    return float(f"{cmp - ref:.4g}")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("reference", type=Path, help="scores.csv of the reference")
    p.add_argument("compared", type=Path, help="scores.csv to compare")
    p.add_argument("--reference-label", default="reference")
    p.add_argument("--compare-label", default="compared")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    # the last row of each: a validation run again appends to its scores
    reference = pd.read_csv(args.reference).iloc[-1]
    compared = pd.read_csv(args.compared).iloc[-1]
    rows = []
    for metric in reference.index:
        if metric not in compared.index:
            continue
        ref, cmp = reference[metric], compared[metric]
        numeric = (pd.api.types.is_number(ref) and
                   pd.api.types.is_number(cmp))
        rows.append({
            "metric": metric,
            args.reference_label: ref,
            args.compare_label: cmp,
            f"difference ({args.compare_label} minus {args.reference_label})":
                difference(ref, cmp) if numeric else "",
        })
    out = pd.DataFrame(rows)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    print(out.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
