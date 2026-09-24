# ACTS muon global pattern finder utilities

Validation and benchmarking tooling around the muon global pattern finder in
[ACTS](https://github.com/acts-project/acts). The algorithm, its unit tests and
the run entry point stay in ACTS; this repository keeps the scripts that drive
them, score the output and draw the plots.

The CPU example is the reference against which the CUDA implementation will be
validated, so every script is written to take the implementation as a parameter.

## Contents

```text
scripts/
  validation/
    run_full_validation.sh             the whole chain, every stage skippable
    run_global_pattern_validation.sh   run the finder over the configured samples
    preprocess_truth.py                truth tree -> compact per muon geometry ids
    score_patterns.py                  patterns + truth -> one csv row per case
    compare_patterns.py                two runs, hit by hit (cpu against cuda)
    plot_performance.py                figures from the csv & the pattern files
plots/
```

## Requirements

- Bash;
- an ACTS build containing `ActsUnitTestGlobalPatternFinderData`;
- Python 3.10 or newer with uproot, numpy, pandas and matplotlib;
- the Athena-exported space point n-tuples and the matching tracking geometry.

## Inputs

The n-tuples are written by Athena's `MuonActsDump/SpacePointWriter`
(tree `MuonSpacePoints`), the geometry by the ACTS tracking geometry json
converter. A typical data directory holds:

```text
ParticleGun_MU0.root
ParticleGun_MU200.root
ActsTrackingGeometry.json
```

## Running the pattern finder

```bash
export ACTS_BUILD_DIR=/path/to/acts/build
export GPF_DATA_DIR=/path/to/data

scripts/validation/run_global_pattern_validation.sh
```

Each case writes `patterns_<sample>_<implementation>.root` and a log into
`${GPF_OUT_DIR}` (by default `${GPF_DATA_DIR}/gpf_validation`). Finished cases
are skipped, so the script can be re-run after adding a sample.

Overrides: `GPF_SAMPLES`, `GPF_IMPLEMENTATIONS`, `GPF_MAX_EVENTS`,
`GPF_GEOMETRY`, `GPF_OUT_DIR`, `GPF_<SAMPLE>_NTUPLE` and `GPF_FORCE`.

A quick check on a handful of events:

```bash
GPF_SAMPLES=PG0 GPF_MAX_EVENTS=5 scripts/validation/run_global_pattern_validation.sh
```

## Output

One entry per event, holding every pattern of that event:

| branch group | contents |
| --- | --- |
| `event_id` | index of the event in the input file |
| `pattern_*` | sector, theta, phi, precision / trigger / phi layer counts, mean normalized residual squared, number of hits |
| `hit_*` | pattern index, station, geometry identifier, muon identifier, bucket identifier and index within the bucket |

The geometry and muon identifiers carry the truth matching, the bucket
identifier and the index within the bucket identify a hit across runs, which is
what the comparison between implementations is based on.

## The whole chain

```bash
export ACTS_BUILD_DIR=/path/to/acts/build
export GPF_DATA_DIR=/path/to/data

scripts/validation/run_full_validation.sh
```

It runs the four stages below and leaves `scores.csv` and the figures in the
output directory. Stages whose output exists are skipped; `GPF_FORCE=1` redoes
them.

### Truth

```bash
scripts/validation/preprocess_truth.py ParticleGun_MU0.root truth_PG0.parquet
```

Reads the truth tree and writes `event, muon, station, geo_id`. The branch
names differ between exports, so they are detected from the file and can be
overridden; `--list` prints the trees and branches the file actually holds.

Matching is by geometry identifier because the export carries no per space
point truth link. One identifier covers several space points of a layer, hence
the distinct identifiers are counted, never the hits.

### Scores

```bash
scripts/validation/score_patterns.py patterns_PG0_cpu.root truth_PG0.parquet \
  --sample PG0 --implementation cpu --output scores.csv
```

A pattern and a muon match when they share at least `--min-shared` identifiers,
3 by default. Per case it reports the muon efficiency, duplicates per muon, the
fake fraction, and the purity and completeness of the matched hits, and appends
one row to the csv.

### Comparison of two runs

```bash
scripts/validation/compare_patterns.py patterns_PG0_cpu.root patterns_PG0_cuda.root
```

The primary check for the CUDA version: a pattern is identified by the set of
hits it holds, and a hit by its place in the input container (bucket and index
within it), which is stable across runs. The script exits non-zero when the two
runs disagree, so it can be used as a regression gate.

### Figures

```bash
scripts/validation/plot_performance.py --scores scores.csv \
  --patterns patterns_*.root --output-dir plots
```

One bar chart per metric across the cases, plus the sanity distributions of the
patterns themselves: theta, phi, sector, hits per pattern, layer counts and
patterns per event.

## Planned

- timing campaign and the corresponding plots;
- energy measurements, once the CUDA version exists.

## Reproducibility

Record the ACTS revision, the revision of this repository, the input files, the
build configuration and, for timings, the machine, the GPU model and the number
of repetitions together with any published numbers.
