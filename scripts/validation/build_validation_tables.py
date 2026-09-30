#!/usr/bin/env python3
"""Join the found patterns with the truth and write the validation tables.

This stage only counts and measures. It decides nothing: every threshold and
every definition of "the pattern found the muon" lives in compute_metrics.py, so
a definition can be changed without running the pattern finder again. That split
is Athena's, whose MuonFastRecoTester writes counts and defines no figure of
merit from them.

Three tables are written, and nothing is extracted that no test consumes. The
definitions they serve are in docs/validation.md.

    muons            one row per truth muon
    patterns         one row per pattern
    pattern_chamber  one row per pattern and chamber

The one difference to Athena that cannot be removed: it associates a measurement
with a truth particle through the sim hit behind it, a link the export does not
carry. Here a hit belongs to a muon when its geometry identifier is one of the
identifiers of the muon's truth segments, which TruthSegmentWriter fills with the
surfaces of exactly those sim hits. A wrong hit on a right surface therefore
counts as matched, which is what test 3 exists to measure.
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

#: Truth muons and the surfaces they crossed
TRUTH_BRANCHES = [
    "event_id",
    "Muons_pt", "Muons_eta", "Muons_phi", "Muons_q",
    "Segments_truthLink", "Segments_hitGeoIds", "Segments_localSegPars",
]
#: The hits of the event. `localPos` is already in the frame of the spectrometer
#: sector, which is the frame `Segments_localSegPars` uses, so no transform and
#: no tracking geometry are needed anywhere in this file.
SP_BRANCHES = [
    "event_id",
    "spacePoint_geometryId", "spacePoint_bucketId", "spacePoint_muonId",
    "spacePoint_localPosX", "spacePoint_localPosY", "spacePoint_localPosZ",
    "spacePoint_driftRadius", "spacePoint_covLoc0",
]
PATTERN_BRANCHES = [
    "event_id",
    "pattern_theta", "pattern_phi", "pattern_nPhiLayers", "pattern_sector",
    "pattern_meanNormResidual2",
    "hit_patternIdx", "hit_geometryId", "hit_station", "hit_muonId",
    "hit_bucketId", "hit_indexInBucket",
]


def read_selected(tree, branches, wanted_ids, step="200 MB"):
    """Return the entries of a tree whose event_id is in `wanted_ids`."""
    wanted = list(wanted_ids)
    kept, total = [], 0
    for chunk in tree.iterate(branches, step_size=step, library="ak"):
        mask = np.isin(ak.to_numpy(chunk["event_id"]), wanted)
        if mask.any():
            kept.append(chunk[mask])
            total += int(mask.sum())
        if total == len(wanted):
            break
    if not kept:
        raise SystemExit("None of the events of the pattern file are in the n-tuple")
    return ak.concatenate(kept)


def truth_identifiers(truth_event):
    """The surfaces each muon crossed, and which segment claims each of them.

    The union over a muon's segments is unaffected by the order of those
    segments, which matters because `Segments_hitGeoIds` is shifted by one
    segment relative to `Segments_chamberIdx` and the segment kinematics in this
    export. Nothing here pairs the two sets, so the shift cannot reach any test.
    """
    per_muon = defaultdict(set)
    owner_of_segment = ak.to_numpy(truth_event["Segments_truthLink"])
    segment_of_id = {}
    for segment, ids in enumerate(truth_event["Segments_hitGeoIds"]):
        muon = int(owner_of_segment[segment])
        for geo_id in ak.to_list(ids):
            per_muon[muon].add(int(geo_id))
            segment_of_id[int(geo_id)] = segment
    return per_muon, segment_of_id


def truth_lines(truth_event):
    """The line of every truth segment, in the frame of its spectrometer sector.

    `Segments_localSegPars` holds (y0, theta, x0, phi, t0) with the two angles in
    degrees, indexed by Line3DWithPartialDerivatives::ParIndex. The line passes
    through (x0, y0, 0) with the direction given by the two angles.
    """
    lines = {}
    for segment, values in enumerate(truth_event["Segments_localSegPars"]):
        pars = np.asarray(ak.to_list(values), dtype=float)
        lines[segment] = (np.array([pars[2], pars[0], 0.0]),
                          gpfval.direction(pars[3], pars[1]))
    return lines


def pull(position, drift, variance, is_straw, line):
    """How many standard deviations a hit lies from a truth segment's line.

    The residual is the Core's own, from CompSpacePointAuxiliaries: for a straw
    the measurement is the drift radius rather than the wire, so the distance to
    the wire has the drift radius subtracted and a correct tube hit gives about
    zero instead of about a tube radius. Dividing by the hit's own uncertainty
    folds in the precision of its technology, so tubes and strips land in one
    distribution and no threshold has to be set per technology.

    Only the bending plane is used: a segment barely constrains the coordinate
    along the tube, and including it would fold a well measured direction
    together with a badly measured one. Measured over the sample, a segment's own
    hits sit 0.14 mm from its line for an MDT, which is the drift resolution, and
    about 7 mm for the coarse trigger chambers.
    """
    origin, direction = line
    norm = np.hypot(direction[1], direction[2])
    if norm < 1e-9 or variance <= 0.0:
        return np.nan
    offset = position - origin
    distance = (direction[2] * offset[1] - direction[1] * offset[2]) / norm
    residual = abs(distance) - drift if is_straw else distance
    return float(residual / np.sqrt(variance))


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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

    muon_rows, pattern_rows, chamber_rows = [], [], []

    for entry, event in enumerate(event_numbers):
        event_id = id_of_number[event]
        sp_event = sp_all[sp_of_id[event_id]]
        truth_event = truth_all[truth_of_id[event_id]]

        # --- the hits of the event ------------------------------------------
        sp_geo = ak.to_numpy(sp_event["spacePoint_geometryId"]).astype(np.int64)
        sp_bucket = ak.to_numpy(sp_event["spacePoint_bucketId"]).astype(int)
        sp_position = np.stack([ak.to_numpy(sp_event[f"spacePoint_localPos{a}"])
                                for a in "XYZ"], axis=1).astype(float)
        sp_drift = ak.to_numpy(sp_event["spacePoint_driftRadius"]).astype(float)
        sp_variance = ak.to_numpy(sp_event["spacePoint_covLoc0"]).astype(float)
        # category and station of every hit of the event, for the counts taken
        # over a whole bucket
        sp_decoded = gpfval.decode_muon_id(
            ak.to_numpy(sp_event["spacePoint_muonId"]))
        sp_category = gpfval.hit_categories(sp_decoded)
        sp_station = gpfval.station_index(sp_decoded["stationName"])
        row_of_geo = {}
        for row, geo_id in enumerate(sp_geo):
            row_of_geo.setdefault(int(geo_id), row)
        available = {int(g) for g in sp_geo}
        hits_in_bucket = np.bincount(
            sp_bucket, minlength=(int(sp_bucket.max()) + 1) if len(sp_bucket) else 1)
        # the writer names a hit by its bucket and its index within it; the
        # reader fills the buckets in tree order, so the index is a running
        # counter that restarts with every new bucket
        row_of_key, counters = {}, defaultdict(int)
        for row, bucket in enumerate(sp_bucket):
            row_of_key[(int(bucket), counters[bucket])] = row
            counters[bucket] += 1

        # --- the truth -------------------------------------------------------
        per_muon, segment_of_id = truth_identifiers(truth_event)
        lines = truth_lines(truth_event)
        owner_of_segment = ak.to_numpy(truth_event["Segments_truthLink"])
        owner_of_id = {geo_id: muon for muon, ids in per_muon.items()
                       for geo_id in ids}

        for muon in range(len(truth_event["Muons_pt"])):
            # the rows the muon's truth segments claim
            mine = np.array([row_of_geo[g] for g in sorted(
                per_muon.get(muon, set()) & available)], dtype=int)
            on_muon = np.zeros(len(sp_geo), dtype=bool)
            on_muon[mine] = True
            muon_rows.append({
                "event": event, "muon": muon,
                "pt": float(truth_event["Muons_pt"][muon]),
                "eta": float(truth_event["Muons_eta"][muon]),
                "phi": float(truth_event["Muons_phi"][muon]),
                "q": int(truth_event["Muons_q"][muon]),
                # only the surfaces that produced a hit could ever be found
                "findable": len(per_muon.get(muon, set()) & available),
                **{f"gen{name}": gpfval.per_station(
                       on_muon & sp_category[key], sp_station).tolist()
                   for key, name in (("prec", "PrecMeas"),
                                     ("nonPrec", "NonPrecMeas"),
                                     ("phi", "PhiMeas"))},
            })

        # --- the patterns ----------------------------------------------------
        hit_pattern = ak.to_numpy(patterns["hit_patternIdx"][entry]).astype(int)
        hit_geo = ak.to_numpy(patterns["hit_geometryId"][entry]).astype(np.int64)
        hit_station = ak.to_numpy(patterns["hit_station"][entry]).astype(int)
        hit_bucket = ak.to_numpy(patterns["hit_bucketId"][entry]).astype(int)
        hit_index = ak.to_numpy(patterns["hit_indexInBucket"][entry]).astype(int)
        hit_decoded = gpfval.decode_muon_id(
            ak.to_numpy(patterns["hit_muonId"][entry]))
        hit_straw = hit_decoded["technology"] == gpfval.MDT
        hit_category = gpfval.hit_categories(hit_decoded)
        hit_side = hit_decoded["side"]

        # a segment's chamber, read off the pattern hits whose identifiers it
        # claims; `Segments_chamberIdx` is in the shifted set and is not used
        station_of_segment = {}
        claimed = defaultdict(list)
        for index, geo_id in enumerate(hit_geo):
            segment = segment_of_id.get(int(geo_id))
            if segment is not None:
                claimed[segment].append(int(hit_station[index]))
        for segment, stations in claimed.items():
            station_of_segment[segment] = int(np.bincount(stations).argmax())

        for pattern in range(len(patterns["pattern_theta"][entry])):
            mine = hit_pattern == pattern
            geo_ids = hit_geo[mine]
            stations = hit_station[mine]
            owners = np.array([owner_of_id.get(int(g), -1) for g in geo_ids])

            # the pattern belongs to the muon owning most of its hits, decided
            # over the whole pattern and not per chamber: fillGlobPatternInfo
            found, counts = np.unique(owners[owners >= 0], return_counts=True)
            main = int(found[np.argmax(counts)]) if len(found) else -1
            is_main = owners == main if main >= 0 else np.zeros(len(owners), bool)
            # the same flag over all hits of the event, for the category masks
            is_main_all = np.zeros(len(hit_pattern), dtype=bool)
            is_main_all[np.flatnonzero(mine)] = is_main

            buckets = np.unique(hit_bucket[mine])
            # every hit of every bucket the pattern drew from
            in_buckets = np.isin(sp_bucket, buckets)
            # muons sharing at least one hit, most-shared first
            ranked = sorted(
                ((int(np.count_nonzero(owners == m)), int(m)) for m in found),
                reverse=True) if len(found) else []
            stations_present = sorted(set(stations.tolist()))
            pattern_rows.append({
                "event": event, "pattern": pattern, "mainMuon": main,
                "matchedMuons": [m for _, m in ranked],
                "nStations": len(stations_present),
                "sector": int(patterns["pattern_sector"][entry][pattern]),
                # side of the first hit of the first station
                "side": int(hit_side[mine][
                    np.argmax(stations == stations_present[0])])
                        if len(stations_present) else 0,
                **{f"n{name}": gpfval.per_station(
                       mine & hit_category[key], hit_station).tolist()
                   for key, name in (("prec", "PrecMeas"),
                                     ("nonPrec", "NonPrecMeas"),
                                     ("phi", "PhiMeas"))},
                **{f"nTruth{name}": gpfval.per_station(
                       mine & is_main_all & hit_category[key],
                       hit_station).tolist()
                   for key, name in (("prec", "PrecMeas"),
                                     ("nonPrec", "NonPrecMeas"),
                                     ("phi", "PhiMeas"))},
                **{f"nAll{name}": gpfval.per_station(
                       in_buckets & sp_category[key], sp_station).tolist()
                   for key, name in (("prec", "PrecMeas"),
                                     ("nonPrec", "NonPrecMeas"),
                                     ("phi", "PhiMeas"))},
                # distinct identifiers, the unit the truth side counts in
                "shared": len({int(g) for g, m in zip(geo_ids, is_main) if m}),
                "stationsWithMuon": len(set(stations[is_main].tolist())),
                "nHits": int(mine.sum()),
                "nHitsMainMuon": int(is_main.sum()),
                "nHitsOtherMuon": int(np.count_nonzero((owners >= 0) & ~is_main)),
                "nHitsNoMuon": int(np.count_nonzero(owners < 0)),
                # every hit of every bucket the pattern drew from: Athena's eAll
                "nAvailable": int(hits_in_bucket[buckets].sum()),
                "theta": float(patterns["pattern_theta"][entry][pattern]),
                "phi": float(patterns["pattern_phi"][entry][pattern]),
                "eta": float(gpfval.eta_of_theta(
                    patterns["pattern_theta"][entry][pattern])),
                "nPhiLayers": int(patterns["pattern_nPhiLayers"][entry][pattern]),
                "meanNormResidual2": float(
                    patterns["pattern_meanNormResidual2"][entry][pattern]),
            })
            if main < 0:
                continue

            # --- how far the hits sit from the muon's path, per chamber ------
            # the line is per chamber because the toroid bends the muon between
            # them; only inside a chamber is the muon's path straight
            fallback = {station_of_segment[s]: s
                        for s in range(len(owner_of_segment))
                        if int(owner_of_segment[s]) == main
                        and s in station_of_segment}
            # the muon's own hits and the rest are kept apart. Averaging them
            # together would describe neither: the hits attributed to the muon
            # answer whether test 2 counted them rightly, and the others answer
            # how far from the muon's path the pattern reached, which is a
            # different question with a legitimately large answer.
            per_chamber = defaultdict(
                lambda: {"muon": [], "other": [], "missing": 0})
            for position, hit in enumerate(np.flatnonzero(mine)):
                station = int(hit_station[hit])
                segment = segment_of_id.get(int(hit_geo[hit]))
                belongs = segment is not None and int(owner_of_segment[segment]) == main
                if not belongs:
                    segment = fallback.get(station)
                content = per_chamber[station]
                row = row_of_key.get((int(hit_bucket[hit]), int(hit_index[hit])))
                if segment is None or row is None:
                    content["missing"] += 1
                    continue
                value = pull(sp_position[row], sp_drift[row], sp_variance[row],
                             bool(hit_straw[hit]), lines[segment])
                if np.isnan(value):
                    content["missing"] += 1
                else:
                    content["muon" if belongs else "other"].append(value)

            def mean_square(values):
                return float(np.mean(np.asarray(values) ** 2)) if values else np.nan

            for station, content in per_chamber.items():
                chamber_rows.append({
                    "event": event, "pattern": pattern, "muon": main,
                    "station": station,
                    "meanSqPull": mean_square(content["muon"]),
                    "nHitsPulled": len(content["muon"]),
                    "meanSqPullOther": mean_square(content["other"]),
                    "nHitsOther": len(content["other"]),
                    "nHitsNoSegment": int(content["missing"]),
                })

    args.output.mkdir(parents=True, exist_ok=True)
    # a fixed row order, so the tables do not depend on the order the sequencer
    # returned the events in
    for name, rows, keys in (
            ("muons", muon_rows, ["event", "muon"]),
            ("patterns", pattern_rows, ["event", "pattern"]),
            ("pattern_chamber", chamber_rows, ["event", "pattern", "station"])):
        frame = pd.DataFrame(rows)
        if len(frame):
            frame = frame.sort_values(keys, kind="stable").reset_index(drop=True)
        frame.to_parquet(args.output / f"{name}.parquet", index=False)
        print(f"{name:<16}{len(frame):>8} rows")
    print(f"{args.output}  {len(event_numbers)} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
