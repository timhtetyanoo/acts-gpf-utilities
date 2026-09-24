#!/usr/bin/env python3
"""Turn the truth tree of an Athena-exported n-tuple into a compact table.

The scorer needs, per event and per truth muon, the set of geometry identifiers
the muon crossed. Extracting that from the truth tree is slow compared with the
scoring itself, so it is done once and stored as a parquet file:

    event, muon, station, geo_id

`station` is kept when the truth tree provides one; otherwise it is -1 and the
scoring runs without a station split.

The branch names differ between exports, hence they are detected from the file
and can be overridden on the command line. Run with --list to print what the
file actually contains.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import awkward as ak
import pandas as pd
import uproot

#: Candidate names, most likely first. Overridable on the command line.
TRUTH_TREES = ["MuonTruth", "MuonTruthSegments", "Truth"]
GEO_ID_BRANCHES = ["Segments_hitGeoIds", "Segments_geoIds", "segment_hitGeoIds"]
LINK_BRANCHES = ["Segments_truthLink", "Segments_muonLink", "segment_truthLink"]
STATION_BRANCHES = ["Segments_stationIndex", "Segments_station", "segment_station"]


def pick(available: list[str], candidates: list[str], what: str, required: bool):
    """Return the first candidate present in the file."""
    for candidate in candidates:
        if candidate in available:
            return candidate
    if not required:
        return None
    raise SystemExit(
        f"Could not find the {what} branch. Tried {candidates}.\n"
        f"Available: {sorted(available)}\n"
        f"Pass the correct name explicitly, see --help."
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ntuple", type=Path, help="Athena exported n-tuple")
    p.add_argument("output", type=Path, nargs="?", help="Parquet file to write")
    p.add_argument("--tree", help="Name of the truth tree")
    p.add_argument("--geo-ids", help="Branch holding the geometry ids per segment")
    p.add_argument("--link", help="Branch linking a segment to its truth muon")
    p.add_argument("--station", help="Branch holding the station of a segment")
    p.add_argument(
        "--list", action="store_true", help="Print the trees & branches and exit"
    )
    args = p.parse_args()

    file = uproot.open(args.ntuple)
    if args.list:
        for key in file.keys():
            print(key)
            obj = file[key]
            if hasattr(obj, "keys"):
                for branch in obj.keys():
                    print(f"    {branch}")
        return 0

    tree_name = args.tree or pick(
        [k.split(";")[0] for k in file.keys()], TRUTH_TREES, "truth tree", True
    )
    tree = file[tree_name]
    branches = tree.keys()

    geo_branch = args.geo_ids or pick(branches, GEO_ID_BRANCHES, "geometry id", True)
    link_branch = args.link or pick(branches, LINK_BRANCHES, "truth link", False)
    station_branch = args.station or pick(branches, STATION_BRANCHES, "station", False)

    wanted = [geo_branch] + [b for b in (link_branch, station_branch) if b]
    data = tree.arrays(wanted, library="ak")

    rows = []
    for event, entry in enumerate(data):
        geo_ids = entry[geo_branch]
        links = entry[link_branch] if link_branch else None
        stations = entry[station_branch] if station_branch else None
        for segment, ids in enumerate(geo_ids):
            muon = int(links[segment]) if links is not None else segment
            station = int(stations[segment]) if stations is not None else -1
            for geo_id in ak.to_list(ids):
                rows.append((event, muon, station, int(geo_id)))

    truth = pd.DataFrame(rows, columns=["event", "muon", "station", "geo_id"])
    output = args.output or args.ntuple.with_suffix(".truth.parquet")
    truth.to_parquet(output, index=False)

    print(
        f"Wrote {len(truth)} truth hits of {truth['muon'].nunique()} muons "
        f"in {truth['event'].nunique()} events to {output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
