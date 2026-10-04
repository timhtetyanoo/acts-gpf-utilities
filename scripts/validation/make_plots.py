#!/usr/bin/env python3
"""The figures of the pattern finder validation, one per test that has a shape.

The panels follow the groups of compute_metrics.py:

    efficiency.png    test 1, against truth pT, eta and phi
    composition.png   test 2, purity, mismatched fraction and selectivity
    pulls.png         test 3, how far the hits sit from the muon's path
    direction.png     test 5, the pattern's direction against the muon's

Test 4 has no shape: fakes and duplicates are counts and live in the csv.

Input is one or more directories holding `muon_flags.parquet` and
`pattern_flags.parquet`, written by compute_metrics.py. Several directories are
drawn on top of each other, which is how a CUDA run is compared with the CPU
reference.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from scipy.stats import beta

import gpfval

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({"figure.dpi": 150, "font.size": 9,
                     "axes.grid": True, "grid.alpha": 0.3})


#: Confidence level of the error bars, ROOT's TEfficiency default
CONFIDENCE = 0.683


def clopper_pearson(passed, total):
    """The central Clopper-Pearson interval of an efficiency, as TEfficiency's
    default does it: the lower and the upper edge, 0 and 1 where that is exact."""
    passed, total = np.asarray(passed, float), np.asarray(total, float)
    alpha = 1.0 - CONFIDENCE
    lower = np.where(passed == 0, 0.0,
                     beta.ppf(alpha / 2, passed, total - passed + 1))
    upper = np.where(passed == total, 1.0,
                     beta.ppf(1 - alpha / 2, passed + 1, total - passed))
    return lower, upper


def efficiency_profile(muons: pd.DataFrame, values, bins):
    """Efficiency of the selected muons in bins of `values`, with its interval."""
    index = np.digitize(np.asarray(values), bins) - 1
    found = muons["found"].to_numpy()
    centres, eff, lower, upper = [], [], [], []
    for b in range(len(bins) - 1):
        in_bin = index == b
        total = int(in_bin.sum())
        if total == 0:
            continue
        passed = int(found[in_bin].sum())
        low, high = clopper_pearson(passed, total)
        centres.append(0.5 * (bins[b] + bins[b + 1]))
        eff.append(passed / total)
        lower.append(float(low))
        upper.append(float(high))
    return (np.array(centres), np.array(eff), np.array(lower), np.array(upper))


def plot_efficiency(runs, out: Path, sample: str):
    """Test 1. The efficiency of the selected truth muons.

    The selection and the binning are those of MuonFastRecoValidation: truth
    muons inside |eta| < 2.4 and above 10 GeV that cross enough stations and hold
    enough hits (gpfval.truth_selection), 25 bins in eta, 45 in pT, 50 in phi, the
    error bars a Clopper-Pearson interval.
    """
    panels = (
        ("pt", lambda m: m["pt"], np.linspace(gpfval.TP_PT_MIN_GEV, 100.0, 46),
         r"efficiency vs $p_\mathrm{T}$", r"truth $p_\mathrm{T}$ [GeV]"),
        ("eta", lambda m: m["eta"],
         np.linspace(-gpfval.TP_ETA_MAX, gpfval.TP_ETA_MAX, 26),
         r"efficiency vs $\eta$", r"truth $\eta$"),
        ("phi", lambda m: np.degrees(m["phi"]), np.linspace(-180.0, 180.0, 51),
         r"efficiency vs $\phi$", r"truth $\phi$ [deg]"),
    )
    fig, axes = plt.subplots(1, 3, figsize=(12.0, 3.4))
    lowest = 1.0
    for label, muons, _ in runs:
        muons = muons[muons["selected"]]
        for ax, (_, column, bins, title, xlabel) in zip(axes, panels):
            x, y, low, high = efficiency_profile(muons, column(muons), bins)
            if len(x) == 0:
                continue
            ax.errorbar(x, y, yerr=[y - low, high - y], marker="o", ms=3, lw=1,
                        capsize=1.5, label=label)
            lowest = min(lowest, float(low.min()))
            ax.set_title(title, fontsize=10)
            ax.set_xlabel(xlabel)
            ax.set_ylabel("pattern efficiency")
    bottom = max(0.0, np.floor((lowest - 0.02) * 20) / 20)
    for ax in axes:
        ax.set_ylim(bottom, 1.02)
    axes[0].legend(loc="lower right")
    cut = (rf"truth: $|\eta| < {gpfval.TP_ETA_MAX}$, "
           rf"$p_\mathrm{{T}} \geq {gpfval.TP_PT_MIN_GEV:g}$ GeV, "
           f"enough stations and hits")
    fig.suptitle(f"{sample}  ({cut})" if sample else cut, fontsize=9)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def plot_composition(runs, out: Path, sample: str):
    """Test 2. Purity is only readable next to selectivity, so they share a row."""
    panels = [
        ("purity", "purity", "hits of the muon / hits of the pattern",
         np.linspace(0, 1, 21)),
        ("selectivity", "selectivity", "hits taken / hits available in those chambers",
         np.linspace(0, 1, 21)),
        ("mismatched", "mismatched fraction", "hits of another muon / hits of the pattern",
         np.linspace(0, 0.5, 21)),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.2))
    for ax, (column, title, xlabel, bins) in zip(axes, panels):
        for label, _, patterns in runs:
            values = patterns.loc[patterns["isMatch"], column].dropna()
            if values.empty:
                continue
            ax.hist(values, bins=bins, histtype="step", lw=1.3,
                    label=f"{label}: {values.mean():.3f}")
        ax.set_title(title, fontsize=10)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("patterns")
        ax.legend(loc="upper left", fontsize=7)
    if sample:
        fig.suptitle(sample, fontsize=10)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def plot_pulls(runs, out: Path, sample: str):
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
    ax.set_title("mean squared pull", fontsize=10)
    ax.set_xlabel("mean squared pull of the muon's hits about its truth line")
    ax.set_ylabel("patterns")
    if sample:
        fig.suptitle(sample, fontsize=10)
    ax.legend(loc="upper right", fontsize=7)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def plot_direction(runs, out: Path, sample: str):
    """Test 5. The phi residual is split on whether the finder measured phi.

    With no phi-measuring hit the finder assigns the centre of the sector rather
    than an estimate, so those patterns are spread over the sector width however
    good they are and are drawn apart from the rest.
    """
    fig, axes = plt.subplots(1, 2, figsize=(8.5, 3.4))
    for label, muons, patterns in runs:
        found = muons[muons["selected"] & muons["found"]]
        if found.empty:
            continue
        values = found["dEta"].dropna()
        axes[0].hist(values, bins=np.linspace(-0.1, 0.1, 61), histtype="step",
                     lw=1.3, label=f"{label}: {values.mean():+.4f} "
                                   f"$\\pm$ {values.std():.4f}")
        measured = patterns.loc[patterns["isMatch"] & (patterns["nPhiLayers"] > 0),
                                ["event", "truthMuon"]]
        has_phi = found.merge(measured.rename(columns={"truthMuon": "muon"}),
                              on=["event", "muon"], how="inner")["dPhi"].dropna()
        for subset, style, tag in ((has_phi, "-", "phi measured"),
                                   (found["dPhi"].dropna(), ":", "all")):
            if subset.empty:
                continue
            axes[1].hist(subset, bins=np.linspace(-0.2, 0.2, 61), histtype="step",
                         lw=1.3, ls=style,
                         label=f"{label}, {tag}: {subset.std():.4f}")
    axes[0].set_title(r"$\eta$ residual", fontsize=10)
    axes[1].set_title(r"$\phi$ residual", fontsize=10)
    axes[0].set_xlabel(r"$\eta_\mathrm{pattern}-\eta_\mathrm{truth\ muon}$")
    axes[1].set_xlabel(r"$\phi_\mathrm{pattern}-\phi_\mathrm{truth\ muon}$ [rad]")
    for ax in axes:
        ax.set_ylabel("muons")
        ax.legend(loc="upper left", fontsize=7)
    if sample:
        fig.suptitle(sample, fontsize=10)
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
    p.add_argument("--sample", default="",
                   help="Named in the title of every figure, e.g. PG0")
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
    plot_efficiency(runs, args.output_dir / "efficiency.png", args.sample)
    plot_composition(runs, args.output_dir / "composition.png", args.sample)
    plot_pulls(runs, args.output_dir / "pulls.png", args.sample)
    plot_direction(runs, args.output_dir / "direction.png", args.sample)
    print(f"Wrote the figures to {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
