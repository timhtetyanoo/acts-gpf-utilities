#!/usr/bin/env python3
"""Write the validation tables out in the n-tuple format of MuonFastRecoValidation.

The plotting package at gitlab.cern.ch/atlas-muon-software/houghidipuffvalidation
reads a tree called `MuonFastRecoTest` whose branches are declared in
MuonFastRecoValidTuple.h on the `LeonardoDev` branch. That tree is what Athena's
MuonFastRecoTester writes, so producing it here lets the same executables plot
the patterns the ACTS example found, with no change to either repository.

Only counts are written. Every threshold stays on the reading side, in
MuonFastRecoValidTupleHelpers: `pat_truthMatched` lists every muon sharing a hit,
most-shared first, and their `effQuality` decides what counts as found.
compute_metrics.py applies the same definitions (gpfval.truth_selection,
pattern_quality, best_match), so its efficiency and fake rate are the numbers the
plotting package shows for this tuple.

Three groups of branches cannot be filled from the export and are written as
zeros, which leaves the plots that use them empty and breaks nothing:

    pat_NPileup*    needs the xAOD::MuonSimHit behind a measurement, which
                    decides pileup in MuonFastRecoTester::isTruthMatched. The
                    export carries no link from a space point to a truth
                    particle, so a pileup muon's hit cannot be told from cavern
                    background or from a hit whose segment was not reconstructed
    runNumber,      not in the export. Read only in a debug printout,
    lbNumber,       FastRecoValidation.cxx:566
    bcid
    mcChannelNumber not in the export, unused by the plots
    mcEventWeight
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import gpfval

#: The tree MuonFastRecoValidTupleHelpers::intree names
TREE = "MuonFastRecoTest"

#: The export stores the transverse momentum in GeV, the tuple in MeV: its
#: selections read `gen_Pt() * 1.e-3` and compare against a threshold in GeV
PT_TO_MEV = 1.0e3

#: Widest value a UChar_t branch holds. Athena's own writer uses
#: MatrixBranch<unsigned char> for these, so it wraps where this saturates
UCHAR_MAX = 255

#: table column -> branch name, for the three populations counted per station
COUNTS = {
    "pat_NPrecMeas": "nPrecMeas",
    "pat_NNonPrecMeas": "nNonPrecMeas",
    "pat_NPhiMeas": "nPhiMeas",
    "pat_NTruthPrecMeas": "nTruthPrecMeas",
    "pat_NTruthNonPrecMeas": "nTruthNonPrecMeas",
    "pat_NTruthPhiMeas": "nTruthPhiMeas",
    "pat_NAllPrecMeas": "nAllPrecMeas",
    "pat_NAllNonPrecMeas": "nAllNonPrecMeas",
    "pat_NAllPhiMeas": "nAllPhiMeas",
}
GEN_COUNTS = {
    "gen_NPrecMeas": "genPrecMeas",
    "gen_NNonPrecMeas": "genNonPrecMeas",
    "gen_NPhiMeas": "genPhiMeas",
}


class Saturation:
    """Counts how much had to be thrown away to fit the branches' UChar_t."""

    def __init__(self):
        self.clipped = 0
        self.largest = 0

    def narrow(self, rows):
        """One branch's values, as a list of per-station lists of UChar_t."""
        out = []
        for row in rows:
            values = np.asarray(row, dtype=np.int64)
            over = values > UCHAR_MAX
            if over.any():
                self.clipped += int(over.sum())
                self.largest = max(self.largest, int(values.max()))
            out.append(np.minimum(values, UCHAR_MAX).astype(np.uint8).tolist())
        return out


