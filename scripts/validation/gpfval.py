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
#: Only the tube technology is needed: a straw's residual has its drift
#: radius subtracted, everything else is measured where it was recorded
MDT = 0

#: Stations in the order of Muon::MuonStationIndex::StIndex
STATIONS = ["BI", "BM", "BO", "BE", "EI", "EM", "EO", "EE"]


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
