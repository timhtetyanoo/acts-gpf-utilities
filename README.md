# ACTS muon global pattern finder utilities

Scripts to run the muon global pattern finder of
[ACTS](https://github.com/acts-project/acts) on the CPU and the GPU, and to
evaluate its physics and computational performance.

The pattern finder and the programs that run it are part of ACTS. This
repository runs them over the samples, validates the patterns against the truth
and compares runs. Each step reads only the output of the previous one, so the
evaluation can be changed without running the pattern finder again.

## Pipeline

| step | script | output |
| --- | --- | --- |
| 1 | `scripts/run/run_finder.sh` | patterns, time per event and resource usage |
| 2 | `scripts/validation/run_validation.sh` | physics metrics and figures |
| 3 | `scripts/compare/run_compare.sh` | comparison of two runs |
| 4 | `scripts/run/run_throughput.sh` | events per second against the number of threads |

Steps 1 and 4 require an ACTS build. Every script lists its options with `--help`.

- [docs/physics_performance.md](docs/physics_performance.md): truth matching,
  metrics and figures.
- [docs/computational_performance.md](docs/computational_performance.md):
  timing, resource utilisation and throughput.

## Requirements

- An ACTS build with `bin/ActsUnitTestGlobalPatternFinderData`, and for the GPU
  one configured with `-DACTS_BUILD_EXAMPLES_CUDA_GLOBAL_PATTERN_FINDER=ON`,
  which provides `bin/ActsUnitTestCudaGlobalPatternFinderData`.
- Python 3.10 or newer with the packages in `requirements.txt`, for example from
  an LCG release.
- `nvidia-smi` for the GPU resource usage.

## Inputs

The space point n-tuples are written by the Athena `MuonActsDump` package and the
tracking geometry by the ACTS JSON geometry converter. They are not tracked and
are expected in `data/`:

```text
data/ParticleGun_MU0.root           PG0, no pile-up
data/ParticleGun_MU200.root         PG200, pile-up 200
data/ActsTrackingGeometry_PG0.json
data/ActsTrackingGeometry_PG200.json
```

Each n-tuple must be used with the geometry exported alongside it.

Some `MuonActsDump` versions write the two local covariances of a space point in
the wrong order. `scripts/fix_ntuple_covariance.py` corrects such a file into a
copy. The files in `data/` are already corrected.

## Usage

```bash
scripts/run/run_finder.sh --config configs/cpu_pg0.conf --name cpu_pg0_all
scripts/run/run_finder.sh --config configs/cuda_pg0.conf --name cuda_v2_pg0_all
scripts/validation/run_validation.sh --name cpu_pg0_all
scripts/validation/run_validation.sh --name cuda_v2_pg0_all
scripts/compare/run_compare.sh --reference cpu_pg0_all --compare cuda_v2_pg0_all

scripts/run/run_throughput.sh --config configs/cuda_pg200.conf --name throughput_cuda_pg200 --events all
```

A configuration in `configs/` sets the backend, the sample and its inputs.
Command-line options take precedence over the configuration:

| option | |
| --- | --- |
| `--name` | name of the run |
| `--events N\|all`, `--repetitions N` | events per repetition, number of repetitions |
| `--backend cpu\|cuda`, `--build-dir DIR` | implementation and ACTS build |
| `--seed-from-mdt`, `--seed-from-inner` | additional seeds from MDT hits or the inner station |
| `--workspace-mb N` | GPU memory for the patterns of an event |
| `--threads "1 2 4"` | thread counts of the throughput test |

The full list is in `scripts/gpf_common.sh`.

## Results

Each run is written to `results/<host>/<name>/` and a comparison to
`results/<host>/compare/<reference>_vs_<compare>/`:

```text
run_info.txt     settings, inputs, ACTS revision, machine and dates
patterns.root    patterns found by the run
performance/     time per event, resource usage and figures
validation/      metrics, figures and the tables they are computed from
```

Only the summaries are tracked in git: `run_info.txt`, `scores.csv`,
`metrics.log`, `summary.csv`, `throughput.csv` and the figures. Patterns, tables,
raw timings and logs remain local.

`results/at-tdaq-mldev02/` holds the evaluation on the full samples:

| runs | |
| --- | --- |
| `cpu_<sample>_all`, `cuda_v2_<sample>_all` | CPU and GPU, default configuration |
| `cuda_v1_<sample>_all` | initial GPU implementation |
| `*_innerseeds_all`, `*_mdtseeds_all` | additional seeds from the inner station or MDT hits |
| `throughput_cpu_pg200`, `throughput_cuda_pg200` | throughput, 1 to 12 threads |

`results/at-tdaq-mldev01/` repeats the default CPU and GPU runs on a second
machine.

## Repository layout

```text
configs/               one configuration per backend and sample
docs/                  physics and computational performance
scripts/gpf_common.sh  shared options and paths
scripts/run/           running the pattern finder, timing and throughput
scripts/validation/    truth matching, metrics and figures
scripts/compare/       comparison of runs
results/<host>/        runs, summaries tracked
data/                  inputs, not tracked
```
