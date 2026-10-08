#!/usr/bin/env python3
"""Where the time of the CPU global pattern finder goes, and how parallel each
part is, from the records of the profiling build (seeds.csv, events.csv).

The events are split by their time into the bulk, up to the 99th percentile,
and the tail above it: busy events behave differently. For each group:

  stages      the time of every stage, its share of the group's time and its
              mean per event
  over seeds  the work of building the seeds against the longest single seed
              of the event: the speedup of that work if every seed ran at once
  in a seed   the pattern-hit tests of the extension against the steps that
              stay in order if the hits of a layer are tested together and the
              backward passes run side by side (change 1 of the v2 design)
  in order    the parts that depend on the order of the seeds: the skip rule,
              the second chance and the final overlap removal

Writes report.txt, stages.csv and stages.png next to the records. Their times
are in milliseconds; the records are in microseconds.
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

#: The work of building one seed, which does not depend on the other seeds
SEED_BUILD = ["tSearch", "tChecks", "tForward", "tBackward", "tPassResolve",
              "tSeedResolve", "tFinalize"]
#: The parts of a seed that depend on the seeds before it
SEED_ORDERED = ["tSkipCount", "tSecondChance"]

#: Stage name -> how to compute it per event from the event table
STAGES = {
    "hit payloads": "tPayloads",
    "search tree": "tTree",
    "skip rule": "tSkipCount",
    "second chance": "tSecondChance",
    "window search": "tSearch",
    "seed checks": "tChecks",
    "forward extension": "tForward",
    "backward extension": "tBackward",
    "overlaps after a pass": "tPassResolve",
    "overlaps in a seed": "tSeedResolve",
    "pattern cuts": "tFinalize",
    "rest of the seed loop": "loopRest",
    "final overlaps": "tFinalResolve",
    "phi-only hits": "tPhiOnly",
    "conversion": "conversion",
    "rest": "rest",
}
#: Stages that are independent per seed, and those that follow the seed order
PER_SEED = ["window search", "seed checks", "forward extension",
            "backward extension", "overlaps after a pass", "overlaps in a seed",
            "pattern cuts"]
IN_ORDER = ["skip rule", "second chance", "final overlaps"]


def load(directory: Path):
    seeds = pd.read_csv(directory / "seeds.csv")
    events = pd.read_csv(directory / "events.csv")

    seeds["build"] = seeds[SEED_BUILD].sum(axis=1)
    seeds["seedRest"] = seeds["tTotal"] - seeds[SEED_BUILD + SEED_ORDERED].sum(axis=1)
    # Under change 1 a seed takes one step per layer forward, and the backward
    # passes run side by side, so they add the layers of one pass
    passes = seeds["nBackwardPasses"].clip(lower=1)
    seeds["hitSteps"] = seeds["forwardHits"] + seeds["backwardHits"]
    seeds["layerSteps"] = seeds["forwardLayers"] + seeds["backwardLayers"] / passes
    seeds["tests"] = seeds["forwardTests"] + seeds["backwardTests"]
    seeds["extension"] = seeds["tForward"] + seeds["tBackward"]

    per_event = seeds.groupby("event").agg(
        **{c: (c, "sum") for c in SEED_BUILD + SEED_ORDERED + ["tTotal", "build"]},
        maxBuild=("build", "max"),
        secondChances=("secondChance", "sum"),
        secondChancePairs=("secondChancePairs", "sum"),
        passResolvePairs=("passResolvePairs", "sum"),
        seedResolvePairs=("seedResolvePairs", "sum"),
        built=("reached", lambda r: int((r == 5).sum())),
    )
    events = events.merge(per_event, left_on="event", right_index=True, how="left")
    events = events.fillna(0.0)
    events["loopRest"] = events["tSeedLoop"] - events["tTotal"]
    events["conversion"] = events["tConvertCore"] + events["tConvertAlg"]
    known = [c for name, c in STAGES.items() if name != "rest"]
    events["rest"] = events["tExecute"] - events[known].sum(axis=1)
    return seeds, events


def groups(events: pd.DataFrame):
    cut = events["tExecute"].quantile(0.99)
    return {
        "all": events,
        "bulk (to p99)": events[events["tExecute"] <= cut],
        "tail (above p99)": events[events["tExecute"] > cut],
    }


def stage_table(events: pd.DataFrame) -> pd.DataFrame:
    total = events["tExecute"].sum()
    rows = []
    for name, column in STAGES.items():
        t = events[column].sum()
        rows.append({"stage": name, "total (ms)": t / 1e3,
                     "share (%)": 100.0 * t / total if total > 0 else 0.0,
                     "mean per event (ms)": t / max(len(events), 1) / 1e3})
    return pd.DataFrame(rows)


def share(events: pd.DataFrame, names) -> float:
    total = events["tExecute"].sum()
    return sum(events[STAGES[n]].sum() for n in names) / total if total > 0 else 0.0


def report(seeds: pd.DataFrame, events: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    lines = [f"{len(events)} events, {int(events['nSeeds'].sum())} seeds, "
             f"{int(events['built'].sum())} of them built", ""]
    tables = []
    for label, g in groups(events).items():
        if g.empty:
            continue
        ids = set(g["event"])
        s = seeds[seeds["event"].isin(ids) & (seeds["reached"] == 5)]
        t = stage_table(g)
        t.insert(0, "group", label)
        tables.append(t)

        lines.append(f"=== {label}: {len(g)} events, "
                     f"{g['tExecute'].sum() / 1e3:.1f} ms in total, "
                     f"mean {g['tExecute'].mean() / 1e3:.2f} ms, "
                     f"median {g['tExecute'].median() / 1e3:.2f} ms per event")
        lines.append(t.drop(columns="group").to_string(
            index=False, float_format=lambda v: f"{v:.3f}"))

        per_seed = share(g, PER_SEED)
        in_order = share(g, IN_ORDER)
        lines.append("")
        lines.append(f"  independent per seed   {100 * per_seed:5.1f} % of the time")
        lines.append(f"  in seed order          {100 * in_order:5.1f} % "
                     "(skip rule, second chance, final overlaps)")
        rest = 1.0 - per_seed
        lines.append(f"  everything else        {100 * rest:5.1f} %: with the "
                     "per-seed work made free, the event is at most "
                     f"{1 / rest:.1f}x faster" if rest > 0 else "")

        built = g[g["maxBuild"] > 0]
        if not built.empty:
            over_seeds = built["build"] / built["maxBuild"]
            lines.append(
                "  over seeds             work / longest seed: "
                f"{built['build'].sum() / built['maxBuild'].sum():.1f}x time-weighted, "
                f"median event {over_seeds.median():.1f}x; the longest seed "
                f"holds {100 * (built['maxBuild'] / built['build']).median():.0f} % "
                "of an event's seed work (median)")
        if not s.empty and s["layerSteps"].sum() > 0:
            width = s["tests"] / s["layerSteps"].clip(lower=1)
            w = s["extension"]
            order = np.argsort(width.to_numpy())
            cum = np.cumsum(w.to_numpy()[order]) / max(w.sum(), 1e-12)
            weighted_median = width.to_numpy()[order][np.searchsorted(cum, 0.5)]
            lines.append(
                "  in a seed              steps in order: "
                f"{s['hitSteps'].sum() / s['layerSteps'].sum():.1f}x fewer as layers "
                "than as hits; pattern-hit tests per layer step: "
                f"{s['tests'].sum() / s['layerSteps'].sum():.1f} on average, "
                f"{weighted_median:.1f} for the median of extension time; "
                f"widest beam {int(s['maxBeam'].max())}, median seed "
                f"{s['maxBeam'].median():.0f}")
        lines.append(
            "  overlap pairs          after a pass "
            f"{int(g['passResolvePairs'].sum())}, in a seed "
            f"{int(g['seedResolvePairs'].sum())}, second chance "
            f"{int(g['secondChancePairs'].sum())} in "
            f"{int(g['secondChances'].sum())} calls, final "
            f"{int(g['finalResolvePairs'].sum())}")
        lines.append("")
    return "\n".join(lines), pd.concat(tables, ignore_index=True)


def plot(table: pd.DataFrame, path: Path) -> None:
    pivot = table.pivot(index="group", columns="stage", values="share (%)")
    pivot = pivot[[s for s in STAGES if s in pivot.columns]]
    fig, ax = plt.subplots(figsize=(10, 1.2 + 0.8 * len(pivot)))
    left = np.zeros(len(pivot))
    colours = plt.get_cmap("tab20")(np.linspace(0, 1, len(pivot.columns)))
    for colour, stage in zip(colours, pivot.columns):
        values = pivot[stage].to_numpy()
        ax.barh(pivot.index, values, left=left, color=colour, label=stage)
        left += values
    ax.set_xlabel("share of the group's time (%)")
    ax.set_xlim(0, 100)
    ax.legend(ncol=4, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.25))
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path,
                        help="folder of seeds.csv and events.csv")
    args = parser.parse_args()

    seeds, events = load(args.directory)
    text, table = report(seeds, events)
    (args.directory / "report.txt").write_text(text + "\n")
    table.to_csv(args.directory / "stages.csv", index=False)
    plot(table, args.directory / "stages.png")
    print(text)
    print(f"Wrote {args.directory}/report.txt, stages.csv and stages.png")


if __name__ == "__main__":
    main()
