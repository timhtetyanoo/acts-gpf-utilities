#!/usr/bin/env python3
"""Extract the sensitive surface transforms of the tracking geometry json.

The json is half a gigabyte and is needed only for its `surfaces` array, so it
is read once, streamed, and the part we use is cached as a parquet file:

    geo_id, tx, ty, tz, r00 .. r22

`geo_id` is the packed Acts::GeometryIdentifier, assembled from the fields the
json spells out, with the masks of Core/include/Acts/Geometry/GeometryIdentifier.hpp.
The rotation is stored row by row, the order AlgebraJsonConverter.cpp writes it
in, and a null rotation in the json is the identity.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

#: Bit position and width of the identifier fields
_FIELDS = {"volume": 56, "boundary": 48, "layer": 36,
           "approach": 28, "sensitive": 8, "extra": 0}


def pack_geo_id(fields: dict) -> int:
    """Assemble the packed identifier from the fields of the json."""
    value = 0
    for name, shift in _FIELDS.items():
        value |= int(fields.get(name, 0)) << shift
    return value


def surfaces(path: Path):
    """Yield the entries of the `surfaces` array one at a time.

    The file does not fit comfortably in memory, so the array is cut into its
    elements by counting braces and only one element is held at a time.
    """
    with path.open() as handle:
        for line in handle:
            if line.strip().startswith('"surfaces"'):
                break
        else:
            raise SystemExit("The json holds no 'surfaces' array")

        block: list[str] = []
        depth = 0
        for line in handle:
            stripped = line.strip()
            if depth == 0:
                if stripped.startswith("]"):
                    return
                if not stripped.startswith("{"):
                    continue
            depth += stripped.count("{") - stripped.count("}")
            block.append(line)
            if depth == 0 and block:
                yield json.loads("".join(block).rstrip().rstrip(","))
                block = []


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("geometry", type=Path, help="ActsTrackingGeometry.json")
    p.add_argument("output", type=Path, help="Parquet file to write")
    p.add_argument("--all", action="store_true",
                   help="Keep the passive surfaces as well")
    args = p.parse_args()

    identity = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    rows = []
    for surface in surfaces(args.geometry):
        if not args.all and not surface.get("sensitive", False):
            continue
        transform = surface["transform"]
        rotation = transform.get("rotation") or identity
        translation = transform["translation"]
        rows.append((pack_geo_id(surface["geo_id"]), *translation, *rotation))

    columns = ["geo_id", "tx", "ty", "tz"] + [f"r{i}{j}" for i in range(3)
                                              for j in range(3)]
    frame = pd.DataFrame(rows, columns=columns)
    frame["geo_id"] = frame["geo_id"].astype(np.uint64)
    frame.to_parquet(args.output, index=False)
    print(f"Wrote {len(frame)} surfaces to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