def build(muons: pd.DataFrame, patterns: pd.DataFrame, saturation: Saturation):
    """Group the two tables by event and return python-native branch columns.

    Returns lists (and numpy scalars) that map onto the TTree branches Athena
    declares: `vector<T>` and `vector<vector<UChar_t>>`. uproot cannot write the
    doubly nested ones as a classic TTree (only as RNTuple), which
    NtupleAnalysisUtils cannot read, so the write step uses PyROOT instead.
    """
    # every event of the pattern file takes part, including the ones where no
    # pattern was found: those events hold truth muons that were missed, which
    # is the denominator of the efficiency
    events = sorted(set(muons["event"]) | set(patterns["event"]))
    by_muon = {event: frame for event, frame in muons.groupby("event")}
    by_pattern = {event: frame for event, frame in patterns.groupby("event")}

    empty_muons = muons.iloc[:0]
    empty_patterns = patterns.iloc[:0]
    gen = {name: [] for name in ("gen_Pt", "gen_Eta", "gen_Phi", "gen_Q")}
    gen_counts = {name: [] for name in GEN_COUNTS}
    pat = {name: [] for name in ("pat_Eta", "pat_Phi", "pat_meanNormResidual2",
                                 "pat_NStations", "pat_Sector1", "pat_Sector2",
                                 "pat_Side", "pat_truthMatched")}
    pat_counts = {name: [] for name in COUNTS}
    n_patterns = []

    for event in events:
        m = by_muon.get(event, empty_muons)
        p = by_pattern.get(event, empty_patterns)

        gen["gen_Pt"].append((m["pt"] * PT_TO_MEV).astype(np.float32).tolist())
        gen["gen_Eta"].append(m["eta"].astype(np.float32).tolist())
        gen["gen_Phi"].append(m["phi"].astype(np.float32).tolist())
        gen["gen_Q"].append(m["q"].astype(np.int16).tolist())
        for branch, column in GEN_COUNTS.items():
            gen_counts[branch].append(list(m[column]))

        sectors = [gpfval.expanded_sector_pair(s) for s in p["sector"]]
        pat["pat_Eta"].append(p["eta"].astype(np.float32).tolist())
        pat["pat_Phi"].append(p["phi"].astype(np.float32).tolist())
        pat["pat_meanNormResidual2"].append(
            p["meanNormResidual2"].astype(np.float32).tolist())
        pat["pat_NStations"].append(p["nStations"].astype(np.uint8).tolist())
        pat["pat_Sector1"].append([int(main) for main, _ in sectors])
        pat["pat_Sector2"].append([int(adjacent) for _, adjacent in sectors])
        pat["pat_Side"].append(p["side"].astype(np.int16).tolist())
        pat["pat_truthMatched"].append(
            [[int(x) for x in v] for v in p["matchedMuons"]])
        for branch, column in COUNTS.items():
            pat_counts[branch].append(list(p[column]))
        n_patterns.append(len(p))

    branches = {
        "eventNumber": [int(e) for e in events],
        "pat_nPatterns": [int(n) for n in n_patterns],
        **gen,
        **pat,
    }
    for branch, rows in {**gen_counts, **pat_counts}.items():
        branches[branch] = saturation.narrow(rows)
    # nothing in the export distinguishes a pileup muon's hit, see the module
    # doc string; the zeros keep isFromPileupMuon() false and the plots empty
    for branch in ("pat_NPileupPrecMeas", "pat_NPileupNonPrecMeas",
                   "pat_NPileupPhiMeas"):
        branches[branch] = [[[0] * gpfval.N_STATIONS] * n for n in n_patterns]
    # the reconstructed muons built from the patterns downstream; the finder
    # stops at the patterns, so there are none. The branches exist and are empty,
    # which MuonFastRecoValidation needs (it stops on a missing branch) and which
    # leaves its muon plots, the resolutions and the charge, empty.
    for branch in ("muon_Eta", "muon_Phi", "muon_Pt", "muon_Q", "muon_patMatched"):
        branches[branch] = [[] for _ in n_patterns]
    # absent from the export, written so the branches exist
    n_events = len(events)
    for branch in ("runNumber", "lbNumber", "bcid", "mcChannelNumber"):
        branches[branch] = [0] * n_events
    branches["mcEventWeight"] = [1.0] * n_events
    return branches


