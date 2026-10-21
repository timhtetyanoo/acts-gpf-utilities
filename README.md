# ACTS muon global pattern finder utilities

Scripts that run the muon global pattern finder of
[ACTS](https://github.com/acts-project/acts) on the CPU and on the GPU, measure its
speed, judge its patterns against the truth and compare two runs. The pattern
finder, its tests and the programs that run it live in ACTS;
[docs/acts_changes.md](docs/acts_changes.md) says which branch holds what.

Every stage reads what the stage before it wrote and nothing else. A change to how
the patterns are judged therefore never requires running the pattern finder again.

## The pipeline

| step | entry point | what it does | writes |
| --- | --- | --- | --- |
| 0 | ACTS unit tests | `ActsUnitTestCudaPatternFinder` checks the GPU functions against the CPU's; `ActsUnitTestGlobalPatternFinder` the CPU example's helpers | |
| 1 | `scripts/run/run_finder.sh` | runs the pattern finder (CPU or GPU) over a sample, a few times for timing | `patterns.root`, `performance/` |
| 2 | `scripts/validation/run_validation.sh` | matches the patterns to the truth muons, computes the metrics and figures | `validation/` |
| 3 | `scripts/compare/run_compare.sh` | puts two runs side by side: timing, metrics, figures, and the patterns hit by hit | `compare/<a>_vs_<b>/` |
| 4 | `scripts/validation/run_hough_plots.sh` | the figures of the ATLAS MuonFastRecoValidation package, for one run or several | `hough/` |
| 5 | `scripts/run/run_throughput.sh` | events per second against the number of threads | `throughput.csv` |

Steps 1 and 5 need an ACTS build; the others only read files. Step 4 needs an
Athena release and a locally changed MuonFastRecoValidation (see step 4).

## Quick start

```bash
source ~/cern/env_setup.sh            # LCG environment: python with ROOT, pandas, ...
cd ~/cern/acts-gpf-utilities

# CPU reference and GPU, one sample
scripts/run/run_finder.sh       --config configs/cpu_pg0.conf
scripts/validation/run_validation.sh --config configs/cpu_pg0.conf
scripts/run/run_finder.sh       --config configs/cuda_pg0.conf --name cuda_v2_pg0_all
scripts/validation/run_validation.sh --config configs/cuda_pg0.conf --name cuda_v2_pg0_all
scripts/compare/run_compare.sh  --reference cpu_pg0_all --compare cuda_v2_pg0_all
```

Every script prints its options with `--help`.

## Requirements

- An ACTS build of the branch to be measured (see
  [docs/acts_changes.md](docs/acts_changes.md)): `bin/ActsUnitTestGlobalPatternFinderData`
  for the CPU, and for the GPU a build with
  `-DACTS_BUILD_EXAMPLES_CUDA_GLOBAL_PATTERN_FINDER=ON`, which has
  `bin/ActsUnitTestCudaGlobalPatternFinderData`.
- Python 3.10 or newer with the packages of `requirements.txt`. The LCG
  environment of `env_setup.sh` has them; the scripts use the `python3` of the
  shell, or the one named by `PYTHON`.
- Bash, and `nvidia-smi` for the GPU's resource usage.

## Inputs

The n-tuples are written by Athena's `MuonActsDump` (`SpacePointWriter` fills the
`MuonSpacePoints` tree, `TruthSegmentWriter` the `MuonTruth` tree); the tracking
geometry comes from the ACTS tracking geometry JSON converter. They are too large
for git and live in `data/`, which every machine needs its own copy of:

```text
data/ParticleGun_MU0.root               PG0: single muons
data/ParticleGun_MU200.root             PG200: muons with pile-up 200
data/ActsTrackingGeometry_PG0.json
data/ActsTrackingGeometry_PG200.json
```

Each sample was exported with its own geometry, so a run always names both files
(`GPF_NTUPLE` and `GPF_GEOMETRY`).

Dumps made before `MuonActsDump` was fixed hold the two local covariances of a
space point in swapped order. The files in `data/` are already corrected. An
n-tuple from such a dump has to be corrected once, into a copy, with
`scripts/fix_ntuple_covariance.py`; running it twice swaps them back.

