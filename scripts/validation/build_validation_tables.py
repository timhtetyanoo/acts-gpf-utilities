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
carry. Here each truth segment lists the surfaces of its sim hits
(`Segments_hitGeoIds`, filled by TruthSegmentWriter), and on each of those
surfaces the segment claims the hit closest to its line by the Core's chi2
(CompSpacePointAuxiliaries::chi2Term), one per measured direction: one eta hit,
one phi hit and one hit measuring both. A tube is its own surface, a strip
layer one surface, so the truth holds one hit per tube and one per strip layer
and direction.
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
    "spacePoint_driftRadius", "spacePoint_covLoc0", "spacePoint_covLoc1",
    "spacePoint_sensorDirPhi", "spacePoint_sensorDirTheta",
    "spacePoint_toNextDirPhi", "spacePoint_toNextDirTheta",
]
PATTERN_BRANCHES = [
    "event_id",
    "pattern_theta", "pattern_phi", "pattern_nPhiLayers", "pattern_sector",
    "pattern_meanNormResidual2",
    "hit_patternIdx", "hit_station", "hit_muonId",
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


class EventColumns:
    """The branches of a tree held as plain arrays, one event at a time.

    Looking an event up in an awkward array costs milliseconds, and the tables
    look up a dozen branches per event, so every branch is converted once:
    a branch with one value per event into a NumPy array, one with a list per
    event into a flat NumPy array and the offsets of each event, and one with a
    list of lists per event into nested Python lists. An event's values are then
    a slice or an index.
    """

    def __init__(self, array, branches):
        self._scalar, self._flat, self._offsets, self._nested = {}, {}, {}, {}
        for branch in branches:
            column = array[branch]
            if column.ndim == 1:
                self._scalar[branch] = ak.to_numpy(column)
            elif column.ndim == 2:
                counts = ak.to_numpy(ak.num(column, axis=1))
                self._offsets[branch] = np.concatenate(([0], np.cumsum(counts)))
                self._flat[branch] = ak.to_numpy(ak.flatten(column, axis=1))
            else:
                self._nested[branch] = ak.to_list(column)

    def event(self, index):
        """The values of every branch for the entry at `index`."""
        values = {name: column[index] for name, column in self._scalar.items()}
        for name, flat in self._flat.items():
            offsets = self._offsets[name]
            values[name] = flat[offsets[index]:offsets[index + 1]]
        for name, nested in self._nested.items():
            values[name] = nested[index]
        return values


def truth_hits(truth_event, lines, by_geo, span_of_geo, hits):
    """The hits each truth segment claims, as the muon and segment of each row.

    For every surface a segment lists, the hits on it are split by the
    directions they measure, and in each group the hit with the smallest
    chi2 to the segment's line is claimed. A hit claimed by two segments goes to
    the one it is closer to. Rows nobody claims keep the muon and segment -1.

    Space points of one measurement, the same strip combined with different
    strips of the other direction, share a surface and a local y
    (HitPayload::overlaps). The third array names, for every row, the claimed
    row of its measurement, so that any of them stands for the claimed one; it
    is the row itself otherwise.
    """
    n_rows = len(hits["position"])
    owner = np.full(n_rows, -1, dtype=int)
    segment_of_row = np.full(n_rows, -1, dtype=int)
    best = np.full(n_rows, np.inf)
    direction_kind = 2 * hits["measures_eta"].astype(int) + hits["measures_phi"]
    owner_of_segment = truth_event["Segments_truthLink"]
    for segment, ids in enumerate(truth_event["Segments_hitGeoIds"]):
        rows = [by_geo[slice(*span_of_geo[int(g)])] for g in ids
                if int(g) in span_of_geo]
        if not rows:
            continue
        rows = np.unique(np.concatenate(rows))
        chi2 = gpfval.chi2_term(*lines[segment],
                                {k: v[rows] for k, v in hits.items()})
        chi2 = np.where(np.isnan(chi2), np.inf, chi2)
        geo, kind = hits["geometry"][rows], direction_kind[rows]
        # the closest hit of every surface and direction
        order = np.lexsort((chi2, kind, geo))
        group = np.stack([geo[order], kind[order]], axis=1)
        first = np.ones(len(order), dtype=bool)
        first[1:] = np.any(group[1:] != group[:-1], axis=1)
        for row, value in zip(rows[order][first], chi2[order][first]):
            if value < best[row] or owner[row] < 0:
                best[row] = value
                owner[row] = int(owner_of_segment[segment])
                segment_of_row[row] = segment
    measurement = np.empty(n_rows, dtype=[("geo", np.int64), ("y", float)])
    measurement["geo"] = hits["geometry"]
    measurement["y"] = hits["local_y"]
    _, measurement_id = np.unique(measurement, return_inverse=True)
    claimed = np.flatnonzero(owner >= 0)
    claimed_of = np.full(measurement_id.max() + 1 if n_rows else 0, -1)
    claimed_of[measurement_id[claimed]] = claimed
    truth_row = np.arange(n_rows)
    stand_in = (owner < 0) & (claimed_of[measurement_id] >= 0)
    truth_row[stand_in] = claimed_of[measurement_id[stand_in]]
    return owner, segment_of_row, truth_row


def truth_lines(truth_event):
    """The line of every truth segment, in the frame of its spectrometer sector.

    `Segments_localSegPars` holds (y0, theta, x0, phi, t0) with the two angles in
    degrees, indexed by Line3DWithPartialDerivatives::ParIndex. The line passes
    through (x0, y0, 0) with the direction given by the two angles.
    """
    lines = {}
    for segment, values in enumerate(truth_event["Segments_localSegPars"]):
        pars = np.asarray(values, dtype=float)
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
    sp_columns = EventColumns(sp_all, SP_BRANCHES)
    truth_columns = EventColumns(truth_all, TRUTH_BRANCHES)
    pattern_columns = EventColumns(patterns, PATTERN_BRANCHES)

    muon_rows, pattern_rows, chamber_rows = [], [], []

    for entry, event in enumerate(event_numbers):
        event_id = id_of_number[event]
        sp_event = sp_columns.event(sp_of_id[event_id])
        truth_event = truth_columns.event(truth_of_id[event_id])
        pattern_event = pattern_columns.event(entry)

        # --- the hits of the event ------------------------------------------
        sp_geo = np.asarray(sp_event["spacePoint_geometryId"]).astype(np.int64)
        sp_bucket = np.asarray(sp_event["spacePoint_bucketId"]).astype(int)
        sp_position = np.stack([np.asarray(sp_event[f"spacePoint_localPos{a}"])
                                for a in "XYZ"], axis=1).astype(float)
        sp_drift = np.asarray(sp_event["spacePoint_driftRadius"]).astype(float)
        sp_variance = np.asarray(sp_event["spacePoint_covLoc1"]).astype(float)
        # category and station of every hit of the event, for the counts taken
        # over a whole bucket
        sp_decoded = gpfval.decode_muon_id(
            np.asarray(sp_event["spacePoint_muonId"]))
        sp_category = gpfval.hit_categories(sp_decoded)
        sp_station = gpfval.station_index(sp_decoded["stationName"])
        # the rows of every identifier, as a slice of the rows sorted by it
        by_geo = np.argsort(sp_geo, kind="stable")
        unique_geo, geo_start = np.unique(sp_geo[by_geo], return_index=True)
        geo_end = np.append(geo_start[1:], len(sp_geo))
        span_of_geo = dict(zip(unique_geo.tolist(),
                               zip(geo_start.tolist(), geo_end.tolist())))
        sp_hits = {
            "geometry": sp_geo,
            "local_y": sp_position[:, 1],
            "position": sp_position,
            "sensor": gpfval.direction(sp_event["spacePoint_sensorDirPhi"],
                                       sp_event["spacePoint_sensorDirTheta"]),
            "to_next": gpfval.direction(sp_event["spacePoint_toNextDirPhi"],
                                        sp_event["spacePoint_toNextDirTheta"]),
            "cov_non_bending": np.asarray(
                sp_event["spacePoint_covLoc0"]).astype(float),
            "cov_bending": sp_variance,
            "drift": sp_drift,
            "straw": sp_decoded["technology"] == gpfval.MDT,
            "measures_eta": sp_decoded["measuresEta"],
            "measures_phi": sp_decoded["measuresPhi"],
        }
        hits_in_bucket = np.bincount(
            sp_bucket, minlength=(int(sp_bucket.max()) + 1) if len(sp_bucket) else 1)
        # the writer names a hit by its bucket and its index within it; the
        # reader fills the buckets in tree order, so the index is a running
        # counter that restarts with every new bucket: the rows of bucket b, in
        # tree order, are rows_by_bucket[bucket_start[b]:bucket_start[b + 1]]
        rows_by_bucket = np.argsort(sp_bucket, kind="stable")
        bucket_start = np.concatenate(([0], np.cumsum(hits_in_bucket)))

        def row_of_key(bucket, index):
            """The row of the hit at `index` in `bucket`, None if there is none."""
            if bucket < 0 or bucket >= len(hits_in_bucket) or \
                    index < 0 or index >= hits_in_bucket[bucket]:
                return None
            return int(rows_by_bucket[bucket_start[bucket] + index])

        # --- the truth -------------------------------------------------------
        lines = truth_lines(truth_event)
        owner_of_segment = truth_event["Segments_truthLink"]
        owner_of_row, segment_of_row, truth_row = truth_hits(
            truth_event, lines, by_geo, span_of_geo, sp_hits)

        for muon in range(len(truth_event["Muons_pt"])):
            # the hits the muon's truth segments claim
            on_muon = owner_of_row == muon
            muon_rows.append({
                "event": event, "muon": muon,
                "pt": float(truth_event["Muons_pt"][muon]),
                "eta": float(truth_event["Muons_eta"][muon]),
                "phi": float(truth_event["Muons_phi"][muon]),
                "q": int(truth_event["Muons_q"][muon]),
                # only the hits its segments claimed could ever be found
                "findable": int(np.count_nonzero(on_muon)),
                **{f"gen{name}": gpfval.per_station(
                       on_muon & sp_category[key], sp_station).tolist()
                   for key, name in (("prec", "PrecMeas"),
                                     ("nonPrec", "NonPrecMeas"),
                                     ("phi", "PhiMeas"))},
            })

        # --- the patterns ----------------------------------------------------
        hit_pattern = np.asarray(pattern_event["hit_patternIdx"]).astype(int)
        hit_station = np.asarray(pattern_event["hit_station"]).astype(int)
        hit_bucket = np.asarray(pattern_event["hit_bucketId"]).astype(int)
        hit_index = np.asarray(pattern_event["hit_indexInBucket"]).astype(int)
        hit_decoded = gpfval.decode_muon_id(
            np.asarray(pattern_event["hit_muonId"]))
        hit_straw = hit_decoded["technology"] == gpfval.MDT
        hit_category = gpfval.hit_categories(hit_decoded)
        hit_side = hit_decoded["side"]

        # the row of every pattern hit in the event, and the truth it carries
        hit_row = np.array([-1 if row is None else row for row in (
            row_of_key(int(b), int(i)) for b, i in zip(hit_bucket, hit_index))],
            dtype=int)
        # the claimed row each pattern hit stands for, and its muon and segment
        hit_truth = np.where(hit_row >= 0, truth_row[hit_row], -1)
        hit_owner = np.where(hit_truth >= 0, owner_of_row[hit_truth], -1)
        hit_segment = np.where(hit_truth >= 0, segment_of_row[hit_truth], -1)

        # a segment's chamber, read off the pattern hits it claims;
        # `Segments_chamberIdx` is in the shifted set and is not used
        station_of_segment = {}
        claimed = defaultdict(list)
        for index, segment in enumerate(hit_segment):
            if segment >= 0:
                claimed[int(segment)].append(int(hit_station[index]))
        for segment, stations in claimed.items():
            station_of_segment[segment] = int(np.bincount(stations).argmax())

        for pattern in range(len(pattern_event["pattern_theta"])):
            mine = hit_pattern == pattern
            stations = hit_station[mine]
            owners = hit_owner[mine]

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
                "sector": int(pattern_event["pattern_sector"][pattern]),
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
                # distinct hits, the unit the truth side counts in
                "shared": len(set(hit_truth[mine][is_main].tolist())),
                "stationsWithMuon": len(set(stations[is_main].tolist())),
                "nHits": int(mine.sum()),
                "nHitsMainMuon": int(is_main.sum()),
                "nHitsOtherMuon": int(np.count_nonzero((owners >= 0) & ~is_main)),
                "nHitsNoMuon": int(np.count_nonzero(owners < 0)),
                # every hit of every bucket the pattern drew from: Athena's eAll
                "nAvailable": int(hits_in_bucket[buckets].sum()),
                "theta": float(pattern_event["pattern_theta"][pattern]),
                "phi": float(pattern_event["pattern_phi"][pattern]),
                "eta": float(gpfval.eta_of_theta(
                    pattern_event["pattern_theta"][pattern])),
                "nPhiLayers": int(pattern_event["pattern_nPhiLayers"][pattern]),
                "meanNormResidual2": float(
                    pattern_event["pattern_meanNormResidual2"][pattern]),
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
                belongs = int(hit_owner[hit]) == main
                segment = int(hit_segment[hit]) if belongs else fallback.get(station)
                content = per_chamber[station]
                row = int(hit_row[hit])
                if segment is None or row < 0:
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
