#!/usr/bin/env python3
"""Computes the following metrics:

    1  efficiency          found muons / selected truth muons
    2  composition         purity, mismatched fraction, selectivity
    3  hits on the path    mean squared pull against the truth line
    4  fakes & duplicates  patterns that are not the match of a muon, muons matched twice
    5  direction           the pattern's eta and phi against the muon's

The selection of the truth muons, which pattern counts as matching a muon and
which of several is the one that stands for it are those of
MuonFastRecoValidation, transcribed in gpfval.py, so that the efficiency and the
fake rate here are the numbers its plots show.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import gpfval


def load(tables: Path) -> dict[str, pd.DataFrame]:
    data = {name: pd.read_parquet(tables / f"{name}.parquet")
            for name in ("muons", "patterns", "pattern_chamber")}
    data["pulls"] = pattern_pulls(data["pattern_chamber"])
    return data


def pattern_pulls(chamber: pd.DataFrame) -> pd.DataFrame:
    """Per pattern: the mean squared pull of the hits that have one, averaged over
    the chambers with the number of hits as weight, and the hits that belong to no
    segment. Independent of every threshold, so it is computed once."""
    if chamber.empty:
        return pd.DataFrame(columns=["event", "pattern", "meanSqPull", "nHitsNoSegment"])
    frame = chamber.assign(
        weighted=chamber["meanSqPull"].fillna(0) * chamber["nHitsPulled"])
    grouped = frame.groupby(["event", "pattern"])
    total = grouped["nHitsPulled"].sum()
    out = pd.DataFrame({
        "meanSqPull": (grouped["weighted"].sum() / total.where(total > 0)),
        "nHitsNoSegment": grouped["nHitsNoSegment"].sum().astype(int),
    })
    return out.reset_index()


def derive(data: dict[str, pd.DataFrame], station_thr: float,
           bending_thr: float):
    """Add the fractions and the match flags to the pattern and muon tables.

    A muon is in the efficiency when it passes gpfval.truth_selection. A pattern
    is a match when it crosses more than `station_thr` of the muon's stations and
    holds more than `bending_thr` of its bending hits, and the best match of a
    muon is the one that stands for it; the other matches are duplicates.
    """
    muons = data["muons"].copy()
    muons["selected"] = gpfval.truth_selection(muons).to_numpy()
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

    patterns = patterns.merge(data["pulls"], on=["event", "pattern"], how="left")

    # which muon a pattern belongs to, whether it matches it and whether it is the
    # one that stands for it. The index is reset first: the arrays are positional
    patterns = patterns.reset_index(drop=True)
    truth, quality = gpfval.pattern_quality(patterns, muons, station_thr, bending_thr)
    patterns["truthMuon"] = truth
    patterns["isMatch"] = quality
    patterns["isBest"] = gpfval.best_match(patterns, quality, truth)
    patterns["isDuplicate"] = patterns["isMatch"] & ~patterns["isBest"]

    best = patterns[patterns["isBest"]]
    muons = muons.merge(
        best[["event", "truthMuon", "pattern", "completeness", "purity",
              "mismatched", "selectivity", "meanSqPull", "eta", "phi"]]
        .rename(columns={"truthMuon": "muon", "eta": "patternEta",
                         "phi": "patternPhi"}),
        on=["event", "muon"], how="left")
    muons["found"] = muons["pattern"].notna()

    muons["dEta"] = muons["patternEta"] - muons["eta"]
    muons["dPhi"] = (muons["patternPhi"] - muons["phi"] + np.pi) % (2 * np.pi) - np.pi

    counts = (patterns[patterns["isDuplicate"]]
              .groupby(["event", "truthMuon"]).size().rename("nDuplicates")
              .reset_index().rename(columns={"truthMuon": "muon"}))
    muons = muons.merge(counts, on=["event", "muon"], how="left")
    muons["nDuplicates"] = muons["nDuplicates"].fillna(0).astype(int)
    return patterns, muons


def metrics(patterns: pd.DataFrame, muons: pd.DataFrame) -> dict:
    events = int(patterns["event"].nunique()) if len(patterns) else 0
    selected = muons[muons["selected"]]
    found = selected[selected["found"]]
    matched = patterns[patterns["isMatch"]]
    unmatched = patterns[~patterns["isMatch"]]
    # a pattern that is not the best match of a muon is a fake, duplicates
    # included. MuonFastRecoValidation averages the fraction per event, over the
    # events that have a pattern and a truth muon
    fake = ~(patterns["isMatch"] & patterns["isBest"])
    fake_per_event = fake.groupby(patterns["event"]).mean()
    fake_per_event = fake_per_event[fake_per_event.index.isin(muons["event"])]

    out = {
        # Number of events that contain at least one pattern.
        "events": events,
        # Number of truth muons that pass the selection of the efficiency.
        "truth_muons": len(selected),
        # Number of truth muons in the sample, selected or not.
        "truth_muons_all": len(muons),
        # Number of patterns the pattern finder produced.
        "patterns": len(patterns),

        # 1. Efficiency
        # Fraction of the selected truth muons that have a matching pattern.
        # 1 means every muon was found.
        "efficiency": len(found) / len(selected) if len(selected) else 0.0,
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
        # Fake rate as MuonFastRecoValidation reports it: the fraction of the
        # patterns of an event that are not the best match of a muon, averaged
        # over the events. Duplicates count as fakes. 0 is ideal.
        "fake_rate": float(fake_per_event.mean()) if len(fake_per_event) else np.nan,
        # The same fraction over all patterns at once.
        "fake_fraction": float(fake.mean()) if len(fake) else 0.0,
        # Average number of patterns per event.
        "patterns_per_event": len(patterns) / events if events else 0.0,
        # Average number of patterns per event that matched no truth muon.
        # 0 is ideal.
        "unmatched_per_event": len(unmatched) / events if events else 0.0,
        # Fraction of all patterns that matched no truth muon. 0 is ideal.
        "unmatched_fraction": len(unmatched) / len(patterns) if len(patterns) else 0.0,
        # Average number of duplicates per found muon. 0 is ideal.
        "duplicates_per_found_muon": (float(found["nDuplicates"].sum() / len(found))
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
    p.add_argument("--station-eff-thr", type=float, default=gpfval.STATION_EFF_THR,
                   help="A match crosses more than this fraction of the muon's stations")
    p.add_argument("--bending-eff-thr", type=float, default=gpfval.BENDING_EFF_THR,
                   help="A match holds more than this fraction of the muon's bending hits")
    p.add_argument("--output", type=Path, help="Csv the summary row is appended to")
    p.add_argument("--scan", action="store_true",
                   help="Print the metrics against the two thresholds, set equal")
    args = p.parse_args()

    data = load(args.tables)

    if args.scan:
        print(f"{'threshold':>15}{'efficiency':>12}{'fake rate':>11}"
              f"{'duplicates':>12}")
        for value in np.arange(0.1, 1.01, 0.1):
            row = metrics(*derive(data, value, value))
            print(f"{value:>15.1f}{row['efficiency']:>12.4f}"
                  f"{row['fake_rate']:>11.4f}"
                  f"{row['duplicates_per_found_muon']:>12.3f}")
        print()

    patterns, muons = derive(data, args.station_eff_thr, args.bending_eff_thr)
    patterns.to_parquet(args.tables / "pattern_flags.parquet", index=False)
    muons.to_parquet(args.tables / "muon_flags.parquet", index=False)

    summary = {
        "sample": args.sample or args.tables.name,
        "implementation": args.implementation,
        "station_eff_thr": args.station_eff_thr,
        "bending_eff_thr": args.bending_eff_thr,
        **metrics(patterns, muons),
    }
    width = max(len(key) for key in summary)
    for key, value in summary.items():
        print(f"{key:<{width}}  {value}")

    if args.output:
        pd.DataFrame([summary]).to_csv(
            args.output, mode="a", header=not args.output.exists(), index=False)
        print(f"\n{args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
