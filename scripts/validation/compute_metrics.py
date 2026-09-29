#!/usr/bin/env python3
"""Turn the validation tables into the performance numbers.

Everything the pattern finder produced is already in the tables written by
build_validation_tables.py; this script only applies a definition to them.
MuonFastRecoTester stops before this point on purpose, so the definition used
here is ours and is stated explicitly:

    a pattern belongs to the muon that owns the most of its hits, the majority
    rule of fillGlobPatternInfo(). The pattern counts as a match of that muon
    when it collected at least `--min-completeness` of the muon's findable
    precision hits and has hits of the muon in at least `--min-stations`
    stations. The second requirement mirrors the `minGroups` of the finder: a
    pattern that lives in a single station is not a muon candidate.

    efficiency   muons with at least one matching pattern
    duplicates   matching patterns beyond the first, per muon
    fakes        patterns that match no muon
    purity       hits of the main muon over all hits, per pattern
    completeness precision hits of the main muon over its findable ones

`--scan` prints the efficiency and the fake fraction over a range of
completeness thresholds, so the effect of the choice is visible.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def load(tables: Path) -> dict[str, pd.DataFrame]:
    names = ["muons", "muon_station", "segments",
             "patterns", "pattern_station", "matches"]
    return {name: pd.read_parquet(tables / f"{name}.parquet") for name in names}


def summarise(data: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reduce the per station tables to one row per pattern and per muon."""
    station = data["pattern_station"]
    per_pattern = station.groupby(["event", "pattern"]).agg(
        nPrec=("nPrec", "sum"), nTrig=("nTrig", "sum"), nPhi=("nPhi", "sum"),
        nTruthPrec=("nTruthPrec", "sum"), nTruthTrig=("nTruthTrig", "sum"),
        nTruthPhi=("nTruthPhi", "sum"),
        nMisTruthPrec=("nMisTruthPrec", "sum"),
        nStationsWithTruth=("nTruthPrec", lambda c: int((c > 0).sum())),
    ).reset_index()

    patterns = data["patterns"].merge(per_pattern, on=["event", "pattern"], how="left")
    patterns["nHitCounts"] = patterns[["nPrec", "nTrig", "nPhi"]].sum(axis=1)
    patterns["nTruthCounts"] = patterns[
        ["nTruthPrec", "nTruthTrig", "nTruthPhi"]].sum(axis=1)
    patterns["purity"] = np.where(
        patterns["nHitCounts"] > 0,
        patterns["nTruthCounts"] / patterns["nHitCounts"].replace(0, np.nan), np.nan)

    findable = data["muon_station"].groupby(["event", "muon"]).agg(
        genPrec=("nPrec", "sum"), genTrig=("nTrig", "sum"), genPhi=("nPhi", "sum"),
        genStations=("nPrec", "size")).reset_index()
    muons = data["muons"].merge(findable, on=["event", "muon"], how="left")
    muons[["genPrec", "genTrig", "genPhi", "genStations"]] = muons[
        ["genPrec", "genTrig", "genPhi", "genStations"]].fillna(0).astype(int)

    patterns = patterns.merge(
        findable.rename(columns={"muon": "mainMuon"}),
        on=["event", "mainMuon"], how="left")
    patterns["completeness"] = np.where(
        patterns["genPrec"].fillna(0) > 0,
        patterns["nTruthPrec"] / patterns["genPrec"].replace(0, np.nan), np.nan)
    return patterns, muons


def classify(patterns: pd.DataFrame, muons: pd.DataFrame,
             min_completeness: float, min_stations: int):
    """Flag every pattern as matching or fake and every muon as found or not."""
    patterns = patterns.copy()
    patterns["isMatch"] = (
        (patterns["mainMuon"] >= 0)
        & (patterns["completeness"] >= min_completeness)
        & (patterns["nStationsWithTruth"] >= min_stations)
    )
    # the best pattern of a muon is the one holding the most of its hits; the
    # others are duplicates of the same muon
    matches = patterns[patterns["isMatch"]].sort_values(
        "nTruthPrec", ascending=False)
    best = matches.drop_duplicates(["event", "mainMuon"])
    patterns["isDuplicate"] = patterns["isMatch"] & ~patterns.index.isin(best.index)

    muons = muons.merge(
        best[["event", "mainMuon", "pattern", "completeness", "purity",
              "nTruthPrec", "dEtaMuon", "dPhiMuon", "dThetaSeg", "dPhiSeg"]]
        .rename(columns={"mainMuon": "muon"}),
        on=["event", "muon"], how="left")
    muons["found"] = muons["pattern"].notna()
    muons["nDuplicates"] = muons.merge(
        patterns[patterns["isDuplicate"]].groupby(["event", "mainMuon"]).size()
        .rename("n").reset_index().rename(columns={"mainMuon": "muon"}),
        on=["event", "muon"], how="left")["n"].fillna(0).astype(int)
    return patterns, muons