## Runs, settings and results

A **run** has a name, and everything it produces goes into
`results/<host>/<name>/`, where `<host>` is the machine's short host name. Give
each run a name that says what it is, e.g. `cpu_pg0_all` or `cuda_v2_pg200_all`.

A config file holds the settings of one run as bash assignments. There is one per
backend and sample:

```text
configs/cpu_pg0.conf    configs/cpu_pg200.conf
configs/cuda_pg0.conf   configs/cuda_pg200.conf
```

A flag overrides the config, and the config overrides an environment variable,
so a config can be bent for one run:

```bash
scripts/run/run_finder.sh --config configs/cpu_pg0.conf --name cpu_pg0_quick --events 100 --repetitions 1
scripts/run/run_finder.sh --config configs/cpu_pg0.conf --name cpu_pg0_innerseeds_all --seed-from-inner
```

| flag | setting |
| --- | --- |
| `--name`, `--sample`, `--ntuple`, `--geometry` | the run and its input |
| `--events N\|all`, `--repetitions N` | events per repetition, timing repetitions |
| `--backend cpu\|cuda`, `--build-dir DIR` | which finder and which build |
| `--seed-from-mdt`, `--seed-from-inner` | also seed from MDT hits, from the inner station |
| `--workspace-mb N` | GPU memory for the patterns of an event (default: half the free memory) |
| `--threads "1 2 4"` | thread counts of `run_throughput.sh` |
| `--station-eff-thr`, `--bending-eff-thr` | the matching thresholds of step 2 |
| `--results-dir DIR` | where the runs are kept |

The full list is in `scripts/gpf_common.sh`.

Only the small files that summarise a run are tracked in git (the rules are in
`.gitignore`): `run_info.txt`, `validation/scores.csv`, `validation/metrics.log`,
`validation/plots/`, `performance/summary.csv`, the performance figures, the
`hough/` PDFs, and the summaries and figures of a comparison. The patterns, the
validation tables, the raw timings and the logs stay on the machine.

```text
results/<host>/
  <name>/
    run_info.txt     settings, input, build, ACTS branch and revision, machine, dates
    patterns.root    step 1: the patterns, input of step 2
    performance/     step 1: summary.csv, events.csv, figures, repetitions/
    logs/            step 1: output of the finder
    validation/      step 2: scores.csv, metrics.log, plots/, tables/
    hough/           step 4
  compare/<reference>_vs_<compare>/    step 3, and step 4 with several runs
```

## The entry points

### 1. `run_finder.sh`: run the pattern finder

```bash
scripts/run/run_finder.sh --config configs/cuda_pg200.conf --name cuda_v2_pg200_all
```

Runs the CPU or GPU data test of ACTS over the sample, once per repetition (default
3). Each repetition times every call of the pattern finder and writes one row per
event; reading the input and writing the patterns are outside the timed region,
and the one-off GPU setup is timed apart. The first repetition also writes the
patterns. `/usr/bin/time` records the process's CPU time and memory, and for the
GPU `nvidia-smi` samples its load, memory, power and clock.
`performance/summary.csv` then holds, per repetition, the mean, median and
slowest time per event, the events per second, the time of each GPU stage and the
resource usage. A new run of the same name replaces the old one, its validation
included.

How the times are taken and what they mean: [docs/benchmarking.md](docs/benchmarking.md).

### 2. `run_validation.sh`: judge the patterns

```bash
scripts/validation/run_validation.sh --name cuda_v2_pg200_all
```

Reads the run's `patterns.root` and the truth of its n-tuple and writes into
`validation/`:

- `tables/`: one row per truth muon, per pattern, and per pattern and chamber
  (`build_validation_tables.py`);
- `scores.csv` and `metrics.log`: efficiency, duplicates, fakes, purity and the
  angular residuals (`compute_metrics.py`);
- `plots/`: efficiency against pT and eta, the composition of the patterns, the
  pulls of their hits and their direction (`make_plots.py`).

The definitions are those of Athena's MuonFastRecoValidation, transcribed in
`gpfval.py`; [docs/validation.md](docs/validation.md) has each one and where it
comes from.

