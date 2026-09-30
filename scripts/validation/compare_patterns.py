#!/usr/bin/env python3
"""Compare the patterns of two runs over the same space points.

Nothing here knows or cares which implementation produced either file. The only
requirement is that both runs read the same n-tuple through the same reader, so
that a hit can be named the same way on both sides. Comparing a CUDA run with
the CPU reference is one use; comparing two CPU runs across a change to the
finder, or two settings of the same run, is the same operation.

What ties the two files together is the hit, named by its place in the input
space point container: the bucket and the index within the bucket. That name is
a property of the input, not of the run, so it is stable across runs and
independent of memory addresses. Neither the order of the hits in a pattern nor
the order of the patterns in an event carries any meaning here.

The patterns are not required to be equal. They are first paired with each
other, greedily on the hits they share, and only then compared, so a pattern
that lost a single borderline hit stays one pattern with a hit difference
instead of being reported as one pattern missing and one appeared.

Compared, per paired pattern:

    shared / onlyRef / onlyCmp   which input hits each side collected
    jaccard                      shared over the union, 1 when identical
    dTheta, dPhi                 the direction each run claims
    dSector                      the sector each run assigned it to
    dPrecisionLayers, dTriggerLayers, dPhiLayers   the layers each run counted
    dMeanNormResidual2           the quality each run reports

and, per run, the patterns that were paired with nothing at all. Events that
only one of the runs processed are named and then left out, since counting
their patterns as lost would say nothing about the patterns.

The exit code is non-zero when the agreement falls below the tolerances, so the
script can be used as a regression gate. The defaults demand exact agreement,
which is what a pure reordering of the same arithmetic produces; loosen them
deliberately, with --min-matched, --min-jaccard and --tolerance, rather than by
ignoring a red exit.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import uproot

PATTERN_BRANCHES = [
    "event_id", "pattern_theta", "pattern_phi", "pattern_sector",
    "pattern_nPrecisionLayers", "pattern_nTriggerLayers", "pattern_nPhiLayers",
    "pattern_meanNormResidual2",
    "hit_patternIdx", "hit_bucketId", "hit_indexInBucket",
]


def load(path: Path, tree: str) -> dict[int, dict]:
    """Per event, the hit keys of every pattern and the pattern parameters."""
    arrays = uproot.open(path)[tree].arrays(PATTERN_BRANCHES, library="np")
    events: dict[int, dict] = {}
    for entry, event in enumerate(arrays["event_id"]):
        hits: dict[int, set[tuple[int, int]]] = {}
        for pattern, bucket, index in zip(arrays["hit_patternIdx"][entry],
                                          arrays["hit_bucketId"][entry],
                                          arrays["hit_indexInBucket"][entry]):
            hits.setdefault(int(pattern), set()).add((int(bucket), int(index)))
        n_patterns = len(arrays["pattern_theta"][entry])
        events[int(event)] = {
            "hits": [hits.get(p, set()) for p in range(n_patterns)],
            "pars": {name: arrays[name][entry] for name in arrays
                     if name.startswith("pattern_")},
        }
    return events


def match(reference: list[set], compared: list[set]) -> list[tuple[int, int, int]]:
    """Pair the patterns of the two runs by the hits they share.

    Greedy on the number of shared hits, which is deterministic and enough here:
    two patterns of the same event that overlap strongly with the same partner
    would have been merged by the finder itself.
    """
    candidates = []
    for a, hits_a in enumerate(reference):
        for b, hits_b in enumerate(compared):
            shared = len(hits_a & hits_b)
            if shared:
                candidates.append((shared, a, b))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    taken_a: set[int] = set()
    taken_b: set[int] = set()
    pairs = []
    for shared, a, b in candidates:
        if a in taken_a or b in taken_b:
            continue
        taken_a.add(a)
        taken_b.add(b)
        pairs.append((a, b, shared))
    return pairs


def wrap_pi(angle: float) -> float:
    return (angle + np.pi) % (2.0 * np.pi) - np.pi


def compare(reference: dict, compared: dict) -> pd.DataFrame:
    """One row per pattern of either run, matched or not."""
    rows = []
    for event in sorted(set(reference) | set(compared)):
        a = reference.get(event, {"hits": [], "pars": {}})
        b = compared.get(event, {"hits": [], "pars": {}})
        pairs = match(a["hits"], b["hits"])
        matched_a = {pair[0] for pair in pairs}
        matched_b = {pair[1] for pair in pairs}

        for index_a, index_b, shared in pairs:
            hits_a, hits_b = a["hits"][index_a], b["hits"][index_b]
            union = len(hits_a | hits_b)
            rows.append({
                "event": event, "reference": index_a, "compared": index_b,
                "shared": shared,
                "onlyRef": len(hits_a - hits_b),
                "onlyCmp": len(hits_b - hits_a),
                "jaccard": shared / union if union else np.nan,
                "dTheta": float(a["pars"]["pattern_theta"][index_a]
                                - b["pars"]["pattern_theta"][index_b]),
                "dPhi": wrap_pi(float(a["pars"]["pattern_phi"][index_a]
                                      - b["pars"]["pattern_phi"][index_b])),
                "dSector": int(a["pars"]["pattern_sector"][index_a])
                - int(b["pars"]["pattern_sector"][index_b]),
                "dPrecisionLayers": int(a["pars"]["pattern_nPrecisionLayers"][index_a])
                - int(b["pars"]["pattern_nPrecisionLayers"][index_b]),
                "dTriggerLayers": int(a["pars"]["pattern_nTriggerLayers"][index_a])
                - int(b["pars"]["pattern_nTriggerLayers"][index_b]),
                "dPhiLayers": int(a["pars"]["pattern_nPhiLayers"][index_a])
                - int(b["pars"]["pattern_nPhiLayers"][index_b]),
                "dMeanNormResidual2": float(
                    a["pars"]["pattern_meanNormResidual2"][index_a]
                    - b["pars"]["pattern_meanNormResidual2"][index_b]),
            })
        for index_a in range(len(a["hits"])):
            if index_a not in matched_a:
                rows.append({"event": event, "reference": index_a, "compared": -1,
                             "shared": 0, "onlyRef": len(a["hits"][index_a]),
                             "onlyCmp": 0, "jaccard": 0.0})
        for index_b in range(len(b["hits"])):
            if index_b not in matched_b:
                rows.append({"event": event, "reference": -1, "compared": index_b,
                             "shared": 0, "onlyRef": 0,
                             "onlyCmp": len(b["hits"][index_b]), "jaccard": 0.0})
    return pd.DataFrame(rows)


def report(table: pd.DataFrame, args, only_reference, only_compared) -> int:
    paired = table[(table["reference"] >= 0) & (table["compared"] >= 0)]
    lost = table[table["compared"] < 0]
    gained = table[table["reference"] < 0]
    n_reference = len(paired) + len(lost)
    n_compared = len(paired) + len(gained)
    identical = int((paired["jaccard"] == 1.0).sum()) if len(paired) else 0
    matched_fraction = len(paired) / n_reference if n_reference else 1.0

    if only_reference or only_compared:
        print(f"warning: events only in reference {len(only_reference)}, only "
              f"in comparison {len(only_compared)}; common events only below",
              file=sys.stderr)
    print(f"{'events':<28}{table['event'].nunique()}")
    print(f"{'patterns reference':<28}{n_reference}")
    print(f"{'patterns compared':<28}{n_compared}")
    print(f"{'paired':<28}{len(paired)}  ({matched_fraction:.4f})")
    print(f"{'paired identical':<28}{identical}")
    print(f"{'unpaired reference':<28}{len(lost)}")
    print(f"{'unpaired compared':<28}{len(gained)}")
    if len(paired):
        print(f"{'jaccard mean':<28}{paired['jaccard'].mean():.6f}")
        print(f"{'jaccard min':<28}{paired['jaccard'].min():.6f}")
        print(f"{'hits only reference':<28}{int(paired['onlyRef'].sum())}")
        print(f"{'hits only compared':<28}{int(paired['onlyCmp'].sum())}")
        print(f"{'max |dTheta|':<28}{paired['dTheta'].abs().max():.3e}")
        print(f"{'max |dPhi|':<28}{paired['dPhi'].abs().max():.3e}")
        for column, label in (("dSector", "sector"),
                              ("dPrecisionLayers", "precision layers"),
                              ("dTriggerLayers", "trigger layers"),
                              ("dPhiLayers", "phi layers")):
            print(f"{'differing ' + label:<28}{int((paired[column] != 0).sum())}")

    worst = paired[paired["jaccard"] < 1.0].nsmallest(args.max_reported, "jaccard")
    if len(worst):
        print(f"\nleast similar pairs ({len(worst)}):")
        for _, row in worst.iterrows():
            print(f"  event {int(row['event'])}: reference {int(row['reference'])} "
                  f"vs compared {int(row['compared'])}, {int(row['shared'])} shared, "
                  f"{int(row['onlyRef'])} lost, {int(row['onlyCmp'])} gained, "
                  f"jaccard {row['jaccard']:.4f}, dTheta {row['dTheta']:+.3e}")

    failures = []
    if matched_fraction < args.min_matched:
        failures.append(f"paired fraction {matched_fraction:.4f} < "
                        f"{args.min_matched}")
    if len(paired):
        if paired["jaccard"].min() < args.min_jaccard:
            failures.append(f"jaccard min {paired['jaccard'].min():.4f} < "
                            f"{args.min_jaccard}")
        if paired["dTheta"].abs().max() > args.tolerance:
            failures.append(f"max |dTheta| {paired['dTheta'].abs().max():.3e} > "
                            f"{args.tolerance:.3e}")
        if paired["dPhi"].abs().max() > args.tolerance:
            failures.append(f"max |dPhi| {paired['dPhi'].abs().max():.3e} > "
                            f"{args.tolerance:.3e}")
    if failures:
        for failure in failures:
            print(f"differ: {failure}", file=sys.stderr)
        return 1
    print("\nagree")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("reference", type=Path, help="Pattern file of the reference run")
    p.add_argument("compared", type=Path, help="Pattern file of the compared run")
    p.add_argument("--tree", default="muonGlobalPatterns", help="Pattern tree name")
    p.add_argument("--max-reported", type=int, default=10,
                   help="Least similar pairs listed in the output")
    p.add_argument("--min-matched", type=float, default=1.0,
                   help="Reference patterns that have to find a partner")
    p.add_argument("--min-jaccard", type=float, default=1.0,
                   help="Hits a matched pair has to share, over their union")
    p.add_argument("--tolerance", type=float, default=1e-6,
                   help="Allowed difference of theta and phi, in radians")
    p.add_argument("--output", type=Path,
                   help="Parquet file the per pattern table is written to")
    args = p.parse_args()

    reference = load(args.reference, args.tree)
    compared = load(args.compared, args.tree)
    # comparing an event one run never saw would count all of its patterns as
    # lost, which says nothing about the patterns themselves
    only_reference = sorted(set(reference) - set(compared))
    only_compared = sorted(set(compared) - set(reference))
    common = sorted(set(reference) & set(compared))

    table = compare({e: reference[e] for e in common},
                    {e: compared[e] for e in common})
    if args.output:
        table.to_parquet(args.output, index=False)
        print(f"{args.output}\n")
    return report(table, args, only_reference, only_compared)


if __name__ == "__main__":
    sys.exit(main())
