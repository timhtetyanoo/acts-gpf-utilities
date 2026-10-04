# ACTS muon global pattern finder utilities

Validation and benchmarking tooling around the muon global pattern finder in
[ACTS](https://github.com/acts-project/acts). The algorithm, its unit tests and
the run entry point stay in ACTS; this repository keeps the scripts that drive
them, measure the output and draw the plots.

The CPU example is the reference against which the CUDA implementation will be
validated: each implementation is a named run with its own build, and the
comparison takes two runs by name.

The chain follows Athena's `MuonFastRecoTester`: one stage produces numbers and
nothing else, a later stage decides what those numbers mean. A change to the
definition of "the pattern found the muon" therefore never requires running the
pattern finder again.

## Contents

```text
scripts/
  gpf_common.sh                        shared helpers: flags, config, python, n-tuples
  run/
    run_finder.sh                      STEP 1: run the finder -> patterns + timing
    aggregate_event_timing.py          C++ per-event csv -> summary
    plot_event_timing.py               cost vs occupancy
  validation/
    run_validation.sh                  STEP 2: patterns + n-tuple -> metrics and figures
    gpfval.py                          definitions transcribed from ACTS & Athena
    build_validation_tables.py         patterns + truth -> the validation tables
    compute_metrics.py                 the tables -> efficiency, fakes, residuals
    make_plots.py                      the four figures
    to_fastreco_tuple.py               tables -> MuonFastRecoValidation n-tuple
    compare_patterns.py                two pattern files, hit by hit
  compare/
    run_compare.sh                     compare two runs and two validations
    compare_timing.py                  two timing summaries -> speedup table
configs/                               one config per run: its name, sample and build
results/                               everything the scripts write, ignored by git
docs/
  acts_changes.md                      what this work changed in the ACTS checkout
```

## Requirements

- Bash;
- an ACTS build containing `ActsUnitTestGlobalPatternFinderData`, for stage 1
  only; the analysis stages need no build;
- Python 3.10 or newer with the packages of `requirements.txt` and, for the
  FastReco tuple, ROOT: the LCG environment of `env_setup.sh` has all of them;
- the Athena-exported n-tuples and the matching tracking geometry.

Source `env_setup.sh` before running anything. The scripts use the `python3` of
that shell and nothing else; `PYTHON=` or `--python` names another interpreter.
There is no virtual environment.

## Inputs

The n-tuples are written by Athena's `MuonActsDump`: `SpacePointWriter` fills
the `MuonSpacePoints` tree, `TruthSegmentWriter` the `MuonTruth` tree. The
geometry comes from the ACTS tracking geometry json converter. They live in
`data/` of this repository, which is ignored by git, so every machine needs its
own copy:

```text
data/ParticleGun_MU0.root
data/ParticleGun_MU200.root
data/ActsTrackingGeometry.json
```

`GPF_DATA_DIR` points the scripts elsewhere.

## Runs, settings and results

A **run** has a name, and everything it produces goes into `results/<name>/`.
The name is the only thing that tells two runs apart, so give each run one that
says what it is: `cpu_pg0_all`, `cuda_pg200_500ev`. A config file holds one run:

```bash
# configs/cpu_pg0_all.conf
GPF_NAME=cpu_pg0_all
GPF_SAMPLE=PG0
GPF_EVENTS=all
GPF_REPETITIONS=3
ACTS_BUILD_DIR="$HOME/cern/acts/build"
```

Both steps and the comparison take their settings from flags, a config file or
environment variables. Where they disagree the order is

```text
flag  >  config file  >  environment variable  >  the script's default
```

so a config can be bent for one run from the command line:

```bash
scripts/run/run_finder.sh --config configs/cpu_pg0_all.conf
scripts/run/run_finder.sh --config configs/cpu_pg0_all.conf --name cpu_pg0_quick --events 100
scripts/validation/run_validation.sh --name cpu_pg0_quick
```

A config is plain bash assignments. The flags and the variable each one sets are
listed in `scripts/gpf_common.sh`, and `--help` prints the header of a script.

`results/` is ignored by git as a whole, so nothing a run writes is ever
tracked. `run_info.txt` in each run records the settings, the ACTS branch and
revision, the build and the date, which is what a result is quoted with.

```text
results/
  <name>/
    run_info.txt            what was run
    patterns.root           step 1: the finder's output, the input of step 2
    timing/                 step 1: summary.csv, events.csv, event_timing.png,
                            repetitions/ (raw)
    logs/                   step 1: finder output of each repetition
    validation/             step 2: scores.csv, metrics.log, plots/, tables/,
                            fastreco.root
  compare/
    <reference>_vs_<compare>/   patterns.log, plots/, scores.csv, speedup.csv
```

## Two steps

```text
STEP 1  scripts/run/run_finder.sh             run the finder     -> results/<name>/
STEP 2  scripts/validation/run_validation.sh  judge the patterns -> results/<name>/validation/
```

Step 1 is the only place the finder runs. Step 2 reads what step 1 wrote and
never starts the finder, so it needs no ACTS build and no tracking geometry and
can be repeated, changed or run on another machine for free. A change to the
definition of "the pattern found the muon" never requires running the finder
again. Both always redo everything: step 1 replaces the earlier run of the same
name, which also removes its validation, because it would no longer belong to the
new patterns.

### Step 1: run the finder

```bash
source ~/cern/env_setup.sh
scripts/run/run_finder.sh --config configs/cpu_pg0_all.conf
```

Runs `bin/ActsUnitTestGlobalPatternFinderData` over the sample, once per
repetition. Each repetition times every call of the finder and writes one row per
event; the first one also writes the pattern file. The timer wraps the finder call
only, so writing the patterns is not part of the measurement, and the finder logs
at WARNING because its own messages are. Defaults: sample PG0, 500 events, 3
repetitions, `../acts/build`.

The Sequencer entry point of ACTS,
`Examples/Scripts/Python/muon_global_pattern_finder.py`, reports a per
component total for a whole run and is there to be run by hand when that view
is wanted.

### Step 2: validate

```bash
scripts/validation/run_validation.sh --name cpu_pg0_all
```

Reads `results/<name>/patterns.root` and the input n-tuple (named in
`run_info.txt`) and writes tables, the FastReco tuple, `scores.csv` and the
physics plots into `results/<name>/validation/`. The FastReco tuple needs ROOT,
which the LCG environment provides; without it that stage is skipped and the rest
finishes.

### Comparison (after the fact)

```bash
scripts/compare/run_compare.sh --reference cpu_pg0_all --compare cuda_pg0_all
```

Takes two runs by name. The patterns of the two give the hit-by-hit gate, their
validations the overlaid figures and the metrics, their timings the speedup
table, all in `results/compare/<reference>_vs_<compare>/`. It runs no finder, and
a part is skipped when one of the runs lacks what it needs. Only compatible runs
are compared: the same sample, the same n-tuple and the same event count, read
from the `run_info.txt` of each. Otherwise it stops and says what differs.

The stages inside step 2, which can also be run one by one on the files of a run:

### 1. The validation tables

```bash
scripts/validation/build_validation_tables.py results/cpu_pg0_all/patterns.root \
  data/ParticleGun_MU0.root results/cpu_pg0_all/validation/tables
```

Three parquet tables. Nothing is extracted that no test consumes, and no
tracking geometry is involved: the hits and the truth lines are both given in
the frame of their spectrometer sector.

| table | one row per | contents |
| --- | --- | --- |
| `muons` | truth muon | pt, eta, phi, and how many of its surfaces produced a hit |
| `patterns` | pattern | which muon it belongs to, what it is made of, its direction |
| `pattern_chamber` | pattern and chamber | how far its hits sit from the muon's path |

Of the 36 branches in the truth tree it reads 7, and of the 25 in the space
point tree it reads 8. What each test needs and why is in
[docs/validation.md](docs/validation.md).

### 2. The metrics

```bash
scripts/validation/compute_metrics.py results/cpu_pg0_all/validation/tables \
  --sample PG0 --implementation cpu_pg0_all --scan --output scores.csv
```

Applies the definitions and appends one row to the csv, writing `muon_flags` and
`pattern_flags` next to the tables. The matching criterion is ACTS's, from
`TrackTruthMatcher`: a majority of the muon's surfaces *and* a majority of the
pattern's hits, both at 0.5. `--scan` shows how the numbers move with it.

### 3. The figures

```bash
scripts/validation/make_plots.py results/cpu_pg0_all/validation/tables \
  results/cuda_pg0_all/validation/tables \
  --labels cpu_pg0_all cuda_pg0_all --output-dir plots
```

One figure per test, with the quantities of that test side by side:

```text
efficiency.png     against truth pT and truth eta
composition.png    purity, selectivity, mismatched fraction
pulls.png          how far the hits sit from the muon's path
direction.png      the eta residual, and the phi residual
```

Fakes and duplicates are counts and live in the csv. What each panel means is
in [docs/validation.md](docs/validation.md). Several table directories are
overlaid, which is how CUDA is compared with the CPU reference.

### 4. Comparison of two pattern files

```bash
scripts/validation/compare_patterns.py results/cpu_pg0_all/patterns.root \
  results/cuda_pg0_all/patterns.root
```

Two runs over the same space points, compared. Nothing in it knows which
implementation wrote either file: the only requirement is that both runs read
the same n-tuple through the same reader. Comparing CUDA against the CPU
reference is one use of it; comparing two CPU runs across a change to the
finder, or two settings of the same run, is the same operation.

The hit is what ties the two files together, named by its place in the input
container — bucket and index within the bucket. That name is a property of the
input and not of the run, so it is stable across runs and independent of memory
addresses. Neither the order of the hits in a pattern nor the order of the
patterns in an event carries meaning.

Equality is not required. The patterns are paired with each other first,
greedily on the hits they share, and compared afterwards, so a pattern that lost
one borderline hit stays one pattern with a hit difference instead of being
reported as one missing and one appeared.

Per paired pattern: shared, lost and gained hits, their Jaccard overlap, and the
differences in theta, phi, sector, the three layer counts and the mean
normalized residual. Per run: the patterns paired with nothing. Events only one
run processed are named and then excluded, since counting their patterns as lost
would say nothing about the patterns. `--output` writes the pair table as
parquet for plotting.

The exit code is non-zero when the agreement falls below `--min-matched`,
`--min-jaccard` or `--tolerance`. The defaults demand exact agreement, which is
what a pure reordering of the same arithmetic gives; loosen them deliberately
once the CUDA version is known to differ, rather than ignoring a red exit.
`scripts/compare/run_compare.sh` runs it over the patterns of two runs.

It answers a different question from the figures of step 2. This one asks how far the two runs
drifted apart, hit by hit; the overlaid figures ask whether a run that drifted is
still as good physically. A red exit here is a reason to look at the figures, not
a verdict on its own.

## How the validation works

### Truth association

`MuonFastRecoTester` associates a measurement with a truth particle through the
sim hit behind it, `getTruthMatchedHit`. The export carries no such link, so a
hit belongs to a muon here when its geometry identifier is one of the
identifiers of that muon's truth segments, `Segments_hitGeoIds`, which
`TruthSegmentWriter` fills with the surfaces of exactly those sim hits.

The two differ in one direction only: a wrong hit on a right surface counts as
matched here and never does in Athena. An MDT identifier is a tube and a strip
identifier a gas gap, so the surface is fine-grained, but the statement is about
surfaces and not about hits and should be quoted that way next to Athena's
numbers.

### Which muon a pattern belongs to

The majority rule of `fillGlobPatternInfo`: the muon owning the most hits of the
pattern, decided over the whole pattern and not per station. The per-station
split exists in the tables for the analysis, exactly as it does in Athena.

### The truth denominator

Counted from the space points that exist and are matched, not from the truth
segments, because "we have sim hits that haven't made it into spacepoints due to
inefficiencies" (`MuonFastRecoTester.cxx`). Hits are deduplicated per layer of a
sector with the MDT straws exempt, the layer being the `detLayer` field of the
muon identifier, which the exporter fills with `sectorLayerNum()` — the quantity
Athena deduplicates on.

The pattern side is not deduplicated, in Athena either, so a ratio of the two
can exceed one where a layer holds several hits.

### What counts as found

The definitions of `MuonFastRecoValidation`, transcribed in `gpfval.py`, so that
the efficiency and the fake rate are the numbers its plots show for the same
patterns. A truth muon enters the efficiency when it lies inside |eta| < 2.4 and
above 10 GeV and left enough hits (two stations with four bending hits each, two
trigger hits in the middle and outer layers, eight precision hits). A pattern
matches its muon when it crosses more than half of the muon's stations and holds
more than half of its bending hits; the match with the most bending hits stands
for the muon, and a pattern that is not that match is a fake.
[docs/validation.md](docs/validation.md) has the full definition and where each
number comes from.

### The angular residuals

A pattern's theta is the polar angle of the global position of its seed hit,
`patTheta{VectorHelpers::theta(seed->globalPosition(gctx))}`, and is never
refitted. It is the angle of a point of the trajectory, not the direction of
one, so the residuals are

| residual | against |
| --- | --- |
| `dThetaSeg`, `dPhiSeg` | the position of the truth segment sharing the most identifiers with the pattern; the same kind of quantity, free of the bending |
| `dEtaMuon`, `dPhiMuon` | the truth muon at production, the pair Athena writes as `pat_Eta` and `gen_Eta`; the toroid bends the muon in between, so this is a sanity check |

`Segments_dirTheta` is deliberately unused: it is the direction of the segment,
which the pattern does not estimate.

## Known limits

- No pile-up truth particles. Both particle-gun samples carry only the one or
  two gun muons, so Athena's pile-up category cannot be reproduced and a pattern
  built from pile-up hits in MU200 is counted as a fake. Its hits appear as
  `nUnmatchedHits` of the pattern, which is the number to watch.
- sTGC precision. The export does not carry the channel type, so an sTGC space
  point counts as precision only when it measures eta alone. Athena calls a
  strip a precision hit either way.
- Athena demands, for a space point measuring both coordinates, that the second
  measurement carries the same truth link before counting it as a phi hit. One
  identifier covers the whole space point here, so a matched two dimensional hit
  counts for both coordinates.

## Planned

- energy measurements, once the CUDA version exists.

## Reproducibility

`results/<name>/run_info.txt` records the settings of a run, the n-tuple, the
build, the ACTS branch and revision (with a note when the checkout had local
changes), the revision of this repository, the machine, the GPU and the dates.
Quote it with any published number, and add the build configuration, which it
does not hold.
