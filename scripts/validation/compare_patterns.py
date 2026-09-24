#!/usr/bin/env python3
"""Compare two pattern files hit by hit.

This is the primary check for the CUDA implementation: the same input has to
give the same patterns as the CPU reference. A pattern is identified by the set
of hits it holds, and a hit by its place in the input space point container
(bucket and index within the bucket), which is stable across runs and
independent of memory addresses.

Reported per event:

    identical    patterns with exactly the same hit content on both sides
    only_a       patterns found by the reference alone
    only_b       patterns found by the compared run alone

A run that agrees everywhere prints no differing event and exits with 0, so the
script can be used as a regression gate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uproot


def load(path: Path, tree: str) -> dict[int, set[frozenset[tuple[int, int]]]]:
    """Return, per event, the set of patterns as sets of hit keys."""
    arrays = uproot.open(path)[tree].arrays(
        ["event_id", "hit_patternIdx", "hit_bucketId", "hit_indexInBucket"],
        library="np",
    )
    events: dict[int, set[frozenset[tuple[int, int]]]] = {}
    for event, patterns, buckets, indices in zip(
        arrays["event_id"],
        arrays["hit_patternIdx"],
        arrays["hit_bucketId"],
        arrays["hit_indexInBucket"],
    ):
        hits: dict[int, set[tuple[int, int]]] = {}
        for pattern, bucket, index in zip(patterns, buckets, indices):
            hits.setdefault(int(pattern), set()).add((int(bucket), int(index)))
        events[int(event)] = {frozenset(hit_set) for hit_set in hits.values()}
    return events


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("reference", type=Path, help="Pattern file of the reference run")
    p.add_argument("compared", type=Path, help="Pattern file of the compared run")
    p.add_argument("--tree", default="muonGlobalPatterns", help="Pattern tree name")
    p.add_argument(
        "--max-reported", type=int, default=10, help="Events listed in the output"
    )
    args = p.parse_args()

    reference = load(args.reference, args.tree)
    compared = load(args.compared, args.tree)

    events = sorted(set(reference) | set(compared))
    identical_total = only_a_total = only_b_total = 0
    differing: list[tuple[int, int, int, int]] = []

    for event in events:
        a = reference.get(event, set())
        b = compared.get(event, set())
        identical = len(a & b)
        only_a = len(a - b)
        only_b = len(b - a)
        identical_total += identical
        only_a_total += only_a
        only_b_total += only_b
        if only_a or only_b:
            differing.append((event, identical, only_a, only_b))

    print(f"Events compared       {len(events)}")
    print(f"Identical patterns    {identical_total}")
    print(f"Only in {args.reference.name}  {only_a_total}")
    print(f"Only in {args.compared.name}  {only_b_total}")
    print(f"Differing events      {len(differing)}")

    for event, identical, only_a, only_b in differing[: args.max_reported]:
        print(
            f"  event {event}: {identical} identical, "
            f"{only_a} only in the reference, {only_b} only in the comparison"
        )
    if len(differing) > args.max_reported:
        print(f"  ... {len(differing) - args.max_reported} more")

    return 1 if differing else 0


if __name__ == "__main__":
    sys.exit(main())
