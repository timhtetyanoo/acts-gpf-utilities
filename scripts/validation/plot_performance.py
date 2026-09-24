#!/usr/bin/env python3
"""Draw the validation figures.

Two sources are plotted:

    scores.csv          one row per scored case, written by score_patterns.py
    patterns_*.root     the pattern files, for the distributions of the found
                        patterns themselves

The first gives the comparison between samples and implementations, the second
the sanity plots that show whether the patterns look physical at all.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import uproot  # noqa: E402

#: Metrics of the summary table & their axis labels
METRICS = {
    "efficiency": "Muon efficiency",
    "fake_fraction": "Fake fraction",
    "duplicates_per_muon": "Duplicates per muon",
    "hit_purity": "Hit purity",
    "hit_completeness": "Hit completeness",
}


def plot_scores(scores: pd.DataFrame, out_dir: Path) -> None:
    """One bar chart per metric, grouped by sample and implementation."""
    scores = scores.copy()
    scores["case"] = scores["sample"].astype(str)
    if scores["implementation"].notna().any():
        scores["case"] += " " + scores["implementation"].fillna("").astype(str)

    for metric, label in METRICS.items():
        if metric not in scores:
            continue
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.bar(scores["case"], scores[metric], color="tab:blue")
        ax.set_ylabel(label)
        ax.set_xlabel("")
        ax.grid(axis="y", alpha=0.3)
        for index, value in enumerate(scores[metric]):
            ax.text(index, value, f"{value:.3f}", ha="center", va="bottom")
        fig.tight_layout()
        fig.savefig(out_dir / f"{metric}.png", dpi=150)
        plt.close(fig)


def plot_distributions(path: Path, tree: str, out_dir: Path, label: str) -> None:
    """Sanity distributions of the patterns of one file."""
    arrays = uproot.open(path)[tree].arrays(
        [
            "pattern_theta",
            "pattern_phi",
            "pattern_sector",
            "pattern_nHits",
            "pattern_nPrecisionLayers",
            "pattern_nTriggerLayers",
            "pattern_nPhiLayers",
        ],
        library="np",
    )
    flat = {key: np.concatenate(value) if len(value) else np.array([])
            for key, value in arrays.items()}
    patterns_per_event = np.array([len(value) for value in arrays["pattern_theta"]])

    panels = [
        ("pattern_theta", "theta [rad]", 50),
        ("pattern_phi", "phi [rad]", 50),
        ("pattern_sector", "expanded sector", 32),
        ("pattern_nHits", "hits per pattern", 40),
        ("pattern_nPrecisionLayers", "precision layers", 20),
        ("pattern_nTriggerLayers", "trigger layers", 20),
    ]

    fig, axes = plt.subplots(3, 3, figsize=(12, 9))
    for ax, (key, xlabel, bins) in zip(axes.flat, panels):
        values = flat[key]
        if values.size:
            ax.hist(values, bins=bins, color="tab:blue")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("patterns")

    ax = axes.flat[len(panels)]
    ax.hist(patterns_per_event, bins=np.arange(patterns_per_event.max() + 2) - 0.5,
            color="tab:orange")
    ax.set_xlabel("patterns per event")
    ax.set_ylabel("events")

    for ax in axes.flat[len(panels) + 1:]:
        ax.axis("off")

    fig.suptitle(label)
    fig.tight_layout()
    fig.savefig(out_dir / f"distributions_{label}.png", dpi=150)
    plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scores", type=Path, help="Csv written by score_patterns.py")
    p.add_argument(
        "--patterns",
        type=Path,
        nargs="*",
        default=[],
        help="Pattern files the distributions are drawn for",
    )
    p.add_argument("--tree", default="muonGlobalPatterns", help="Pattern tree name")
    p.add_argument(
        "--output-dir", type=Path, default=Path("plots"), help="Directory of the figures"
    )
    args = p.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.scores:
        plot_scores(pd.read_csv(args.scores), args.output_dir)
    for path in args.patterns:
        plot_distributions(path, args.tree, args.output_dir, path.stem)

    print(f"Wrote the figures to {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
