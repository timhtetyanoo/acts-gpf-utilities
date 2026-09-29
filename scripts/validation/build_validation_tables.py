#!/usr/bin/env python3
"""Join the found patterns with the truth and write the validation tables.

This is the counterpart of Athena's MuonFastRecoTester: it only produces
numbers, it does not decide what is efficient. Every threshold and every
definition of "the pattern found the muon" lives in compute_metrics.py, so a
definition can be changed without running the pattern finder again.

The one difference to the Athena tester is unavoidable. MuonFastRecoTester
associates a measurement with a truth particle through the sim hit behind it
(getTruthMatchedHit), a link the exported n-tuple does not carry. Here a hit
belongs to a muon when its geometry identifier is one of the identifiers of the
muon's truth segments, `Segments_hitGeoIds`, which the exporter fills with the
surfaces of exactly those sim hits (TruthSegmentWriter.cxx). The consequence is
that a wrong hit on a right surface counts as matched here and never does in
Athena: an MDT identifier is a tube, a strip identifier is a gas gap.

Written tables, all parquet, one directory:

    muons           event, muon, pt, eta, phi, q, ...
    muon_station    event, muon, station, nPrec, nTrig, nPhi     (the truth)
    segments        event, muon, segment, station, position, direction
    truth_hits      event, muon, segment, geo_id, was it findable, was it taken
    patterns        event, pattern, theta, phi, ..., main muon, residuals
    pattern_station event, pattern, station, counts by category
    matches         event, pattern, muon, station, shared identifiers
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import awkward as ak
import numpy as np
import pandas as pd
import uproot

import gpfval
from gpfval import PHI, PREC, TRIG

#: Number of stations, Muon::MuonStationIndex::StIndex
N_STATIONS = len(gpfval.STATIONS)

SP_BRANCHES = [
    "event_id",
    "spacePoint_geometryId",
    "spacePoint_muonId",
    "spacePoint_bucketId",
]
TRUTH_BRANCHES = [
    "event_id",
    "Muons_pt", "Muons_eta", "Muons_phi", "Muons_q",
    "Muons_truthOrigin", "Muons_truthType", "Muons_nTruthSegments",
    "Segments_truthLink", "Segments_chamberIdx", "Segments_sector",
    "Segments_etaIndex", "Segments_posX", "Segments_posY", "Segments_posZ",
    "Segments_dirTheta", "Segments_dirPhi", "Segments_hitGeoIds",
    "Segments_nPrecHits", "Segments_nTrigEtaLayers", "Segments_nTrigPhiLayers",
    "Segments_chi2", "Segments_nDoF",
]
PATTERN_BRANCHES = [
    "event_id",
    "pattern_sector", "pattern_theta", "pattern_phi",
    "pattern_nPrecisionLayers", "pattern_nTriggerLayers", "pattern_nPhiLayers",
    "pattern_meanNormResidual2", "pattern_nHits",
    "hit_patternIdx", "hit_station", "hit_geometryId", "hit_muonId",
    "hit_bucketId", "hit_indexInBucket",
]


def read_selected(tree, branches, wanted_ids, step="200 MB"):
    """Return the entries of a tree whose event_id is in `wanted_ids`."""
    kept = []
    for chunk in tree.iterate(branches, step_size=step, library="ak"):
        mask = np.isin(ak.to_numpy(chunk["event_id"]), list(wanted_ids))
        if mask.any():
            kept.append(chunk[mask])
        if sum(len(part) for part in kept) == len(wanted_ids):
            break
    if not kept:
        raise SystemExit("None of the events of the pattern file are in the n-tuple")
    return ak.concatenate(kept)


def truth_hits_per_muon(truth_event):
    """Geometry identifiers of every truth muon of the event.

    The identifiers of a muon are the union over its truth segments, which
    `Segments_truthLink` assigns to the muon.
    """
    per_muon = defaultdict(set)
    links = ak.to_numpy(truth_event["Segments_truthLink"])
    geo_ids = truth_event["Segments_hitGeoIds"]
    for segment, muon in enumerate(links):
        per_muon[int(muon)].update(int(v) for v in ak.to_list(geo_ids[segment]))
    return per_muon


def truth_counts(space_points, per_muon):
    """Count the findable hits of every truth muon, per station and category.

    This is our fillTruthInfo(). Athena counts the truth hits from the space
    points and not from the segments, "because we have sim hits that haven't
    made it into spacepoints due to inefficiencies" (MuonFastRecoTester.cxx),
    and deduplicates them: one hit per layer of a sector, with the straws of the
    MDTs exempt because a layer legitimately holds several of them. Both are
    reproduced here, the layer being `detLayer`, which the exporter fills with
    sectorLayerNum(), the quantity Athena deduplicates on.

    Athena additionally demands, for a space point measuring both coordinates,
    that the second measurement carries the same truth link before it counts as
    a phi hit. The export has one identifier for the whole space point, so that
    condition cannot be tested and a matched two dimensional hit counts for both
    coordinates.
    """
    rows = []
    for muon, muon_ids in per_muon.items():
        mine = np.isin(space_points["geo_id"], list(muon_ids))
        if not mine.any():
            continue
        counts = np.zeros((N_STATIONS, 3), dtype=int)
        seen_eta: set[tuple] = set()
        seen_phi: set[tuple] = set()
        index = np.flatnonzero(mine)
        # precision hits first, so that they claim a layer they share with a
        # trigger hit before it does, as the type loop of fillTruthInfo() does
        order = index[np.argsort(space_points["type"][index], kind="stable")]
        for hit in order:
            station = space_points["station"][hit]
            if station < 0:
                continue
            layer = (station, space_points["sector"][hit],
                     space_points["side"][hit], space_points["detLayer"][hit])
            if space_points["measuresEta"][hit]:
                if layer in seen_eta and not space_points["isStraw"][hit]:
                    continue
                seen_eta.add(layer)
                counts[station, PREC if space_points["isPrec"][hit] else TRIG] += 1
                if space_points["measuresPhi"][hit]:
                    seen_phi.add(layer)
                    counts[station, PHI] += 1
            else:
                if layer in seen_phi:
                    continue
                seen_phi.add(layer)
                counts[station, PHI] += 1
        for station in range(N_STATIONS):
            if counts[station].any():
                rows.append({
                    "muon": muon, "station": station,
                    "nPrec": int(counts[station, PREC]),
                    "nTrig": int(counts[station, TRIG]),
                    "nPhi": int(counts[station, PHI]),
                })
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("patterns", type=Path, help="Pattern file written by the example")
    p.add_argument("ntuple", type=Path, help="Athena exported n-tuple")
    p.add_argument("output", type=Path, help="Directory the tables are written to")
    p.add_argument("--pattern-tree", default="muonGlobalPatterns")
    p.add_argument("--max-events", type=int, default=0, help="0 reads all of them")
    args = p.parse_args()

    patterns = uproot.open(args.patterns)[args.pattern_tree].arrays(
        PATTERN_BRANCHES, library="ak")
    if args.max_events:
        patterns = patterns[: args.max_events]
    event_numbers = ak.to_numpy(patterns["event_id"]).astype(int)

    ntuple = uproot.open(args.ntuple)
    # the pattern file records the reader's event number, the n-tuple the
    # original event_id, so the two have to be brought onto the same key
    id_of_number = {number: event_id for event_id, number
                    in gpfval.reader_event_numbers(ntuple).items()}
    missing = [n for n in event_numbers if n not in id_of_number]
    if missing:
        raise SystemExit(f"{len(missing)} events of the pattern file are unknown "
                         f"to the n-tuple, first one {missing[0]}")
    wanted_ids = {id_of_number[n] for n in event_numbers}

    sp_all = read_selected(ntuple["MuonSpacePoints"], SP_BRANCHES, wanted_ids)
    truth_all = read_selected(ntuple["MuonTruth"], TRUTH_BRANCHES, wanted_ids)
    sp_of_id = {int(e): i for i, e in enumerate(ak.to_numpy(sp_all["event_id"]))}
    truth_of_id = {int(e): i for i, e in enumerate(ak.to_numpy(truth_all["event_id"]))}

    muon_rows, muon_station_rows, segment_rows = [], [], []
    pattern_rows, pattern_station_rows, match_rows = [], [], []
    truth_hit_rows = []

    for entry, event in enumerate(event_numbers):
        event_id = id_of_number[event]
        sp_event = sp_all[sp_of_id[event_id]]
        truth_event = truth_all[truth_of_id[event_id]]

        # --- the space points of the event, decoded once -------------------
        muon_id = ak.to_numpy(sp_event["spacePoint_muonId"])
        fields = gpfval.decode_muon_id(muon_id)
        space_points = {
            "geo_id": ak.to_numpy(sp_event["spacePoint_geometryId"]).astype(np.int64),
            "bucket": ak.to_numpy(sp_event["spacePoint_bucketId"]).astype(int),
            "station": gpfval.station_of_name(fields["stationName"]),
            "sector": fields["sector"],
            "side": fields["side"],
            "detLayer": fields["detLayer"],
            "measuresEta": fields["measuresEta"],
            "measuresPhi": fields["measuresPhi"],
            "isStraw": fields["technology"] == gpfval.MDT,
            "type": gpfval.measurement_type(
                fields["technology"], fields["measuresEta"], fields["measuresPhi"]),
        }
        is_prec, is_trig, is_phi = gpfval.hit_classes(
            fields["technology"], fields["measuresEta"], fields["measuresPhi"])
        space_points |= {"isPrec": is_prec, "isTrig": is_trig, "isPhi": is_phi}

        # --- the truth -----------------------------------------------------
        per_muon = truth_hits_per_muon(truth_event)
        for muon in range(len(truth_event["Muons_pt"])):
            muon_rows.append({
                "event": event, "event_id": event_id, "muon": muon,
                "pt": float(truth_event["Muons_pt"][muon]),
                "eta": float(truth_event["Muons_eta"][muon]),
                "phi": float(truth_event["Muons_phi"][muon]),
                "q": int(truth_event["Muons_q"][muon]),
                "truthOrigin": int(truth_event["Muons_truthOrigin"][muon]),
                "truthType": int(truth_event["Muons_truthType"][muon]),
                "nSegments": int(truth_event["Muons_nTruthSegments"][muon]),
                "nGeoIds": len(per_muon.get(muon, ())),
            })
        for row in truth_counts(space_points, per_muon):
            muon_station_rows.append({"event": event, **row})

        # every identifier the muons crossed, and what became of it. A pattern
        # can only take an identifier that reached a space point, so the two
        # flags separate a loss before the finder from a loss inside it
        collected = set(int(g) for g in
                        ak.to_numpy(patterns["hit_geometryId"][entry]))
        available = set(int(g) for g in space_points["geo_id"])

        chamber = ak.to_numpy(truth_event["Segments_chamberIdx"])
        seg_station = gpfval.station_of_name(chamber)
        pos = np.stack([ak.to_numpy(truth_event[f"Segments_pos{a}"])
                        for a in "XYZ"], axis=1)
        for segment in range(len(chamber)):
            muon = int(truth_event["Segments_truthLink"][segment])
            for geo_id in ak.to_list(truth_event["Segments_hitGeoIds"][segment]):
                truth_hit_rows.append({
                    "event": event, "muon": muon, "segment": segment,
                    "station": int(seg_station[segment]),
                    "geo_id": int(geo_id),
                    "hasSpacePoint": int(geo_id) in available,
                    "inPattern": int(geo_id) in collected,
                })
            x, y, z = pos[segment]
            segment_rows.append({
                "event": event, "muon": muon,
                "segment": segment, "station": int(seg_station[segment]),
                "chamberIdx": int(chamber[segment]),
                "sector": int(truth_event["Segments_sector"][segment]),
                "etaIndex": int(truth_event["Segments_etaIndex"][segment]),
                "posX": float(x), "posY": float(y), "posZ": float(z),
                # the polar angle of a point of the trajectory, which is the
                # quantity a pattern's theta is, see the header of patterns
                "posTheta": float(np.arctan2(np.hypot(x, y), z)),
                "posPhi": float(np.arctan2(y, x)),
                "dirTheta": float(np.radians(truth_event["Segments_dirTheta"][segment])),
                "dirPhi": float(np.radians(truth_event["Segments_dirPhi"][segment])),
                "nPrecHits": int(truth_event["Segments_nPrecHits"][segment]),
                "nTrigEtaLayers": int(truth_event["Segments_nTrigEtaLayers"][segment]),
                "nTrigPhiLayers": int(truth_event["Segments_nTrigPhiLayers"][segment]),
                "chi2": float(truth_event["Segments_chi2"][segment]),
                "nDoF": int(truth_event["Segments_nDoF"][segment]),
                "nGeoIds": len(truth_event["Segments_hitGeoIds"][segment]),
            })

        # --- the patterns --------------------------------------------------
        hit_pattern = ak.to_numpy(patterns["hit_patternIdx"][entry]).astype(int)
        hit_station = ak.to_numpy(patterns["hit_station"][entry]).astype(int)
        hit_geo = ak.to_numpy(patterns["hit_geometryId"][entry]).astype(np.int64)
        hit_bucket = ak.to_numpy(patterns["hit_bucketId"][entry]).astype(int)
        hit_fields = gpfval.decode_muon_id(ak.to_numpy(patterns["hit_muonId"][entry]))
        hit_classes = np.stack(gpfval.hit_classes(
            hit_fields["technology"], hit_fields["measuresEta"],
            hit_fields["measuresPhi"]), axis=1)
        owner = {geo_id: muon for muon, ids in per_muon.items() for geo_id in ids}

        for pattern in range(len(patterns["pattern_theta"][entry])):
            mine = hit_pattern == pattern
            stations = hit_station[mine]
            classes = hit_classes[mine]
            geo_ids = hit_geo[mine]
            matched = np.array([owner.get(int(g), -1) for g in geo_ids])

            # the main truth muon is the one with the most hits in the pattern,
            # the rule of fillGlobPatternInfo(); it is taken over the whole
            # pattern, not per station
            muons, hits = np.unique(matched[matched >= 0], return_counts=True)
            main = int(muons[np.argmax(hits)]) if len(muons) else -1

            # the categories of updatePatHitInfo: every hit of the pattern,
            # those of the main muon, those of any other muon
            counts = np.zeros((N_STATIONS, 3, 4), dtype=int)
            for station, kinds, muon in zip(stations, classes, matched):
                for kind in np.flatnonzero(kinds):
                    counts[station, kind, 0] += 1
                    if main >= 0 and muon == main:
                        counts[station, kind, 1] += 1
                    elif muon >= 0:
                        counts[station, kind, 2] += 1
            # every hit of a bucket the pattern took a hit from, the eAll
            # counters of the tester
            crossed = np.flatnonzero(
                np.isin(space_points["bucket"], np.unique(hit_bucket[mine])))
            for kind, key in ((PREC, "isPrec"), (TRIG, "isTrig"), (PHI, "isPhi")):
                for hit in crossed[space_points[key][crossed]]:
                    station = space_points["station"][hit]
                    if station >= 0:
                        counts[station, kind, 3] += 1

            for station in range(N_STATIONS):
                if counts[station].any():
                    pattern_station_rows.append({
                        "event": event, "pattern": pattern, "station": station,
                        **{f"n{name}{kind}": int(counts[station, k, c])
                           for k, kind in ((PREC, "Prec"), (TRIG, "Trig"), (PHI, "Phi"))
                           for c, name in ((0, ""), (1, "Truth"), (2, "MisTruth"), (3, "All"))},
                    })
            for muon in muons:
                for station in range(N_STATIONS):
                    shared = int(np.count_nonzero(
                        (matched == muon) & (stations == station)))
                    if shared:
                        match_rows.append({
                            "event": event, "pattern": pattern, "muon": int(muon),
                            "station": station, "nShared": shared})

            theta = float(patterns["pattern_theta"][entry][pattern])
            phi = float(patterns["pattern_phi"][entry][pattern])
            row = {
                "event": event, "event_id": event_id, "pattern": pattern,
                "sector": int(patterns["pattern_sector"][entry][pattern]),
                "theta": theta, "eta": float(gpfval.eta_of_theta(theta)), "phi": phi,
                "nPrecisionLayers": int(patterns["pattern_nPrecisionLayers"][entry][pattern]),
                "nTriggerLayers": int(patterns["pattern_nTriggerLayers"][entry][pattern]),
                "nPhiLayers": int(patterns["pattern_nPhiLayers"][entry][pattern]),
                "meanNormResidual2": float(patterns["pattern_meanNormResidual2"][entry][pattern]),
                "nHits": int(mine.sum()),
                "nStations": int(len(np.unique(stations))),
                "mainMuon": main,
                "nShared": int(hits.max()) if len(muons) else 0,
                "nMatchedMuons": int(len(muons)),
                "nUnmatchedHits": int(np.count_nonzero(matched < 0)),
            }
            row.update(residuals(row, truth_event, per_muon, geo_ids, main))
            pattern_rows.append(row)

    args.output.mkdir(parents=True, exist_ok=True)
    tables = {
        "muons": muon_rows, "muon_station": muon_station_rows,
        "segments": segment_rows, "truth_hits": truth_hit_rows,
        "patterns": pattern_rows,
        "pattern_station": pattern_station_rows, "matches": match_rows,
    }
    for name, rows in tables.items():
        frame = pd.DataFrame(rows)
        frame.to_parquet(args.output / f"{name}.parquet", index=False)
        print(f"{name:<16} {len(frame):>8} rows")
    print(f"\nWrote the tables of {len(event_numbers)} events to {args.output}")
    return 0


def residuals(row, truth_event, per_muon, geo_ids, main):
    """Angular residuals of a pattern against its main truth muon.

    A pattern's theta is the polar angle of the global position of its seed hit,
    `patTheta{VectorHelpers::theta(seed->globalPosition(gctx))}` in
    GlobalPatternFinderAuxiliaries.ipp, and is never refitted. It is therefore
    the angle of a point of the trajectory, not the direction of one, and the
    truth quantities it may be compared with are

      dEtaMuon / dPhiMuon   the muon at production, the pair MuonFastRecoTester
                            writes as pat_Eta & gen_Eta. The toroid bends the
                            muon between the two, so this is a sanity check.
      dThetaSeg / dPhiSeg   the polar and azimuthal angle of the position of the
                            truth segment sharing the most identifiers with the
                            pattern. Same kind of quantity as the pattern's, and
                            free of the bending.

    `Segments_dirTheta` is deliberately not used: it is the direction of the
    segment, which the pattern does not estimate.
    """
    empty = {"dEtaMuon": np.nan, "dPhiMuon": np.nan,
             "dThetaSeg": np.nan, "dPhiSeg": np.nan, "segment": -1}
    if main < 0:
        return empty
    out = dict(empty)
    out["dEtaMuon"] = row["eta"] - float(truth_event["Muons_eta"][main])
    out["dPhiMuon"] = float(gpfval.wrap_pi(
        row["phi"] - float(truth_event["Muons_phi"][main])))

    pattern_ids = set(int(g) for g in geo_ids)
    best, best_shared = -1, 0
    for segment, muon in enumerate(ak.to_numpy(truth_event["Segments_truthLink"])):
        if int(muon) != main:
            continue
        shared = len(pattern_ids.intersection(
            int(v) for v in ak.to_list(truth_event["Segments_hitGeoIds"][segment])))
        if shared > best_shared:
            best, best_shared = segment, shared
    if best < 0:
        return out
    x = float(truth_event["Segments_posX"][best])
    y = float(truth_event["Segments_posY"][best])
    z = float(truth_event["Segments_posZ"][best])
    out["segment"] = best
    out["dThetaSeg"] = row["theta"] - float(np.arctan2(np.hypot(x, y), z))
    out["dPhiSeg"] = float(gpfval.wrap_pi(row["phi"] - np.arctan2(y, x)))
    return out


if __name__ == "__main__":
    sys.exit(main())
