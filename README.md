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
    run_global_pattern_validation.sh   run the finder over the configured samples
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

## Planned

- truth preprocessing from the `MuonTruth` tree into per-event, per-muon
  geometry identifier sets;
- scoring of efficiency, duplicates, fakes and hit purity into one csv row per
  case;
- comparison of two runs hit by hit, for the CPU against the CUDA version;
- timing campaign and the corresponding plots.

## Reproducibility

Record the ACTS revision, the revision of this repository, the input files, the
build configuration and, for timings, the machine, the GPU model and the number
of repetitions together with any published numbers.
