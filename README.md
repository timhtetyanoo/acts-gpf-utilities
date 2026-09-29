# ACTS muon global pattern finder utilities

Validation and benchmarking tooling around the muon global pattern finder in
[ACTS](https://github.com/acts-project/acts). The algorithm, its unit tests and
the run entry point stay in ACTS; this repository keeps the scripts that drive
them, measure the output and draw the plots.

The CPU example is the reference against which the CUDA implementation will be
validated, so every script takes the implementation as a parameter.

The chain follows Athena's `MuonFastRecoTester`: one stage produces numbers and
nothing else, a later stage decides what those numbers mean. A change to the
definition of "the pattern found the muon" therefore never requires running the
pattern finder again.

## Contents

```text
scripts/
  validation/
    run_full_validation.sh             the whole chain, every stage skippable
    run_global_pattern_validation.sh   run the finder over the configured samples
    gpfval.py                          definitions transcribed from ACTS & Athena
    build_validation_tables.py         patterns + truth -> the validation tables
    compute_metrics.py                 the tables -> efficiency, fakes, residuals
    make_plots.py                      the four figures
    compare_patterns.py                two runs, hit by hit (cpu against cuda)
docs/
  acts_changes.md                      what this work changed in the ACTS checkout
```

## Requirements

- Bash;
- an ACTS build containing `ActsUnitTestGlobalPatternFinderData`, for stage 1
  only; the analysis stages need no build;
- Python 3.10 or newer with the packages of `requirements.txt`;
- the Athena-exported n-tuples and the matching tracking geometry.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

The scripts default to `.venv/bin/python` and fall back to `python3`.

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

## The whole chain

```bash
export ACTS_BUILD_DIR=/path/to/acts/build   # omit to analyse existing pattern files

scripts/validation/run_full_validation.sh
```

Stages whose output exists are skipped; `GPF_FORCE=1` redoes them. Stage 1 needs
the build machine, stages 2 to 5 run anywhere.

Everything is written into `gpf_validation/` of this repository. The pattern
files, `scores.csv`, the logs and the figures are tracked, so a run is
transferred with a commit and a push; the tables are large and regenerable and
are ignored. The last stage warns about any tracked
output above 50 MB, since GitHub refuses files above 100 MB.

### 1. The patterns

```bash
scripts/validation/run_global_pattern_validation.sh
```

Each case writes `patterns_<sample>_<implementation>.root` and a log into
`${GPF_OUT_DIR}` (by default `gpf_validation/` of this repository). Overrides:
`GPF_SAMPLES`, `GPF_IMPLEMENTATIONS`, `GPF_MAX_EVENTS`, `GPF_GEOMETRY`,
`GPF_OUT_DIR`, `GPF_<SAMPLE>_NTUPLE` and `GPF_FORCE`.

### 2. The validation tables

```bash
scripts/validation/build_validation_tables.py patterns_PG0_cpu.root \
  ParticleGun_MU0.root tables_PG0_cpu
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

### 3. The metrics

```bash
scripts/validation/compute_metrics.py tables_PG0_cpu --sample PG0 \
  --implementation cpu --scan --output scores.csv
```

Applies the definitions and appends one row to the csv, writing `muon_flags` and
`pattern_flags` next to the tables. The matching criterion is ACTS's, from
`TrackTruthMatcher`: a majority of the muon's surfaces *and* a majority of the
pattern's hits, both at 0.5. `--scan` shows how the numbers move with it.

### 4. The figures

```bash
scripts/validation/make_plots.py tables_PG0_cpu tables_PG0_cuda \
  --labels cpu cuda --output-dir plots/PG0
```

One quantity per figure, named as ACTS's own validation tools name their
histograms — the quantity first, then the variable it is binned against, with
the sample prefixed so a figure identifies itself once copied out:

```text
PG0_patteff_vs_eta.png    PG0_purity.png         PG0_pull_truthline.png
PG0_patteff_vs_pt.png     PG0_selectivity.png    PG0_res_eta.png
                          PG0_mismatched.png     PG0_res_phi.png
```

An axis carries the name of its quantity, not its definition; what each one
means is in [docs/validation.md](docs/validation.md). Fakes and duplicates are
counts and live in the csv. Several table directories are overlaid, which is how CUDA is
compared with the CPU reference.

### 5. Comparison of two runs

```bash
scripts/validation/compare_patterns.py patterns_PG0_cpu.root patterns_PG0_cuda.root
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
once the CUDA version is known to differ, rather than ignoring a red exit. The
driver runs the comparison by itself as soon as `GPF_IMPLEMENTATIONS` names more
than one implementation, taking the first as the reference.

It answers a different question from stage 5. This one asks how far the two runs
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

Ours, since Athena defines nothing and only stores counts. A pattern matches its
main muon when it collected at least `--min-completeness` of that muon's
findable precision hits and holds hits of it in at least `--min-stations`
stations. The second mirrors the `minGroups` of the finder: a pattern confined
to one station is not a muon candidate.

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

- timing campaign and the corresponding plots;
- energy measurements, once the CUDA version exists.

## Reproducibility

Record the ACTS revision, the revision of this repository, the input files, the
build configuration and, for timings, the machine, the GPU model and the number
of repetitions together with any published numbers.
