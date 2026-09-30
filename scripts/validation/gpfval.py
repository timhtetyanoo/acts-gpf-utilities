"""Helpers shared by the validation scripts.

Everything here is a transcription of a definition that lives in the ACTS or
the Athena source. The reference is named in the doc string of each function so
that a change on either side can be traced back.
"""

from __future__ import annotations

import numpy as np

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
