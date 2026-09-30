"""Write the validation tables as a MuonFastRecoTest tree.

Branch layout: MuonFastRecoValidTuple.h, houghidipuffvalidation, branch
LeonardoDev. Counts only; the matching thresholds are applied on the reading
side by MuonFastRecoValidTupleHelpers.

Not filled:

    pat_NPileup*                   no space point to truth particle link in the
                                   export, so a pileup hit cannot be separated
                                   from an unassociated one
    runNumber, lbNumber, bcid      absent from the export
    mcChannelNumber, mcEventWeight absent from the export

Transverse momentum is converted from GeV to MeV.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import awkward as ak
import numpy as np
import pandas as pd
import uproot

import gpfval

#: The tree MuonFastRecoValidTupleHelpers::intree names
TREE = "MuonFastRecoTest"

#: The export stores the transverse momentum in GeV, the tuple in MeV
PT_TO_MEV = 1.0e3

#: Widest value a UChar_t branch holds
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
    """Counts the values that did not fit a UChar_t branch."""

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


def jagged(values, dtype):
    """A branch of one vector per event, from a list of per-event sequences."""
    return ak.values_astype(ak.Array([list(v) for v in values]), dtype)


def build(muons: pd.DataFrame, patterns: pd.DataFrame, saturation: Saturation):
    """Group the two tables by event and return the branches of the tree."""
    # events without a pattern carry the muons that were missed
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

        gen["gen_Pt"].append((m["pt"] * PT_TO_MEV).tolist())
        gen["gen_Eta"].append(m["eta"].tolist())
        gen["gen_Phi"].append(m["phi"].tolist())
        gen["gen_Q"].append(m["q"].tolist())
        for branch, column in GEN_COUNTS.items():
            gen_counts[branch].append(list(m[column]))

        sectors = [gpfval.expanded_sector_pair(s) for s in p["sector"]]
        pat["pat_Eta"].append(p["eta"].tolist())
        pat["pat_Phi"].append(p["phi"].tolist())
        pat["pat_meanNormResidual2"].append(p["meanNormResidual2"].tolist())
        pat["pat_NStations"].append(p["nStations"].tolist())
        pat["pat_Sector1"].append([main for main, _ in sectors])
        pat["pat_Sector2"].append([adjacent for _, adjacent in sectors])
        pat["pat_Side"].append(p["side"].tolist())
        pat["pat_truthMatched"].append([list(v) for v in p["matchedMuons"]])
        for branch, column in COUNTS.items():
            pat_counts[branch].append(list(p[column]))
        n_patterns.append(len(p))

    branches = {
        "eventNumber": np.asarray(events, dtype=np.uint64),
        "pat_nPatterns": np.asarray(n_patterns, dtype=np.uint32),
        "gen_Pt": jagged(gen["gen_Pt"], np.float32),
        "gen_Eta": jagged(gen["gen_Eta"], np.float32),
        "gen_Phi": jagged(gen["gen_Phi"], np.float32),
        "gen_Q": jagged(gen["gen_Q"], np.int16),
        "pat_Eta": jagged(pat["pat_Eta"], np.float32),
        "pat_Phi": jagged(pat["pat_Phi"], np.float32),
        "pat_meanNormResidual2": jagged(pat["pat_meanNormResidual2"], np.float32),
        "pat_NStations": jagged(pat["pat_NStations"], np.uint8),
        "pat_Sector1": jagged(pat["pat_Sector1"], np.uint16),
        "pat_Sector2": jagged(pat["pat_Sector2"], np.uint16),
        "pat_Side": jagged(pat["pat_Side"], np.int16),
        "pat_truthMatched": jagged(pat["pat_truthMatched"], np.uint8),
    }
    for branch, rows in {**gen_counts, **pat_counts}.items():
        branches[branch] = jagged(saturation.narrow(rows), np.uint8)
    for branch in ("pat_NPileupPrecMeas", "pat_NPileupNonPrecMeas",
                   "pat_NPileupPhiMeas"):
        branches[branch] = jagged(
            [[[0] * gpfval.N_STATIONS] * n for n in n_patterns], np.uint8)
    n_events = len(events)
    for branch, dtype in (("runNumber", np.uint32), ("lbNumber", np.uint32),
                          ("bcid", np.uint32), ("mcChannelNumber", np.uint32)):
        branches[branch] = np.zeros(n_events, dtype=dtype)
    branches["mcEventWeight"] = np.ones(n_events, dtype=np.float64)
    return branches


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

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with uproot.recreate(args.output) as file:
        file[TREE] = branches

    if saturation.clipped:
        print(f"warning: {saturation.clipped} station counts saturated at "
              f"{UCHAR_MAX}, maximum {saturation.largest}", file=sys.stderr)
    print(f"{args.output}:{TREE}  "
          f"{len(branches['eventNumber'])} events, "
          f"{int(branches['pat_nPatterns'].sum())} patterns, "
          f"{len(muons)} truth muons")
    return 0


if __name__ == "__main__":
    sys.exit(main())