### 3. `run_compare.sh`: two runs side by side

```bash
scripts/compare/run_compare.sh --reference cpu_pg0_all --compare cuda_v2_pg0_all
```

Writes into `results/<host>/compare/<reference>_vs_<compare>/` whatever both runs
have: the timing and resources with the speedup (`performance.csv`, figures), the
metrics with their difference (`scores.csv`), the validation figures overlaid
(`plots/`), and the patterns compared hit by hit (`patterns.log`). For the last,
`compare_patterns.py` pairs each pattern with the pattern of the other run that
shares most hits with it, and reports the shared, lost and gained hits, the
Jaccard index (shared hits over the hits in either pattern), and the patterns
left without a partner. The hit-by-hit comparison shows how far two runs differ;
the metrics show whether that matters for the physics.

Only runs over the same sample, n-tuple and number of events are compared.

### 4. `run_hough_plots.sh`: the MuonFastRecoValidation figures

The efficiency, purity, fake and station plots of the ATLAS muon group, drawn by
`MuonFastRecoValidation` of
[houghidipuffvalidation](https://gitlab.cern.ch/atlas-muon-software/houghidipuffvalidation)
(branch `LeonardoDev`). The script converts the run's validation tables into the
package's n-tuple (`to_fastreco_tuple.py`) and runs it. It needs an Athena release
set up in its own shell, without `env_setup.sh`:

```bash
setupATLAS
cd <build directory of houghidipuffvalidation>
asetup --restore
source x86_64-el9-gcc15-opt/setup.sh
cd ~/cern/acts-gpf-utilities
scripts/validation/run_hough_plots.sh cpu_pg0_all cuda_v2_pg0_all --labels CPU,GPU
```

One run writes into its `hough/`; several runs, one curve each, into
`compare/<first>_vs_<second>.../hough/`.

**This does not work with the package as it is upstream.** The upstream
`FastRecoValidation` plots scenarios hard-coded in its source
(`MuonFastRecoValidation/util/FastRecoValidation.cxx`). The script needs a
version that takes them from the command line:

```text
FastRecoValidation [--plot-dir DIR] [--out DIR] [--sample-name TEXT] [LABEL[@#RRGGBB]=]FILE.root ...
```

These changes were made locally for this work and are not in the package. To use
the script, add such a command line to `FastRecoValidation.cxx`, or plot the
`validation/fastreco.root` files that `to_fastreco_tuple.py` writes by editing
the hard-coded scenarios. The figures already in `results/` were made with the
local version.

### 5. `run_throughput.sh`: events per second against threads

```bash
scripts/run/run_throughput.sh --config configs/cuda_pg200.conf --name throughput_cuda_pg200 --events 1000
scripts/compare/plot_throughput.py results/<host>/throughput_cpu_pg200 results/<host>/throughput_cuda_pg200 \
  --output results/<host>/compare/throughput_pg200.png
```

Runs the throughput case of the data test: the events are read into memory, then
run on 1, 2, 4, 8 and 12 threads sharing one pattern finder, each thread taking
the next event. Every thread count must find the same number of patterns per
event as one thread. `throughput.csv` holds the events per second, the CPU cores
used and, for the GPU, its load during each pass. Each GPU event in flight gets
its own fixed workspace (`--workspace-mb`, default 2048), so the patterns do not
depend on the thread count.

## Results in this repository

`results/at-tdaq-mldev02/` (RTX 5000 Ada, AMD EPYC 7272) holds the runs of the
evaluation, all over the full samples:

| runs | what |
| --- | --- |
| `cpu_<sample>_all`, `cuda_v2_<sample>_all` | CPU reference and GPU v2, default settings, 3 repetitions |
| `cuda_v1_<sample>_all` | the first GPU version |
| `*_innerseeds_all`, `*_mdtseeds_all` | seeding also from the inner station, from MDT hits |
| `throughput_cpu_pg200`, `throughput_cuda_pg200` | throughput, 1 to 12 threads |
| `compare/` | the comparisons and the MuonFastRecoValidation figures of these runs |

`results/at-tdaq-mldev01/` (RTX A5000, AMD EPYC 7302) repeats the default CPU and
GPU v2 runs on a second machine. The `run_info.txt` of each run names the ACTS
revision it was made with.

## How the validation works

### Truth association

`MuonFastRecoTester` associates a measurement with a truth particle through the
sim hit behind it. The export carries no such link, so a hit belongs to a muon
here when its geometry identifier is one of the identifiers of that muon's truth
segments, `Segments_hitGeoIds`, which `TruthSegmentWriter` fills with the
surfaces of exactly those sim hits. The two differ in one direction only: a wrong
hit on a right surface counts as matched here and never does in Athena. An MDT
identifier is a tube and a strip identifier a gas gap, so the surface is
fine-grained, but the statement is about surfaces and should be quoted that way
next to Athena's numbers.

### Which muon a pattern belongs to

The majority rule of `fillGlobPatternInfo`: the muon owning the most hits of the
pattern, decided over the whole pattern.

### The truth denominator

Counted from the space points that exist and are matched, not from the truth
segments, since not every sim hit makes a space point. Hits are deduplicated per
layer of a sector, with the MDT straws exempt, as in Athena.

### What counts as found

A truth muon enters the efficiency when it lies within |eta| < 2.4, above 10 GeV,
and left enough hits (two stations with four bending hits each, two trigger hits
in the middle and outer layers, eight precision hits). A pattern matches its muon
when it crosses more than half of the muon's stations and holds more than half of
its bending hits; the match with the most bending hits stands for the muon, and a
pattern that is not that match is a fake.

### The angular residuals

A pattern's theta is that of the global position of its seed hit and is never
refitted, so it is compared with the position of the truth segment sharing the
most identifiers with it (`dThetaSeg`, `dPhiSeg`). The comparison with the truth
muon at production (`dEtaMuon`, `dPhiMuon`) is only a sanity check, since the
toroid bends the muon in between.

## Known limits

- No pile-up truth particles: both samples carry only the gun muons, so a pattern
  built from pile-up hits in PG200 counts as a fake. Its hits appear as
  `nUnmatchedHits`.
- The export does not carry the sTGC channel type, so an sTGC space point counts
  as precision only when it measures eta alone.
- One identifier covers a whole space point, so a matched two-dimensional hit
  counts for both coordinates; Athena checks the second measurement's truth link
  separately.

## Repository layout

```text
scripts/
  gpf_common.sh                 shared: flags, configs, results folder, python
  fix_ntuple_covariance.py      corrects a newly dumped n-tuple (see Inputs)
  run/
    run_finder.sh               step 1
    analyze_performance.sh      the performance summary of a run (called by step 1)
    aggregate_performance.py    per-event csv and resources -> summary.csv
    plot_performance.py         time against occupancy
    plot_stages.py              where the time of a GPU event goes
    run_throughput.sh           step 5
    throughput_gpu.py           the GPU's load during each throughput pass
  validation/
    run_validation.sh           step 2
    gpfval.py                   the definitions, transcribed from ACTS and Athena
    build_validation_tables.py  patterns + truth -> tables
    compute_metrics.py          tables -> scores
    make_plots.py               tables -> figures
    compare_patterns.py         two pattern files, hit by hit
    run_hough_plots.sh          step 4
    to_fastreco_tuple.py        tables -> MuonFastRecoValidation n-tuple
  compare/
    run_compare.sh              step 3
    compare_performance.py      two performance summaries -> speedup table
    compare_scores.py           two score tables -> differences
    plot_throughput.py          events per second against threads, several runs
configs/                        one config per backend and sample
docs/
  acts_changes.md               the ACTS branches and files
  benchmarking.md               how the times are taken and read
  validation.md                 every metric, its definition and source
  athena_deviations.md          where the example differs from Athena
results/<host>/                 the runs (summaries tracked)
data/                           the inputs (not tracked)
```

## Reproducibility

`results/<host>/<name>/run_info.txt` records the settings of a run, its input
files, the build, the ACTS branch and revision (noting local changes), the
revision of this repository, the machine, the GPU and the dates. Quote it with
any published number, together with the build configuration, which it does not
hold.
