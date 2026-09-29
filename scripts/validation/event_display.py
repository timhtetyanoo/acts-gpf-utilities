#!/usr/bin/env python3
"""Draw single events, the way Athena's FastRecoVisualizationTool does.

That tool paints, for one bucket, the hits, the line of the pattern and the
line of the truth segment, in an eta view of the local frame and in the global
R-Z plane. Here the whole event is drawn at once in the global frame, which is
the view that says whether a pattern picked up the right chambers:

    left    R over z
    right   y over x

Grey are the space points of the event, coloured the hits of each pattern, the
dashed lines are the truth segments and the thin rays the direction a pattern
claims. A pattern's theta and phi are the polar and azimuthal angle of its seed
hit, so its ray starts at the origin.

Needs the surface cache of build_geometry_cache.py to place the hits.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import awkward as ak
import matplotlib
import numpy as np
import uproot

import gpfval

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({"figure.dpi": 150, "font.size": 9,
                     "axes.grid": True, "grid.alpha": 0.3})

SP_BRANCHES = (
    ["event_id", "spacePoint_geometryId", "spacePoint_bucketId",
     "spacePoint_localPosX", "spacePoint_localPosY", "spacePoint_localPosZ"]
    + [f"spacePoint_toSectorFrameLinearCol{c}{a}"
       for c in range(3) for a in ("Phi", "Theta")]
    + [f"spacePoint_toSectorFrameTranslation{a}" for a in "XYZ"]
)
TRUTH_BRANCHES = ["event_id", "Segments_truthLink", "Segments_posX",
                  "Segments_posY", "Segments_posZ", "Segments_dirTheta",
                  "Segments_dirPhi"]

#: Half length of the drawn truth segment and of a pattern ray, in millimetres
SEGMENT_HALF_LENGTH = 1500.0
RAY_LENGTH = 24000.0


def collect(tree, branches, wanted_ids):
    kept = []
    for chunk in tree.iterate(branches, step_size="200 MB", library="ak"):
        mask = np.isin(ak.to_numpy(chunk["event_id"]), list(wanted_ids))
        if mask.any():
            kept.append(chunk[mask])
    return ak.concatenate(kept)


def global_positions(surfaces: gpfval.SurfaceMap, event):
    """Global position of every space point of the event."""
    position = np.stack([ak.to_numpy(event[f"spacePoint_localPos{a}"])
                         for a in "XYZ"], axis=1)
    rotation = np.stack(
        [gpfval.direction(event[f"spacePoint_toSectorFrameLinearCol{c}Phi"],
                          event[f"spacePoint_toSectorFrameLinearCol{c}Theta"])
         for c in range(3)], axis=2)
    translation = np.stack(
        [ak.to_numpy(event[f"spacePoint_toSectorFrameTranslation{a}"])
         for a in "XYZ"], axis=1)
    geo_ids = ak.to_numpy(event["spacePoint_geometryId"]).astype(np.int64)
    return geo_ids, surfaces.to_global(geo_ids, position, rotation, translation)


def draw(event_number, geo_ids, points, pattern_entry, truth_event, out: Path):
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.4))
    radius = np.hypot(points[:, 0], points[:, 1])

    axes[0].plot(points[:, 2], radius, ".", ms=1.5, color="0.75",
                 label="space points")
    axes[1].plot(points[:, 0], points[:, 1], ".", ms=1.5, color="0.75")

    hit_pattern = ak.to_numpy(pattern_entry["hit_patternIdx"]).astype(int)
    hit_geo = ak.to_numpy(pattern_entry["hit_geometryId"]).astype(np.int64)
    row_of_id = {int(g): i for i, g in enumerate(geo_ids)}
    colours = plt.cm.tab10.colors

    for pattern in range(len(pattern_entry["pattern_theta"])):
        rows = [row_of_id[int(g)] for g in hit_geo[hit_pattern == pattern]
                if int(g) in row_of_id]
        colour = colours[pattern % len(colours)]
        if rows:
            axes[0].plot(points[rows, 2], radius[rows], "o", ms=3.5, mfc="none",
                         color=colour, label=f"pattern {pattern}")
            axes[1].plot(points[rows, 0], points[rows, 1], "o", ms=3.5,
                         mfc="none", color=colour)
        theta = float(pattern_entry["pattern_theta"][pattern])
        phi = float(pattern_entry["pattern_phi"][pattern])
        ray = RAY_LENGTH * np.array([np.sin(theta) * np.cos(phi),
                                     np.sin(theta) * np.sin(phi), np.cos(theta)])
        axes[0].plot([0.0, ray[2]], [0.0, np.hypot(ray[0], ray[1])], "-",
                     lw=0.8, color=colour)
        axes[1].plot([0.0, ray[0]], [0.0, ray[1]], "-", lw=0.8, color=colour)

    drawn = False
    for segment in range(len(truth_event["Segments_posX"])):
        centre = np.array([float(truth_event[f"Segments_pos{a}"][segment])
                           for a in "XYZ"])
        step = SEGMENT_HALF_LENGTH * gpfval.direction(
            truth_event["Segments_dirPhi"][segment],
            truth_event["Segments_dirTheta"][segment])
        ends = np.stack([centre - step, centre + step])
        axes[0].plot(ends[:, 2], np.hypot(ends[:, 0], ends[:, 1]), "k--", lw=1.2,
                     label=None if drawn else "truth segments")
        axes[1].plot(ends[:, 0], ends[:, 1], "k--", lw=1.2)
        drawn = True

    axes[0].set_xlabel("z [mm]")
    axes[0].set_ylabel("R [mm]")
    axes[0].set_ylim(bottom=0.0)
    axes[1].set_xlabel("x [mm]")
    axes[1].set_ylabel("y [mm]")
    axes[1].set_aspect("equal", adjustable="datalim")
    axes[0].legend(loc="upper left", fontsize=7)
    fig.suptitle(f"event {event_number}")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("patterns", type=Path)
    p.add_argument("ntuple", type=Path)
    p.add_argument("surfaces", type=Path, help="Cache of build_geometry_cache.py")
    p.add_argument("output", type=Path, help="Directory of the figures")
    p.add_argument("--pattern-tree", default="muonGlobalPatterns")
    p.add_argument("--events", type=int, nargs="*", default=[],
                   help="Event numbers to draw, the first --n-events otherwise")
    p.add_argument("--n-events", type=int, default=5)
    args = p.parse_args()

    patterns = uproot.open(args.patterns)[args.pattern_tree].arrays(library="ak")
    numbers = ak.to_numpy(patterns["event_id"]).astype(int)
    chosen = args.events or list(numbers[: args.n_events])

    ntuple = uproot.open(args.ntuple)
    id_of_number = {number: event_id for event_id, number
                    in gpfval.reader_event_numbers(ntuple).items()}
    wanted = {id_of_number[n] for n in chosen}
    space_points = collect(ntuple["MuonSpacePoints"], SP_BRANCHES, wanted)
    truth = collect(ntuple["MuonTruth"], TRUTH_BRANCHES, wanted)
    sp_of_id = {int(e): i for i, e in enumerate(ak.to_numpy(space_points["event_id"]))}
    truth_of_id = {int(e): i for i, e in enumerate(ak.to_numpy(truth["event_id"]))}

    surfaces = gpfval.SurfaceMap(args.surfaces)
    args.output.mkdir(parents=True, exist_ok=True)
    for number in chosen:
        entry = int(np.flatnonzero(numbers == number)[0])
        event_id = id_of_number[number]
        geo_ids, points = global_positions(surfaces,
                                           space_points[sp_of_id[event_id]])
        draw(number, geo_ids, points, patterns[entry], truth[truth_of_id[event_id]],
             args.output / f"event_{number:06d}.png")
    print(f"Drew {len(chosen)} events into {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
