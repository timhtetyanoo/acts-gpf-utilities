#!/usr/bin/env python3
"""The figures of the pattern finder validation, one quantity per file.

Naming follows ACTS's own validation tools. `EffPlotTool` and `ResPlotTool` name
a histogram after the quantity and then the variable it is binned against,

    trackeff_vs_eta        res_d0_vs_eta        pull_qop

and title it with the quantity plus the selection applied. Manfred's utilities
add the case to the file name, since figures get copied out of the directory
they were made in. Both are followed here:

    <sample>_patteff_vs_eta.png     <sample>_purity.png
    <sample>_patteff_vs_pt.png      <sample>_selectivity.png
    <sample>_res_eta.png            <sample>_mismatched.png
    <sample>_res_phi.png            <sample>_pull_truthline.png

An axis carries the name of its quantity, not its definition; what each one
means is in docs/validation.md.

Input is one or more directories holding `muon_flags.parquet` and
`pattern_flags.parquet`, written by compute_metrics.py. Several directories are
drawn on top of each other, which is how a CUDA run is compared with the CPU
reference. Test 4, fakes and duplicates, is counts and lives in the csv.
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

#: Figure size of a single quantity, wide enough for a legend
FIGSIZE = (4.6, 3.4)


def figure(sample: str, title: str, xlabel: str, ylabel: str):
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.set_title(f"{sample}: {title}" if sample else title, fontsize=10)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    return fig, ax


def path(out_dir: Path, sample: str, name: str) -> Path:
    """`<sample>_<quantity>.png`, so a figure identifies itself once copied."""
    return out_dir / (f"{sample}_{name}.png" if sample else f"{name}.png")


def save(fig, out: Path):
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


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


def plot_efficiency(runs, sample, out_dir: Path):
    """Test 1, binned against truth quantities as EffPlotTool does.

    No acceptance cut is applied, so the edge of the spectrometer's coverage
    shows as the curve falling rather than being removed by a threshold.
    """
    for name, column, bins, xlabel in (
            ("patteff_vs_eta", "eta", np.linspace(-3.0, 3.0, 31), r"truth $\eta$"),
            ("patteff_vs_pt", "pt", np.linspace(0.0, 100.0, 21),
             r"truth $p_\mathrm{T}$ [GeV]")):
        fig, ax = figure(sample, "pattern efficiency", xlabel, "efficiency")
        for label, muons, _ in runs:
            x, y, e = efficiency_profile(muons, column, bins)
            ax.errorbar(x, y, yerr=e, marker="o", ms=3, lw=1, label=label)
        ax.set_ylim(0.0, 1.05)
        ax.legend(loc="lower right", fontsize=8)
        save(fig, path(out_dir, sample, name))


def plot_fraction(runs, sample, out_dir: Path, name, column, title, bins):
    """Test 2. One quantity per figure, the axis carrying its name."""
    fig, ax = figure(sample, title, title, "patterns")
    drawn = False
    for label, _, patterns in runs:
        values = patterns.loc[patterns["isMatch"], column].dropna()
        if values.empty:
            continue
        drawn = True
        ax.hist(values, bins=bins, histtype="step", lw=1.3,
                label=f"{label}: mean {values.mean():.3f}")
    if not drawn:
        plt.close(fig)
        return
    ax.legend(loc="upper left", fontsize=8)
    save(fig, path(out_dir, sample, name))


def plot_pull(runs, sample, out_dir: Path):
    """Test 3. One is the value hits lying on the muon's path should give."""
    fig, ax = figure(sample, "pattern hits about the truth line",
                     "mean squared pull", "patterns")
    drawn = False
    bins = np.logspace(-2, 4, 49)
    for label, _, patterns in runs:
        values = patterns.loc[patterns["isMatch"], "meanSqPull"].dropna()
        if values.empty:
            continue
        drawn = True
        ax.hist(values.clip(bins[0], bins[-1]), bins=bins, histtype="step",
                lw=1.3, label=f"{label}: median {values.median():.2f}")
    if not drawn:
        plt.close(fig)
        return
    ax.axvline(1.0, color="0.4", ls="--", lw=0.9)
    ax.set_xscale("log")
    ax.legend(loc="upper right", fontsize=8)
    save(fig, path(out_dir, sample, "pull_truthline"))


def plot_residuals(runs, sample, out_dir: Path):
    """Test 5, named as ResPlotTool names a residual.

    The phi residual is split on whether the finder had a phi-measuring hit:
    without one it assigns the centre of the sector rather than an estimate, so
    those patterns are spread over the sector width however good they are.
    """
    fig, ax = figure(sample, "pattern direction",
                     r"$\eta_\mathrm{pattern}-\eta_\mathrm{truth}$", "muons")
    for label, muons, _ in runs:
        values = muons.loc[muons["found"], "dEta"].dropna()
        if values.empty:
            continue
        ax.hist(values, bins=np.linspace(-0.1, 0.1, 61), histtype="step", lw=1.3,
                label=f"{label}: {values.mean():+.4f} $\\pm$ {values.std():.4f}")
    ax.legend(loc="upper left", fontsize=8)
    save(fig, path(out_dir, sample, "res_eta"))

    fig, ax = figure(sample, "pattern direction",
                     r"$\phi_\mathrm{pattern}-\phi_\mathrm{truth}$ [rad]", "muons")
    for label, muons, patterns in runs:
        found = muons[muons["found"]]
        if found.empty:
            continue
        measured = patterns.loc[patterns["isMatch"] & (patterns["nPhiLayers"] > 0),
                                ["event", "mainMuon"]].rename(
                                    columns={"mainMuon": "muon"})
        with_phi = found.merge(measured, on=["event", "muon"],
                               how="inner")["dPhi"].dropna()
        for values, style, tag in ((with_phi, "-", "phi measured"),
                                   (found["dPhi"].dropna(), ":", "all patterns")):
            if values.empty:
                continue
            ax.hist(values, bins=np.linspace(-0.2, 0.2, 61), histtype="step",
                    lw=1.3, ls=style,
                    label=f"{label}, {tag}: {values.std():.4f}")
    ax.legend(loc="upper left", fontsize=7)
    save(fig, path(out_dir, sample, "res_phi"))


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
    plot_efficiency(runs, args.sample, args.output_dir)
    for name, column, title, bins in (
            ("purity", "purity", "purity", np.linspace(0, 1, 21)),
            ("selectivity", "selectivity", "selectivity", np.linspace(0, 1, 21)),
            ("mismatched", "mismatched", "mismatched fraction",
             np.linspace(0, 0.5, 21))):
        plot_fraction(runs, args.sample, args.output_dir, name, column, title, bins)
    plot_pull(runs, args.sample, args.output_dir)
    plot_residuals(runs, args.sample, args.output_dir)
    print(f"Wrote the figures to {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
