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

#: Technology field, MuonSpacePoint::MuonId::TechField
MDT, RPC, TGC, STGC, MM = 0, 2, 3, 4, 5

#: Station names in the order of MuonSpacePoint::MuonId::StationName. Athena's
#: Muon::MuonStationIndex::ChIndex numbers its first fifteen entries the same
#: way, so `Segments_chamberIdx` of the truth tree indexes this list as well.
STATION_NAMES = [
    "BIS", "BIL", "BMS", "BML", "BOS", "BOL", "BEE",
    "EIS", "EIL", "EMS", "EML", "EOS", "EOL", "EES", "EEL",
]

#: Stations in the order of Muon::MuonStationIndex::StIndex
STATIONS = ["BI", "BM", "BO", "BE", "EI", "EM", "EO", "EE"]

#: Station name -> station, from toStationIndex() in
#: Examples/Algorithms/TrackFinding/src/GlobalPatternFinderDefs.cpp
_STATION_OF_NAME = np.array(
    [0, 0, 1, 1, 2, 2, 3, 4, 4, 5, 5, 6, 6, 7, 7], dtype=np.int8
)


def station_of_name(station_name):
    """Station index of a station name, both as the enums number them."""
    name = np.asarray(station_name, dtype=np.int64)
    out = np.full(name.shape, -1, dtype=np.int8)
    valid = (name >= 0) & (name < len(_STATION_OF_NAME))
    out[valid] = _STATION_OF_NAME[name[valid]]
    return out


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


def is_precision(technology, measures_eta, measures_phi):
    """Precision hit, as the example algorithm defines it.

    Transcribed from isPrecisionHit() in GlobalPatternFinderDefs.cpp. It differs
    from Athena's MuonR4::isPrecisionHit for sTGC, where the export does not
    carry the channel type: an sTGC space point counts as precision only when it
    measures eta alone, so an sTGC strip that also measures phi is counted as a
    trigger hit here and as a precision hit in Athena.
    """
    return (
        (technology == MDT)
        | (technology == MM)
        | ((technology == STGC) & measures_eta & ~measures_phi)
    )


#: Measurement classes of MuonFastRecoTester's `measType`, used to order the
#: hits; the counters themselves are not exclusive, see hit_classes()
PREC, TRIG, PHI = 0, 1, 2


def measurement_type(technology, measures_eta, measures_phi):
    """Precision / trigger-eta / phi-only of a hit.

    The split of fillSpacePointInfo() in MuonFastRecoTester.cxx: precision when
    isPrecisionHit() holds, otherwise a trigger hit when it measures eta,
    otherwise a phi-only hit. fillTruthInfo() walks the hits in this order so
    that a precision hit claims a layer before a trigger hit of the same layer
    does, which is why it is kept here.
    """
    prec = is_precision(technology, measures_eta, measures_phi)
    return np.where(prec, PREC, np.where(measures_eta, TRIG, PHI)).astype(np.int8)


def hit_classes(technology, measures_eta, measures_phi):
    """The three counters a hit contributes to, which are not exclusive.

    updatePatHitInfo() and processMeas() in MuonFastRecoTester.cxx count a hit
    as precision or as trigger when it measures eta, and count it as a phi hit
    whenever it measures phi. A space point measuring both therefore appears in
    an eta counter and in the phi counter at once.
    """
    prec = is_precision(technology, measures_eta, measures_phi)
    return (measures_eta & prec, measures_eta & ~prec, measures_phi)


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


def wrap_pi(angle):
    """Fold an angle difference into [-pi, pi)."""
    return (np.asarray(angle) + np.pi) % (2.0 * np.pi) - np.pi


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


class SurfaceMap:
    """Local-to-global transforms of the sensitive surfaces, by identifier.

    Built from the parquet file of build_geometry_cache.py. The rotation is
    stored the way AlgebraJsonConverter.cpp writes it, row by row, and is used
    without transposing: composing it as below reproduces the `patTheta` the
    pattern finder computed in C++ to within 1e-7, which is the check that
    fixes the convention.
    """

    def __init__(self, path):
        import pandas as pd

        frame = pd.read_parquet(path)
        self._row_of_id = {int(g): i for i, g in enumerate(frame["geo_id"].to_numpy())}
        self._rotation = frame[[f"r{i}{j}" for i in range(3)
                                for j in range(3)]].to_numpy().reshape(-1, 3, 3)
        self._translation = frame[["tx", "ty", "tz"]].to_numpy()

    def rows(self, geo_ids):
        """Row of every identifier, -1 when the surface is not in the geometry."""
        return np.array([self._row_of_id.get(int(g), -1) for g in geo_ids])

    def to_global(self, geo_ids, sector_position, to_sector_rotation,
                  to_sector_translation):
        """Global position of space points given in the frame of their sector.

        A space point's position is expressed in the frame of its spectrometer
        sector, and `toSectorTransform` maps the frame of its surface onto that
        one, so the global position is

            surface.localToGlobal * toSectorTransform^-1 * sectorPosition

        which is the composition localToGlobalTransform() of
        GlobalPatternFinderDefs.cpp applies in the algorithm. Rows without a
        surface come back as NaN.
        """
        rows = self.rows(geo_ids)
        local = np.einsum("nji,nj->ni", to_sector_rotation,
                          np.asarray(sector_position, dtype=float)
                          - np.asarray(to_sector_translation, dtype=float))
        out = np.full((len(rows), 3), np.nan)
        known = rows >= 0
        out[known] = (np.einsum("nij,nj->ni", self._rotation[rows[known]],
                                local[known]) + self._translation[rows[known]])
        return out
