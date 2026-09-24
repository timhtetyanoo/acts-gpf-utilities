#!/usr/bin/env python3
"""Score found patterns against the truth.

A pattern and a truth muon are matched when they share geometry identifiers.
Since one identifier covers several space points of a layer, the distinct
identifiers are counted, never the hits themselves.

    shared      = |geo ids of the pattern & geo ids of the muon|
    efficiency  = fraction of truth muons with at least one matched pattern
    duplicates  = matched patterns beyond the first one of a muon, per muon
    fakes       = fraction of patterns matched to no muon
    purity      = shared / |geo ids of the pattern|, averaged over matches
    completeness= shared / |geo ids of the muon|, averaged over matches

One row is appended to the output csv per scored file, which keeps the numbers
of every sample and implementation in one table for the plots.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import uproot


def load_patterns(path: Path, tree: str) -> pd.DataFrame:
    """Return one row per pattern hit: event, pattern, geo_id."""
    arrays = uproot.open(path)[tree].arrays(
        ["event_id", "hit_patternIdx", "hit_geometryId"], library="np"
    )
    rows = []
    for event, patterns, geo_ids in zip(
        arrays["event_id"], arrays["hit_patternIdx"], arrays["hit_geometryId"]
    ):
        for pattern, geo_id in zip(patterns, geo_ids):
            rows.append((int(event), int(pattern), int(geo_id)))
    return pd.DataFrame(rows, columns=["event", "pattern", "geo_id"])


def score(patterns: pd.DataFrame, truth: pd.DataFrame, min_shared: int) -> dict:
    """Match patterns against truth muons and return the summary numbers."""
    pattern_ids = (
        patterns.groupby(["event", "pattern"])["geo_id"].apply(set).to_dict()
    )
    truth_ids = truth.groupby(["event", "muon"])["geo_id"].apply(set).to_dict()

    matched_muons: set[tuple[int, int]] = set()
    matched_patterns: set[tuple[int, int]] = set()
    duplicates = 0
    purities: list[float] = []
    completeness: list[float] = []

    for (event, muon), muon_geo in truth_ids.items():
        candidates = [
            (key, ids)
            for key, ids in pattern_ids.items()
            if key[0] == event and len(ids & muon_geo) >= min_shared
        ]
        if not candidates:
            continue
        matched_muons.add((event, muon))
        # the pattern sharing the most identifiers is the match, the rest are
        # duplicates of the same muon
        candidates.sort(key=lambda item: len(item[1] & muon_geo), reverse=True)
        duplicates += len(candidates) - 1
        for key, ids in candidates:
            matched_patterns.add(key)
        best = candidates[0][1]
        shared = len(best & muon_geo)
        purities.append(shared / len(best))
        completeness.append(shared / len(muon_geo))

    n_truth = len(truth_ids)
    n_patterns = len(pattern_ids)
    fakes = n_patterns - len(matched_patterns)
    return {
        "events": int(patterns["event"].nunique()),
        "truth_muons": n_truth,
        "patterns": n_patterns,
        "matched_muons": len(matched_muons),
        "efficiency": len(matched_muons) / n_truth if n_truth else 0.0,
        "duplicates_per_muon": duplicates / n_truth if n_truth else 0.0,
        "fake_fraction": fakes / n_patterns if n_patterns else 0.0,
        "hit_purity": sum(purities) / len(purities) if purities else 0.0,
        "hit_completeness": (
            sum(completeness) / len(completeness) if completeness else 0.0
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("patterns", type=Path, help="Pattern file written by the example")
    p.add_argument("truth", type=Path, help="Parquet file from preprocess_truth.py")
    p.add_argument("--tree", default="muonGlobalPatterns", help="Pattern tree name")
    p.add_argument("--sample", default="", help="Label of the sample, e.g. PG0")
    p.add_argument("--implementation", default="", help="Label, e.g. cpu or cuda")
    p.add_argument(
        "--min-shared",
        type=int,
        default=3,
        help="Distinct geometry ids a pattern & a muon must share to match",
    )
    p.add_argument("--output", type=Path, help="Csv the summary row is appended to")
    args = p.parse_args()

    patterns = load_patterns(args.patterns, args.tree)
    truth = pd.read_parquet(args.truth)

    summary = {
        "sample": args.sample or args.patterns.stem,
        "implementation": args.implementation,
        "min_shared": args.min_shared,
        **score(patterns, truth, args.min_shared),
    }

    width = max(len(key) for key in summary)
    for key, value in summary.items():
        print(f"{key:<{width}}  {value}")

    if args.output:
        row = pd.DataFrame([summary])
        header = not args.output.exists()
        row.to_csv(args.output, mode="a", header=header, index=False)
        print(f"\nAppended the summary to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
