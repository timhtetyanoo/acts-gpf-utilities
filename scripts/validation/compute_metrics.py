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


#: Names of the columns of scores.csv. Each says what is counted and over what,
#: so the file reads without this script
EFFICIENCY = "efficiency (found / selected muons)"
FAKE_RATE = "fake rate (event average; duplicates count as fakes)"
DUPLICATES = "duplicates per found muon"


def metrics(patterns: pd.DataFrame, muons: pd.DataFrame,
            events_read: int) -> dict:
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

    def mean(frame, column):
        return float(frame[column].mean()) if len(frame) else np.nan

    return {
        "events read": events_read,
        "events with patterns": int(patterns["event"].nunique()),
        "truth muons in the events": len(muons),
        # the muons that pass gpfval.truth_selection, the efficiency's denominator
        "truth muons selected for the efficiency": len(selected),
        "selected muons found": len(found),
        "patterns (all events)": len(patterns),

        # 1. Efficiency: 1 means every selected muon was found
        EFFICIENCY: len(found) / len(selected) if len(selected) else 0.0,

        # 4. Fakes and duplicates: 0 is ideal
        DUPLICATES: (float(found["nDuplicates"].sum() / len(found))
                     if len(found) else 0.0),
        # as MuonFastRecoValidation reports it: the fraction of an event's
        # patterns that are not the best match of a muon, averaged over the
        # events with a pattern and a truth muon
        FAKE_RATE: (float(fake_per_event.mean()) if len(fake_per_event)
                    else np.nan),
        "fake fraction (all patterns; duplicates count as fakes)":
            float(fake.mean()) if len(fake) else 0.0,
        "patterns matching no muon (fraction of all patterns)":
            len(unmatched) / len(patterns) if len(patterns) else 0.0,
        "patterns per event read":
            len(patterns) / events_read if events_read else 0.0,
        "patterns matching no muon per event read":
            len(unmatched) / events_read if events_read else 0.0,

        # 1 and 2. What the patterns hold
        # fraction of the muon's hit surfaces that its pattern contains; 1 is ideal
        "completeness of found muons (mean)": mean(found, "completeness"),
        # fraction of a matched pattern's hits that belong to its muon; 1 is ideal
        "purity of matched patterns (mean)": mean(matched, "purity"),
        # fraction of a matched pattern's hits from another truth muon; 0 is ideal
        "hits from another muon in matched patterns (mean fraction)":
            mean(matched, "mismatched"),
        # hits a matched pattern took over the hits of the buckets it drew from
        "hits taken of those in the pattern's buckets (mean fraction)":
            mean(matched, "selectivity"),

        # 3. Hits on the path: about 1 is ideal
        "mean squared pull of matched patterns about the truth line (median)":
            (float(matched["meanSqPull"].median()) if len(matched) else np.nan),

        # 5. Direction of the found muons' patterns
        "eta of pattern minus truth (mean)": mean(found, "dEta"),
        "eta of pattern minus truth (std)":
            float(found["dEta"].std()) if len(found) else np.nan,
        "phi of pattern minus truth (mean; rad)": mean(found, "dPhi"),
        "phi of pattern minus truth (std; rad)":
            float(found["dPhi"].std()) if len(found) else np.nan,
    }


def events_in(pattern_file: Path, tree: str) -> int:
    """The events the finder ran over: the pattern file has one entry per event,
    with or without patterns"""
    import uproot
    return int(uproot.open(pattern_file)[tree].num_entries)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tables", type=Path, help="Directory of build_validation_tables.py")
    p.add_argument("--patterns", type=Path, required=True,
                   help="Pattern file the tables were built from, for the "
                        "number of events read")
    p.add_argument("--pattern-tree", default="muonGlobalPatterns")
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
    events_read = events_in(args.patterns, args.pattern_tree)

    if args.scan:
        print("Both match thresholds set to the same value:")
        print(f"{'threshold':>15}{'efficiency':>12}{'fake rate':>11}"
              f"{'duplicates per found muon':>27}")
        for value in np.arange(0.1, 1.01, 0.1):
            row = metrics(*derive(data, value, value), events_read)
            print(f"{value:>15.1f}{row[EFFICIENCY]:>12.4f}"
                  f"{row[FAKE_RATE]:>11.4f}"
                  f"{row[DUPLICATES]:>27.3f}")
        print()

    patterns, muons = derive(data, args.station_eff_thr, args.bending_eff_thr)
    patterns.to_parquet(args.tables / "pattern_flags.parquet", index=False)
    muons.to_parquet(args.tables / "muon_flags.parquet", index=False)

    summary = {
        "sample": args.sample or args.tables.name,
        "run": args.implementation,
        "match needs more than this fraction of the muon's stations":
            args.station_eff_thr,
        "match needs more than this fraction of the muon's bending hits":
            args.bending_eff_thr,
        **metrics(patterns, muons, events_read),
    }
    width = max(len(key) for key in summary)
    for key, value in summary.items():
        print(f"{key:<{width}}  {value}")

    # four significant digits: enough to tell two runs apart, short to read
    summary = {key: (float(f"{value:.4g}") if isinstance(value, float) else value)
               for key, value in summary.items()}
    if args.output:
        pd.DataFrame([summary]).to_csv(
            args.output, mode="a", header=not args.output.exists(), index=False)
        print(f"\n{args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
