#!/usr/bin/env python3
"""The figures of the pattern finder validation, one per test that has a shape.

Input is one or more directories holding `muon_flags.parquet` and
`pattern_flags.parquet`, written by compute_metrics.py. Several directories are
drawn on top of each other, which is how a CUDA run is compared with the CPU
reference.

    efficiency.png    test 1, against truth eta and truth pT
    composition.png   test 2, purity, mismatched fraction and selectivity
    pulls.png         test 3, how far the hits sit from the muon's path
    direction.png     test 5, the pattern's direction against the muon's

Test 4 has no shape: fakes and duplicates are counts and live in the csv.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({"figure.dpi": 150, "font.size": 9,
                     "axes.grid": True, "grid.alpha": 0.3})


def efficiency_profile(muons: pd.DataFrame, column: str, bins):
    """Efficiency with its binomial uncertainty in bins of `column`."""
    index = np.digitize(muons[column], bins) - 1
    centres, values, errors = [], [], []
    for b in range(len(bins) - 1):
        selected = muons[index == b]
        if selected.empty:
            continue
        p = float(selected["found"].mean())
        centres.append(0.5 * (bins[b] + bins[b + 1]))
        values.append(p)
        errors.append(np.sqrt(max(p * (1.0 - p), 1e-12) / len(selected)))
    return np.array(centres), np.array(values), np.array(errors)


def plot_efficiency(runs, out: Path):
    """Test 1. Binned against truth quantities, as ACTS's EffPlotTool does.

    No acceptance cut: every truth muon is in the denominator, so the edge of
    the spectrometer's coverage shows up as the curve falling rather than being
    removed by a threshold nobody can justify.
    """
    fig, axes = plt.subplots(1, 2, figsize=(8.5, 3.4))
    for label, muons, _ in runs:
        for ax, column, bins, xlabel in (
                (axes[0], "pt", np.linspace(0.0, 100.0, 21),
                 r"truth $p_\mathrm{T}$ [GeV]"),
                (axes[1], "eta", np.linspace(-3.0, 3.0, 31), r"truth $\eta$")):
            x, y, e = efficiency_profile(muons, column, bins)
            ax.errorbar(x, y, yerr=e, marker="o", ms=3, lw=1, label=label)
            ax.set_xlabel(xlabel)
            ax.set_ylabel("pattern efficiency")
            ax.set_ylim(0.0, 1.05)
    axes[0].legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def plot_composition(runs, out: Path):
    """Test 2. Purity is only readable next to selectivity, so they share a row."""
    panels = [
        ("purity", "hits of the muon / hits of the pattern", np.linspace(0, 1, 21)),
        ("selectivity", "hits taken / hits available in those chambers",
         np.linspace(0, 1, 21)),
        ("mismatched", "hits of another muon / hits of the pattern",
         np.linspace(0, 0.5, 21)),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.2))
    for ax, (column, xlabel, bins) in zip(axes, panels):
        for label, _, patterns in runs:
            values = patterns.loc[patterns["isMatch"], column].dropna()
            if values.empty:
                continue
            ax.hist(values, bins=bins, histtype="step", lw=1.3,
                    label=f"{label}: {values.mean():.3f}")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("patterns")
        ax.legend(loc="upper left", fontsize=7)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def plot_pulls(runs, out: Path):
    """Test 3. One is the value a pattern lying on the muon's path should give."""
    fig, ax = plt.subplots(figsize=(5.0, 3.4))
    bins = np.logspace(-2, 4, 49)
    for label, _, patterns in runs:
        values = patterns.loc[patterns["isMatch"], "meanSqPull"].dropna()
        if values.empty:
            continue
        ax.hist(values.clip(bins[0], bins[-1]), bins=bins, histtype="step", lw=1.3,
                label=f"{label}: median {values.median():.2f}")
    ax.axvline(1.0, color="0.4", ls="--", lw=0.9)
    ax.set_xscale("log")
    ax.set_xlabel("mean squared pull of the muon's hits about its truth line")
    ax.set_ylabel("patterns")
    ax.legend(loc="upper right", fontsize=7)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def plot_direction(runs, out: Path):
    """Test 5. The phi residual is split on whether the finder measured phi.

    With no phi-measuring hit the finder assigns the centre of the sector rather
    than an estimate, so those patterns are spread over the sector width however
    good they are and are drawn apart from the rest.
    """
    fig, axes = plt.subplots(1, 2, figsize=(8.5, 3.4))
    for label, muons, patterns in runs:
        found = muons[muons["found"]]
        if found.empty:
            continue
        values = found["dEta"].dropna()
        axes[0].hist(values, bins=np.linspace(-0.1, 0.1, 61), histtype="step",
                     lw=1.3, label=f"{label}: {values.mean():+.4f} "
                                   f"$\\pm$ {values.std():.4f}")
        measured = patterns.loc[patterns["isMatch"] & (patterns["nPhiLayers"] > 0),
                                ["event", "mainMuon"]]
        has_phi = found.merge(measured.rename(columns={"mainMuon": "muon"}),
                              on=["event", "muon"], how="inner")["dPhi"].dropna()
        for subset, style, tag in ((has_phi, "-", "phi measured"),
                                   (found["dPhi"].dropna(), ":", "all")):
            if subset.empty:
                continue
            axes[1].hist(subset, bins=np.linspace(-0.2, 0.2, 61), histtype="step",
                         lw=1.3, ls=style,
                         label=f"{label}, {tag}: {subset.std():.4f}")
    axes[0].set_xlabel(r"$\eta_\mathrm{pattern}-\eta_\mathrm{truth\ muon}$")
    axes[1].set_xlabel(r"$\phi_\mathrm{pattern}-\phi_\mathrm{truth\ muon}$ [rad]")
    for ax in axes:
        ax.set_ylabel("muons")
        ax.legend(loc="upper left", fontsize=7)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tables", type=Path, nargs="+",
                   help="Directories written by compute_metrics.py")
    p.add_argument("--labels", nargs="*", default=[],
                   help="One label per directory, the directory name by default")
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()

    labels = args.labels or [t.name for t in args.tables]
    if len(labels) != len(args.tables):
        raise SystemExit("Give one label per directory")

    runs = [(label,
             pd.read_parquet(tables / "muon_flags.parquet"),
             pd.read_parquet(tables / "pattern_flags.parquet"))
            for label, tables in zip(labels, args.tables)]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    plot_efficiency(runs, args.output_dir / "efficiency.png")
    plot_composition(runs, args.output_dir / "composition.png")
    plot_pulls(runs, args.output_dir / "pulls.png")
    plot_direction(runs, args.output_dir / "direction.png")
    print(f"Wrote the figures to {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
