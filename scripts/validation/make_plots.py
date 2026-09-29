#!/usr/bin/env python3
"""The four figures of the pattern finder validation.

Input is one or more directories holding `muon_flags.parquet` and
`pattern_flags.parquet`, written by compute_metrics.py. Several directories are
drawn on top of each other, which is how a CUDA run is compared with the CPU
reference.

    efficiency.png   efficiency against pt and against eta
    quality.png      completeness & purity of the matched patterns
    residuals.png    the angular residuals of a pattern against its muon
    rates.png        fakes & duplicates, and their dependence on the cut
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
        if len(selected) < 1:
            continue
        found = int(selected["found"].sum())
        total = len(selected)
        p = found / total
        centres.append(0.5 * (bins[b] + bins[b + 1]))
        values.append(p)
        errors.append(np.sqrt(max(p * (1.0 - p), 1e-12) / total))
    return np.array(centres), np.array(values), np.array(errors)


def plot_efficiency(runs, out: Path):
    fig, axes = plt.subplots(1, 2, figsize=(8.5, 3.4))
    pt_bins = np.linspace(0.0, 100.0, 21)
    eta_bins = np.linspace(-2.8, 2.8, 29)
    for label, muons, _ in runs:
        for ax, column, bins, xlabel in (
                (axes[0], "pt", pt_bins, r"truth $p_\mathrm{T}$ [GeV]"),
                (axes[1], "eta", eta_bins, r"truth $\eta$")):
            x, y, e = efficiency_profile(muons, column, bins)
            ax.errorbar(x, y, yerr=e, marker="o", ms=3, lw=1, label=label)
            ax.set_xlabel(xlabel)
            ax.set_ylabel("pattern efficiency")
            ax.set_ylim(0.0, 1.05)
    axes[0].legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def plot_quality(runs, out: Path):
    fig, axes = plt.subplots(1, 2, figsize=(8.5, 3.4))
    for label, muons, patterns in runs:
        found = muons[muons["found"]]
        axes[0].hist(found["completeness"].dropna(), bins=np.linspace(0, 1.4, 29),
                     histtype="step", lw=1.3, label=label)
        matched = patterns[patterns["isMatch"]]
        axes[1].hist(matched["purity"].dropna(), bins=np.linspace(0, 1.0, 21),
                     histtype="step", lw=1.3, label=label)
    axes[0].set_xlabel("completeness: precision hits found / findable")
    axes[1].set_xlabel("purity: hits of the main muon / hits of the pattern")
    for ax in axes:
        ax.set_ylabel("patterns")
        ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def plot_residuals(runs, out: Path):
    panels = [
        ("dThetaSeg", r"$\theta_\mathrm{pattern}-\theta_\mathrm{segment\ position}$ [rad]",
         np.linspace(-0.05, 0.05, 61)),
        ("dPhiSeg", r"$\phi_\mathrm{pattern}-\phi_\mathrm{segment\ position}$ [rad]",
         np.linspace(-0.05, 0.05, 61)),
        ("dEtaMuon", r"$\eta_\mathrm{pattern}-\eta_\mathrm{truth\ muon}$",
         np.linspace(-0.1, 0.1, 61)),
        ("dPhiMuon", r"$\phi_\mathrm{pattern}-\phi_\mathrm{truth\ muon}$ [rad]",
         np.linspace(-0.2, 0.2, 61)),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(8.5, 6.0))
    for ax, (column, xlabel, bins) in zip(axes.ravel(), panels):
        for label, muons, _ in runs:
            values = muons.loc[muons["found"], column].dropna()
            if values.empty:
                continue
            ax.hist(values, bins=bins, histtype="step", lw=1.3,
                    label=f"{label}: {values.mean():+.4f} $\\pm$ {values.std():.4f}")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("patterns")
        ax.legend(loc="upper left", fontsize=7)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def plot_rates(runs, out: Path):
    fig, axes = plt.subplots(1, 2, figsize=(8.5, 3.4))
    width = 0.8 / max(len(runs), 1)
    for i, (label, muons, patterns) in enumerate(runs):
        per_event = patterns.groupby("event").agg(
            patterns=("pattern", "size"), fakes=("isMatch", lambda c: int((~c).sum())))
        categories = ["patterns", "fakes", "duplicates"]
        values = [per_event["patterns"].mean(), per_event["fakes"].mean(),
                  muons["nDuplicates"].sum() / max(len(muons), 1)]
        axes[0].bar(np.arange(3) + i * width, values, width=width, label=label)
        axes[1].plot(muons["genPrec"], muons["nTruthPrec"].fillna(0), ".", ms=2,
                     label=label)
    axes[0].set_xticks(np.arange(3) + 0.4 - width / 2)
    axes[0].set_xticklabels(["patterns/event", "fakes/event", "duplicates/muon"])
    axes[0].set_ylabel("mean")
    axes[0].legend()
    limit = max(1.0, float(max(m["genPrec"].max() for _, m, _ in runs)))
    axes[1].plot([0, limit], [0, limit], "k--", lw=0.8)
    axes[1].set_xlabel("findable precision hits of the muon")
    axes[1].set_ylabel("precision hits in its pattern")
    axes[1].legend()
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

    runs = []
    for label, tables in zip(labels, args.tables):
        runs.append((label,
                     pd.read_parquet(tables / "muon_flags.parquet"),
                     pd.read_parquet(tables / "pattern_flags.parquet")))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    plot_efficiency(runs, args.output_dir / "efficiency.png")
    plot_quality(runs, args.output_dir / "quality.png")
    plot_residuals(runs, args.output_dir / "residuals.png")
    plot_rates(runs, args.output_dir / "rates.png")
    print(f"Wrote four figures to {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
