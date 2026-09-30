#!/usr/bin/env python3
"""Computes the following metrics:

    1  efficiency          found muons / all truth muons
    2  composition         purity, mismatched fraction, selectivity
    3  hits on the path    mean squared pull against the truth line
    4  fakes & duplicates  patterns matching nothing, muons matched twice
    5  direction           the pattern's eta and phi against the muon's
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Threshold for the pattern to be considered a muon candidate
MATCHING_RATIO = 0.5
#: Minimum number of stations that the pattern must cross to be considered a muon candidate
MIN_STATIONS = 2


def load(tables: Path) -> dict[str, pd.DataFrame]:
    return {name: pd.read_parquet(tables / f"{name}.parquet")
            for name in ("muons", "patterns", "pattern_chamber")}


def derive(data: dict[str, pd.DataFrame], matching_ratio: float,
           min_stations: int):
    """Add the fractions and the match flags to the pattern and muon tables."""
    muons = data["muons"].copy()
    patterns = data["patterns"].merge(
        muons[["event", "muon", "findable"]].rename(columns={"muon": "mainMuon"}),
        on=["event", "mainMuon"], how="left")

    def ratio(numerator, denominator):
        return np.where(denominator > 0,
                        numerator / denominator.replace(0, np.nan), np.nan)

    patterns["completeness"] = ratio(patterns["shared"],
                                     patterns["findable"].fillna(0))
    patterns["purity"] = ratio(patterns["nHitsMainMuon"], patterns["nHits"])
    patterns["mismatched"] = ratio(patterns["nHitsOtherMuon"], patterns["nHits"])
    patterns["selectivity"] = ratio(patterns["nHits"], patterns["nAvailable"])

    chamber = data["pattern_chamber"]
    if len(chamber):
        per_pattern = chamber.groupby(["event", "pattern"]).apply(
            lambda g: pd.Series({
                "meanSqPull": np.average(
                    g["meanSqPull"].fillna(0), weights=g["nHitsPulled"])
                if g["nHitsPulled"].sum() else np.nan,
                "nHitsNoSegment": int(g["nHitsNoSegment"].sum()),
            }), include_groups=False).reset_index()
        patterns = patterns.merge(per_pattern, on=["event", "pattern"], how="left")
    else:
        patterns[["meanSqPull", "nHitsNoSegment"]] = np.nan

    # The pattern is considered a muon candidate if it meets the following criteria:
    # - The pattern has a main muon assigned to it
    # - The pattern's completeness is greater than or equal to the matching ratio
    # - The pattern's purity is greater than or equal to the matching ratio
    # - The pattern has crossed at least min_stations stations
    patterns["isMatch"] = (
        (patterns["mainMuon"] >= 0)
        & (patterns["completeness"] >= matching_ratio)
        & (patterns["purity"] >= matching_ratio)
        & (patterns["stationsWithMuon"] >= min_stations)
    )

    # The pattern with the most shared hits is chosen for the muon; the rest are
    # duplicates, and are not fakes. Ties are broken on the pattern itself and
    # never on the order of the rows: the sequencer returns the events in
    # whatever order its threads finish them, and which pattern represents a
    # muon must not depend on that. Purity, then the distance of the hits from
    # the muon's line, then the index the finder gave the pattern inside its own
    # event, which is the same however the events were scheduled.
    ranked = patterns[patterns["isMatch"]].sort_values(
        ["shared", "purity", "meanSqPull", "pattern"],
        ascending=[False, False, True, True], kind="stable")
    best = ranked.drop_duplicates(["event", "mainMuon"])
    patterns["isDuplicate"] = patterns["isMatch"] & ~patterns.index.isin(best.index)

    muons = muons.merge(
        best[["event", "mainMuon", "pattern", "completeness", "purity",
              "mismatched", "selectivity", "meanSqPull", "eta", "phi"]]
        .rename(columns={"mainMuon": "muon", "eta": "patternEta",
                         "phi": "patternPhi"}),
        on=["event", "muon"], how="left")
    muons["found"] = muons["pattern"].notna()

    muons["dEta"] = muons["patternEta"] - muons["eta"]
    muons["dPhi"] = (muons["patternPhi"] - muons["phi"] + np.pi) % (2 * np.pi) - np.pi

    counts = (patterns[patterns["isDuplicate"]]
              .groupby(["event", "mainMuon"]).size().rename("nDuplicates")
              .reset_index().rename(columns={"mainMuon": "muon"}))
    muons = muons.merge(counts, on=["event", "muon"], how="left")
    muons["nDuplicates"] = muons["nDuplicates"].fillna(0).astype(int)
    return patterns, muons


def metrics(patterns: pd.DataFrame, muons: pd.DataFrame) -> dict:
    events = int(patterns["event"].nunique()) if len(patterns) else 0
    found = muons[muons["found"]]
    matched = patterns[patterns["isMatch"]]
    unmatched = patterns[~patterns["isMatch"]]

    out = {
        # Number of events that contain at least one pattern.
        "events": events,
        # Number of truth muons in the sample.
        "truth_muons": len(muons),
        # Number of patterns the pattern finder produced.
        "patterns": len(patterns),

        # 1. Efficiency
        # Fraction of truth muons that have at least one matching pattern.
        # 1 means every muon was found.
        "efficiency": len(found) / len(muons) if len(muons) else 0.0,
        # Fraction of the surfaces where the muon left a hit that the pattern contains.
        # Averaged over all found muons. 1 means no hit was missed.
        "mean_completeness": float(found["completeness"].mean()) if len(found) else np.nan,

        # 2. Composition
        # Fraction of a pattern's hits that belong to the muon it was matched
        # to. Averaged over matched patterns. 1 means no foreign hits.
        "mean_purity": float(matched["purity"].mean()) if len(matched) else np.nan,
        # Fraction of a pattern's hits that belong to a different truth muon.
        # Averaged over matched patterns. 0 means no hits from another muon.
        "mean_mismatched": float(matched["mismatched"].mean()) if len(matched) else np.nan,
        # Fraction of the hits selected by the pattern over the hits available in the buckets it drew from. 
        # Averaged over matched patterns. Low means the finder rejected most of the hits around the muon.
        "mean_selectivity": float(matched["selectivity"].mean()) if len(matched) else np.nan,

        # 3. Hits on the path
        # The mean squared pull of the muon's hits about its truth line.
        # Averaged over matched patterns. About 1 is ideal; much larger means
        # the hits are further from the truth than their errors say.
        "median_meanSqPull": float(matched["meanSqPull"].median()) if len(matched) else np.nan,
        
        # 4. Fakes & Duplicates
        # Average number of patterns per event.
        "patterns_per_event": len(patterns) / events if events else 0.0,
        # Average number of patterns per event that matched no truth muon.
        # 0 is ideal.
        "unmatched_per_event": len(unmatched) / events if events else 0.0,
        # Fraction of all patterns that matched no truth muon. 0 is ideal.
        "unmatched_fraction": len(unmatched) / len(patterns) if len(patterns) else 0.0,
        # Average number of duplicates per found muon. 0 is ideal.
        "duplicates_per_found_muon": (float(muons["nDuplicates"].sum() / len(found))
                                      if len(found) else 0.0),

        # 5. Direction
        # Mean of the difference in eta between the pattern and the muon. 0 means the pattern eta is not systematically off.
        "dEta_mean": float(found["dEta"].mean()) if len(found) else np.nan,
        # Spread (standard deviation) of the difference in eta between the pattern and the muon. Smaller is better.
        "dEta_std": float(found["dEta"].std()) if len(found) else np.nan,
        # Mean of the difference in phi between the pattern and the muon. 0 means the pattern phi is not systematically off.
        "dPhi_mean": float(found["dPhi"].mean()) if len(found) else np.nan,
        # Spread (standard deviation) of the difference in phi between the pattern and the muon. Smaller is better.
        "dPhi_std": float(found["dPhi"].std()) if len(found) else np.nan,
    }
    return out


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tables", type=Path, help="Directory of build_validation_tables.py")
    p.add_argument("--sample", default="", help="Label of the sample, e.g. PG0")
    p.add_argument("--implementation", default="", help="Label, e.g. cpu or cuda")
    p.add_argument("--matching-ratio", type=float, default=MATCHING_RATIO,
                   help="ACTS's matchingRatio, applied to completeness and purity")
    p.add_argument("--min-stations", type=int, default=MIN_STATIONS)
    p.add_argument("--output", type=Path, help="Csv the summary row is appended to")
    p.add_argument("--scan", action="store_true",
                   help="Print the metrics against the matching ratio")
    args = p.parse_args()

    data = load(args.tables)

    if args.scan:
        print(f"{'matching ratio':>15}{'efficiency':>12}{'unmatched/ev':>14}"
              f"{'duplicates':>12}")
        for value in np.arange(0.1, 1.01, 0.1):
            row = metrics(*derive(data, value, args.min_stations))
            print(f"{value:>15.1f}{row['efficiency']:>12.4f}"
                  f"{row['unmatched_per_event']:>14.3f}"
                  f"{row['duplicates_per_found_muon']:>12.3f}")
        print()

    patterns, muons = derive(data, args.matching_ratio, args.min_stations)
    patterns.to_parquet(args.tables / "pattern_flags.parquet", index=False)
    muons.to_parquet(args.tables / "muon_flags.parquet", index=False)

    summary = {
        "sample": args.sample or args.tables.name,
        "implementation": args.implementation,
        "matching_ratio": args.matching_ratio,
        "min_stations": args.min_stations,
        **metrics(patterns, muons),
    }
    width = max(len(key) for key in summary)
    for key, value in summary.items():
        print(f"{key:<{width}}  {value}")

    if args.output:
        pd.DataFrame([summary]).to_csv(
            args.output, mode="a", header=not args.output.exists(), index=False)
        print(f"\nAppended the summary to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
