"""Helpers shared by the validation scripts.

Everything here is a transcription of a definition that lives in the ACTS or
the Athena source. The reference is named in the doc string of each function so
that a change on either side can be traced back.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --- the muon identifier -----------------------------------------------------
# Bit layout of `spacePoint_muonId` and `hit_muonId`, transcribed from
# MuonSpacePoint::MuonId::MuonId(std::uint32_t) in
# Examples/Framework/src/EventData/MuonSpacePoint.cpp.

#: Technology field, MuonSpacePoint::MuonId::TechField. The gap at 1 is the CSC,
#: which Run 4 does not have
MDT = 0
RPC = 2
TGC = 3
STGC = 4
MM = 5

#: Stations in the order of Muon::MuonStationIndex::StIndex
STATIONS = ["BI", "BM", "BO", "BE", "EI", "EM", "EO", "EE"]

#: Number of stations, Muon::MuonStationIndex::StIndex::StIndexMax
N_STATIONS = len(STATIONS)

#: Sectors of the spectrometer, MuonStationIndex::numberOfSectors()
N_SECTORS = 16

#: Muon::MuonStationIndex::toStationIndex(ChIndex), as a lookup over the
#: stationName field, which the exporter fills with the chamber index
STATION_OF_CHAMBER = np.array([0, 0,      # BIS BIL -> BI
                               1, 1,      # BMS BML -> BM
                               2, 2,      # BOS BOL -> BO
                               3,         # BEE     -> BE
                               4, 4,      # EIS EIL -> EI
                               5, 5,      # EMS EML -> EM
                               6, 6,      # EOS EOL -> EO
                               7, 7],     # EES EEL -> EE
                              dtype=np.int8)


def decode_muon_id(raw):
    """Unpack the fields of a muon identifier.

    The inverse of MuonSpacePoint::MuonId::toInt(). `detLayer` is the field the
    Athena exporter fills with MuonSectorMapping::sectorLayerNum(), which is the
    quantity MuonFastRecoTester deduplicates on.
    """
    raw = np.asarray(raw, dtype=np.uint32)
    return {
        "stationName": (raw & 0xF).astype(np.int8),
        "side": np.where((raw >> 4) & 0x1 == 1, 1, -1).astype(np.int8),
        "technology": ((raw >> 5) & 0x7).astype(np.int8),
        "sector": ((raw >> 8) & 0x3F).astype(np.int16) + 1,
        "measuresEta": ((raw >> 14) & 0x1).astype(bool),
        "measuresPhi": ((raw >> 15) & 0x1).astype(bool),
        "detLayer": ((raw >> 17) & 0xF).astype(np.int16) + 1,
        "channel": (raw >> 21).astype(np.int32) + 1,
    }


# --- the event numbering -----------------------------------------------------
def reader_event_numbers(file, tree_name="MuonSpacePoints"):
    """Map an event_id onto the event number the reader hands the algorithm.

    RootMuonSpacePointReader sorts the entries of the space point tree by
    event_id with an ascending stable sort (RootUtility::stableSort) and reads
    entry `m_eventRanges[eventNumber]`, so the event number is the rank of the
    entry. The pattern file records that number, hence the truth has to be keyed
    by it as well.
    """
    event_ids = file[tree_name]["event_id"].array(library="np")
    order = np.argsort(event_ids, kind="stable")
    return {int(event_ids[entry]): number for number, entry in enumerate(order)}


# --- angles ------------------------------------------------------------------


def eta_of_theta(theta):
    """Pseudorapidity of a polar angle, as MuonFastRecoTester fills pat_Eta."""
    theta = np.asarray(theta, dtype=float)
    return -np.log(np.tan(np.clip(theta, 1e-9, np.pi - 1e-9) / 2.0))


# --- the global frame --------------------------------------------------------


def direction(phi_degrees, theta_degrees):
    """Unit vector of a direction the n-tuple stores as two angles in degrees.

    The counterpart of Acts::makeDirectionFromPhiTheta, which the readers apply
    to the columns of the frames and to the sensor directions.
    """
    phi = np.radians(np.asarray(phi_degrees, dtype=float))
    theta = np.radians(np.asarray(theta_degrees, dtype=float))
    return np.stack([np.sin(theta) * np.cos(phi),
                     np.sin(theta) * np.sin(phi),
                     np.cos(theta)], axis=-1)


def station_index(station_name):
    """Station of a chamber, MuonStationIndex::toStationIndex(ChIndex).

    The pattern file records it per hit as `hit_station`; the space points of
    the n-tuple carry the chamber in their identifier instead.
    """
    name = np.asarray(station_name, dtype=int)
    return STATION_OF_CHAMBER[np.clip(name, 0, len(STATION_OF_CHAMBER) - 1)]


def hit_categories(decoded):
    """Split hits into the three populations counted per station.

    Precision is isPrecisionHit() from MuonSpacePoint/SpacePointHelpers: a tube,
    a micromega, or an sTgc measuring the precision coordinate alone, which is
    the strip.
    """
    tech = decoded["technology"]
    measures_eta = decoded["measuresEta"]
    precision = ((tech == MDT) | (tech == MM)
                 | ((tech == STGC) & measures_eta & ~decoded["measuresPhi"]))
    return {"prec": precision,
            "nonPrec": measures_eta & ~precision,
            "phi": ~measures_eta}


def per_station(mask, stations):
    """Count the hits selected by `mask`, one entry per station.

    The inner vector of every pat_N*Meas and gen_N*Meas branch, indexed by
    StIndex over its full range. Counted in int32; the branches are UChar_t and
    the narrowing happens in the writer.
    """
    counts = np.zeros(N_STATIONS, dtype=np.int32)
    if len(stations) == 0:
        return counts
    selected = np.asarray(stations, dtype=int)[np.asarray(mask, dtype=bool)]
    if len(selected):
        np.add.at(counts, selected, 1)
    return counts


def expanded_sector_pair(expanded):
    """The two ms sectors an expanded sector spans, as pat_Sector1 & pat_Sector2.

    ExpandedSector::msSectorAndProj, ::msSector and ::adjacentMsSector. Equal
    outside an overlap region.
    """
    expanded = int(expanded)
    if expanded in (0, 1):
        # the wrap of sector 16, which the constructor maps onto 0 and 1
        main, projector = N_SECTORS, expanded
    else:
        main = expanded // 2
        projector = expanded - 2 * main
    if main == 1 and projector == -1:
        return main, N_SECTORS
    if main == N_SECTORS and projector == 1:
        return main, 1
    return main, main + projector


# --- the selection and the matching of MuonFastRecoValidation --------------
# Transcribed from MuonFastRecoValidTuple.h on the LeonardoDev branch of
# houghidipuffvalidation, so that the numbers here are the ones the plotting
# package computes from the same patterns. Each function names its original.

#: tpEtaMax and tpPtMin, the kinematic acceptance of a truth muon
TP_ETA_MAX = 2.4
TP_PT_MIN_GEV = 10.0
#: minTrigEtaHits, minPrecHits, minStations, minBendPerStation of tpHitSel
MIN_TRIG_ETA_HITS = 2
MIN_PREC_HITS = 8
MIN_STATIONS = 2
MIN_BEND_PER_STATION = 4
#: stationEffThr and NBendingEffThr of effQuality, both compared with a strict >
STATION_EFF_THR = 0.5
BENDING_EFF_THR = 0.5

#: seedingLayers = {Middle, Outer}: BM, BO, EM, EO as Muon::MuonStationIndex::
#: toLayerIndex(StIndex) maps them, in StIndex order
SEEDING_STATIONS = np.array([1, 2, 5, 6])

#: The branches are UChar_t, so the plotting package reads every count clipped
#: at 255; the same clip here keeps a ratio of two counts the same number
UCHAR_MAX = 255


def stack_counts(column):
    """A column of per-station count arrays as an (entries, stations) array."""
    rows = list(column)
    if not rows:
        return np.zeros((0, N_STATIONS), dtype=np.int64)
    return np.minimum(np.stack(rows).astype(np.int64), UCHAR_MAX)


def truth_selection(muons, eta_max=TP_ETA_MAX, pt_min=TP_PT_MIN_GEV):
    """Which truth muons enter the efficiency, tpHitSel.

    Inside |eta| < 2.4 and above 10 GeV, with at least two stations holding four
    or more bending hits, two trigger hits in the middle and outer layers, and
    eight precision hits in all. The tuple stores eta and pT as floats and pT in
    MeV, and the comparison is made in those types.
    """
    prec = stack_counts(muons["genPrecMeas"])
    trig = stack_counts(muons["genNonPrecMeas"])
    n_stations = ((prec + trig) >= MIN_BEND_PER_STATION).sum(axis=1)
    n_trig = trig[:, SEEDING_STATIONS].sum(axis=1)
    eta = muons["eta"].to_numpy().astype(np.float32)
    pt_mev = (muons["pt"].to_numpy().astype(np.float64) * 1.0e3).astype(np.float32)
    selected = ((np.abs(eta) < np.float32(eta_max))
                & (pt_mev.astype(np.float64) * 1.0e-3 >= pt_min)
                & (n_stations >= MIN_STATIONS)
                & (n_trig >= MIN_TRIG_ETA_HITS)
                & (prec.sum(axis=1) >= MIN_PREC_HITS))
    return pd.Series(selected, index=muons.index)


def pattern_truth(patterns):
    """The muon a pattern is matched to, getPatTruthPar: the first of the muons
    that share a hit with it, most shared first. -1 when it shares none."""
    return np.array([int(v[0]) if len(v) else -1 for v in patterns["matchedMuons"]],
                    dtype=np.int64)


def pattern_quality(patterns, muons, station_thr=STATION_EFF_THR,
                    bending_thr=BENDING_EFF_THR):
    """Which patterns count as a match of their muon, hasQualityTruth.

    The pattern has to cross more than `station_thr` of the stations the muon
    crossed, and to hold more than `bending_thr` of the muon's bending hits. The
    two ratios are compared as `ratio <= threshold` fails, so a muon with no hits
    at all (0/0) does not fail, as in effQuality.

    @return the truth muon of every pattern and a boolean per pattern
    """
    truth = pattern_truth(patterns)
    quality = np.zeros(len(patterns), dtype=bool)
    has = truth >= 0
    if not has.any():
        return truth, quality
    sub = patterns.loc[has]
    gen = pd.DataFrame({"event": sub["event"].to_numpy(), "muon": truth[has]}).merge(
        muons[["event", "muon", "genPrecMeas", "genNonPrecMeas"]],
        on=["event", "muon"], how="left")
    gen_prec, gen_trig = stack_counts(gen["genPrecMeas"]), stack_counts(gen["genNonPrecMeas"])
    pat_prec, pat_trig = stack_counts(sub["nPrecMeas"]), stack_counts(sub["nNonPrecMeas"])
    truth_prec = stack_counts(sub["nTruthPrecMeas"])
    truth_trig = stack_counts(sub["nTruthNonPrecMeas"])

    gen_stations = (gen_prec + gen_trig) > 0
    pat_stations = (pat_prec + pat_trig) > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        station_ratio = (gen_stations & pat_stations).sum(axis=1) / gen_stations.sum(axis=1)
        bending_ratio = (truth_prec + truth_trig).sum(axis=1) / (gen_prec + gen_trig).sum(axis=1)
    quality[has] = ~(station_ratio <= station_thr) & ~(bending_ratio <= bending_thr)
    return truth, quality


def best_match(patterns, quality, truth):
    """Which matched pattern stands for its muon, isBestMatch.

    The one with the most of the muon's bending hits, and among those the
    smallest mean normalised residual. It has to beat every other match of the
    muon strictly: two matches equal in both leave none of them the best, which
    is how the plotting package behaves and makes it count the muon as missed.
    """
    best = np.zeros(len(patterns), dtype=bool)
    if not quality.any():
        return best
    sub = patterns.loc[quality]
    frame = pd.DataFrame({
        "event": sub["event"].to_numpy(),
        "truth": truth[quality],
        "nbend": (stack_counts(sub["nTruthPrecMeas"])
                  + stack_counts(sub["nTruthNonPrecMeas"])).sum(axis=1),
        "resid": sub["meanNormResidual2"].to_numpy().astype(np.float32),
        "row": np.flatnonzero(quality),
    }).sort_values(["event", "truth", "nbend", "resid"],
                   ascending=[True, True, False, True], kind="stable")
    group = frame.groupby(["event", "truth"], sort=False)
    next_nbend, next_resid = group["nbend"].shift(-1), group["resid"].shift(-1)
    strictly = (next_nbend.isna() | (frame["nbend"] > next_nbend)
                | ((frame["nbend"] == next_nbend) & (frame["resid"] < next_resid)))
    best[frame.loc[(group.cumcount() == 0) & strictly, "row"].to_numpy()] = True
    return best
