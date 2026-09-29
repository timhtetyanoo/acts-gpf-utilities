#!/usr/bin/env python3
"""Turn the validation tables into the five numbers, applying the definitions.

The tables produced by build_validation_tables.py only count. Every definition
lives here, so a definition can be changed and re-applied in a second without
running the pattern finder again. What each test means and why it is built this
way is in docs/validation.md; this file is only the arithmetic.

    1  efficiency          found muons / all truth muons
    2  composition         purity, mismatched fraction, selectivity
    3  hits on the path    mean squared pull against the truth line
    4  fakes & duplicates  patterns matching nothing, muons matched twice
    5  direction           the pattern's eta and phi against the muon's

The matching criterion is ACTS's, from TrackTruthMatcher: a pattern matches a
muon when it holds a majority of that muon's findable surfaces *and* a majority
of its own hits are that muon's, both at 0.5, which is `matchingRatio` with
`doubleMatching` enabled. Requiring both is what stops a pattern that swept up a
whole chamber from counting as having found the muon it caught on the way.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

#: ACTS's matchingRatio, used on both sides of the match
MATCHING_RATIO = 0.5
#: A pattern confined to one chamber is not a muon candidate
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

    # test 1 and test 2, all from counts already in the table
    patterns["completeness"] = ratio(patterns["shared"],
                                     patterns["findable"].fillna(0))
    patterns["purity"] = ratio(patterns["nHitsMainMuon"], patterns["nHits"])
    patterns["mismatched"] = ratio(patterns["nHitsOtherMuon"], patterns["nHits"])
    patterns["selectivity"] = ratio(patterns["nHits"], patterns["nAvailable"])

    # test 3, summarised per pattern over the chambers it crossed
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

    # ACTS's double matching: a majority of the muon and a majority of the
    # pattern, plus the requirement that the pattern followed the muon across
    # more than one chamber
    patterns["isMatch"] = (
        (patterns["mainMuon"] >= 0)
        & (patterns["completeness"] >= matching_ratio)
        & (patterns["purity"] >= matching_ratio)
        & (patterns["stationsWithMuon"] >= min_stations)
    )

    # the best pattern of a muon is the one sharing the most of it; the rest are
    # duplicates, and are not fakes
    ranked = patterns[patterns["isMatch"]].sort_values("shared", ascending=False)
    best = ranked.drop_duplicates(["event", "mainMuon"])
    patterns["isDuplicate"] = patterns["isMatch"] & ~patterns.index.isin(best.index)

    muons = muons.merge(
        best[["event", "mainMuon", "pattern", "completeness", "purity",
              "mismatched", "selectivity", "meanSqPull", "eta", "phi"]]
        .rename(columns={"mainMuon": "muon", "eta": "patternEta",
                         "phi": "patternPhi"}),
        on=["event", "muon"], how="left")
    muons["found"] = muons["pattern"].notna()
    # test 5: the pattern's direction against the muon's at production
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
        "events": events,
        "truth_muons": len(muons),
        "patterns": len(patterns),
        # 1. efficiency, over every truth muon with no acceptance cut
        "efficiency": len(found) / len(muons) if len(muons) else 0.0,
        "mean_completeness": float(found["completeness"].mean()) if len(found) else np.nan,
        # 2. what the matched patterns are made of
        "mean_purity": float(matched["purity"].mean()) if len(matched) else np.nan,
        "mean_mismatched": float(matched["mismatched"].mean()) if len(matched) else np.nan,
        "mean_selectivity": float(matched["selectivity"].mean()) if len(matched) else np.nan,
        # 3. are those hits on the muon's path
        "median_meanSqPull": float(matched["meanSqPull"].median()) if len(matched) else np.nan,
        # 4. patterns that matched no truth muon. Whether one of those is a
        # fake depends on the sample: without pile-up every particle that
        # crossed the spectrometer is in the truth tree, so it is one, while a
        # pattern of a pile-up muon has nothing to match and cannot be told from
        # a fake. The count is the same either way, so it is reported under the
        # name that is true either way.
        "patterns_per_event": len(patterns) / events if events else 0.0,
        "unmatched_per_event": len(unmatched) / events if events else 0.0,
        "unmatched_fraction": len(unmatched) / len(patterns) if len(patterns) else 0.0,
        "duplicates_per_found_muon": (float(muons["nDuplicates"].sum() / len(found))
                                      if len(found) else 0.0),
        # 5. direction
        "dEta_mean": float(found["dEta"].mean()) if len(found) else np.nan,
        "dEta_rms": float(found["dEta"].std()) if len(found) else np.nan,
        "dPhi_mean": float(found["dPhi"].mean()) if len(found) else np.nan,
        "dPhi_rms": float(found["dPhi"].std()) if len(found) else np.nan,
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