def metrics(patterns: pd.DataFrame, muons: pd.DataFrame) -> dict:
    n_events = int(patterns["event"].nunique()) if len(patterns) else 0
    n_muons = len(muons)
    n_patterns = len(patterns)
    found = muons[muons["found"]]
    return {
        "events": n_events,
        "truth_muons": n_muons,
        "patterns": n_patterns,
        "found_muons": int(len(found)),
        "efficiency": len(found) / n_muons if n_muons else 0.0,
        "fake_fraction": float((~patterns["isMatch"]).mean()) if n_patterns else 0.0,
        "fakes_per_event": float((~patterns["isMatch"]).sum() / n_events) if n_events else 0.0,
        "duplicates_per_muon": float(muons["nDuplicates"].sum() / n_muons) if n_muons else 0.0,
        "mean_completeness": float(found["completeness"].mean()) if len(found) else 0.0,
        "mean_purity": float(found["purity"].mean()) if len(found) else 0.0,
        "dEtaMuon_mean": float(found["dEtaMuon"].mean()) if len(found) else np.nan,
        "dEtaMuon_rms": float(found["dEtaMuon"].std()) if len(found) else np.nan,
        "dPhiMuon_mean": float(found["dPhiMuon"].mean()) if len(found) else np.nan,
        "dPhiMuon_rms": float(found["dPhiMuon"].std()) if len(found) else np.nan,
        "dThetaSeg_rms": float(found["dThetaSeg"].std()) if len(found) else np.nan,
        "dPhiSeg_rms": float(found["dPhiSeg"].std()) if len(found) else np.nan,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tables", type=Path, help="Directory of build_validation_tables.py")
    p.add_argument("--sample", default="", help="Label of the sample, e.g. PG0")
    p.add_argument("--implementation", default="", help="Label, e.g. cpu or cuda")
    p.add_argument("--min-completeness", type=float, default=0.5)
    p.add_argument("--min-stations", type=int, default=2)
    p.add_argument("--output", type=Path, help="Csv the summary row is appended to")
    p.add_argument("--scan", action="store_true",
                   help="Print efficiency & fakes against the completeness cut")
    args = p.parse_args()

    data = load(args.tables)
    patterns, muons = summarise(data)

    if args.scan:
        print(f"{'min completeness':>17}  {'efficiency':>10}  {'fakes/event':>11}  "
              f"{'duplicates/muon':>15}")
        for cut in np.arange(0.0, 1.01, 0.1):
            flagged, flagged_muons = classify(patterns, muons, cut, args.min_stations)
            row = metrics(flagged, flagged_muons)
            print(f"{cut:>17.1f}  {row['efficiency']:>10.4f}  "
                  f"{row['fakes_per_event']:>11.3f}  {row['duplicates_per_muon']:>15.3f}")
        print()

    patterns, muons = classify(patterns, muons,
                               args.min_completeness, args.min_stations)
    patterns.to_parquet(args.tables / "pattern_flags.parquet", index=False)
    muons.to_parquet(args.tables / "muon_flags.parquet", index=False)

    summary = {
        "sample": args.sample or args.tables.name,
        "implementation": args.implementation,
        "min_completeness": args.min_completeness,
        "min_stations": args.min_stations,
        **metrics(patterns, muons),
    }
    width = max(len(key) for key in summary)
    for key, value in summary.items():
        print(f"{key:<{width}}  {value}")

    if args.output:
        row = pd.DataFrame([summary])
        row.to_csv(args.output, mode="a", header=not args.output.exists(), index=False)
        print(f"\nAppended the summary to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