def write_ttree(path: Path, branches: dict) -> None:
    """Write a classic TTree with vector / vector<vector> branches via PyROOT."""
    import ROOT  # local: LCG / Athena env provides it

    def fill_vector(vec, values):
        vec.clear()
        for value in values:
            vec.push_back(value)

    def fill_matrix(mat, rows):
        mat.clear()
        for row in rows:
            inner = ROOT.std.vector["unsigned char"]()
            for value in row:
                inner.push_back(int(value))
            mat.push_back(inner)

    path.parent.mkdir(parents=True, exist_ok=True)
    file = ROOT.TFile.Open(str(path), "RECREATE")
    if not file or file.IsZombie():
        raise RuntimeError(f"Cannot create {path}")
    tree = ROOT.TTree(TREE, TREE)

    scalars = {
        "eventNumber": np.array([0], dtype=np.uint64),
        "pat_nPatterns": np.array([0], dtype=np.uint32),
        "runNumber": np.array([0], dtype=np.uint32),
        "lbNumber": np.array([0], dtype=np.uint32),
        "bcid": np.array([0], dtype=np.uint32),
        "mcChannelNumber": np.array([0], dtype=np.uint32),
        "mcEventWeight": np.array([0.0], dtype=np.float64),
    }
    tree.Branch("eventNumber", scalars["eventNumber"], "eventNumber/l")
    tree.Branch("pat_nPatterns", scalars["pat_nPatterns"], "pat_nPatterns/i")
    tree.Branch("runNumber", scalars["runNumber"], "runNumber/i")
    tree.Branch("lbNumber", scalars["lbNumber"], "lbNumber/i")
    tree.Branch("bcid", scalars["bcid"], "bcid/i")
    tree.Branch("mcChannelNumber", scalars["mcChannelNumber"], "mcChannelNumber/i")
    tree.Branch("mcEventWeight", scalars["mcEventWeight"], "mcEventWeight/D")

    vectors = {
        "gen_Pt": ROOT.std.vector["float"](),
        "gen_Eta": ROOT.std.vector["float"](),
        "gen_Phi": ROOT.std.vector["float"](),
        "gen_Q": ROOT.std.vector["short"](),
        "pat_Eta": ROOT.std.vector["float"](),
        "pat_Phi": ROOT.std.vector["float"](),
        "pat_meanNormResidual2": ROOT.std.vector["float"](),
        "pat_NStations": ROOT.std.vector["unsigned char"](),
        "pat_Sector1": ROOT.std.vector["unsigned short"](),
        "pat_Sector2": ROOT.std.vector["unsigned short"](),
        "pat_Side": ROOT.std.vector["short"](),
        "muon_Eta": ROOT.std.vector["float"](),
        "muon_Phi": ROOT.std.vector["float"](),
        "muon_Pt": ROOT.std.vector["float"](),
        "muon_Q": ROOT.std.vector["short"](),
        "muon_patMatched": ROOT.std.vector["unsigned char"](),
    }
    for name, vec in vectors.items():
        tree.Branch(name, vec)

    matrices = {
        name: ROOT.std.vector[ROOT.std.vector["unsigned char"]]()
        for name in (
            *GEN_COUNTS,
            *COUNTS,
            "pat_truthMatched",
            "pat_NPileupPrecMeas",
            "pat_NPileupNonPrecMeas",
            "pat_NPileupPhiMeas",
        )
    }
    for name, mat in matrices.items():
        tree.Branch(name, mat)

    n_events = len(branches["eventNumber"])
    for i in range(n_events):
        scalars["eventNumber"][0] = branches["eventNumber"][i]
        scalars["pat_nPatterns"][0] = branches["pat_nPatterns"][i]
        scalars["runNumber"][0] = branches["runNumber"][i]
        scalars["lbNumber"][0] = branches["lbNumber"][i]
        scalars["bcid"][0] = branches["bcid"][i]
        scalars["mcChannelNumber"][0] = branches["mcChannelNumber"][i]
        scalars["mcEventWeight"][0] = branches["mcEventWeight"][i]
        for name, vec in vectors.items():
            fill_vector(vec, branches[name][i])
        for name, mat in matrices.items():
            fill_matrix(mat, branches[name][i])
        tree.Fill()

    tree.Write()
    file.Close()


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tables", type=Path, help="Directory from build_validation_tables.py")
    p.add_argument("output", type=Path, help="ROOT file to write")
    args = p.parse_args()

    muons = pd.read_parquet(args.tables / "muons.parquet")
    patterns = pd.read_parquet(args.tables / "patterns.parquet")

    saturation = Saturation()
    branches = build(muons, patterns, saturation)
    write_ttree(args.output, branches)

    print(f"Wrote {len(branches['eventNumber'])} events, "
          f"{sum(branches['pat_nPatterns'])} patterns and "
          f"{len(muons)} truth muons to {args.output}:{TREE}")
    if saturation.clipped:
        print(f"Saturated {saturation.clipped} station counts at {UCHAR_MAX}, "
              f"the largest was {saturation.largest}. The branches are UChar_t "
              f"and a bucket holds more hits than that; Athena's own writer "
              f"wraps here instead.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
