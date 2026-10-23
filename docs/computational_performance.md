# Computational performance

The computational performance is measured by the data tests of ACTS,
`ActsUnitTestGlobalPatternFinderData` for the CPU and
`ActsUnitTestCudaGlobalPatternFinderData` for the GPU. `run_finder.sh` runs them
over a sample and `analyze_performance.sh` summarises the result.

## Execution time

The time per event is measured with `std::chrono::steady_clock` around the call of
the pattern finder. Reading the input and writing the patterns are outside the
timed region. For the GPU, the time includes the host work before and after the
GPU and the copies between host and device. The one-time GPU setup, such as
reserving device memory, is timed separately and reported as
`setup before the first event (ms)`.

Each run is repeated (three times by default). The test writes one row per event
to `performance/events.csv`:

```text
event, nSpacePoints, nBuckets, nPatterns, totalTime_us
```

The GPU test adds the time of each stage, measured with CUDA events, since a
kernel launch returns before the kernel has finished:

```text
hostPreTime_us, uploadTime_us, kernelTime_us, downloadTime_us, hostPostTime_us,
nSeeds, nCandidates, nPatternsInEta, overflow, workspaceUsed_bytes, device_bytes
```

`overflow` is non-zero when the patterns of an event did not fit the workspace.

`performance/summary.csv` holds, per repetition:

| quantity | |
| --- | --- |
| mean, median, p90 and slowest time per event | over all events |
| throughput | events / summed time per event, one event at a time |
| median time per space point | separates a denser event from a slower one |
| time per GPU stage | median and p90 of each stage |
| GPU memory of the event | median and peak of the device memory one event uses |
| events with an overflow | GPU only |

`performance/event_times.png` shows the time per event against the number of
space points, and `performance/stages.png` the split of the GPU time into stages.

## Resource utilisation

During each repetition:

- `/usr/bin/time` records the wall time, the mean number of CPU cores in use and
  the peak memory of the process;
- `nvidia-smi` samples the GPU every 200 ms. The utilisation, power and SM clock
  are averaged over the samples in which the GPU was busy; the memory is the peak.

The device memory reported by `nvidia-smi` is the reserved workspace, not what an
event needs. The GPU test therefore also records the memory each event takes from
its workspace (`workspaceUsed_bytes`) and in total (`device_bytes`).

`nvidia-smi` reports the whole device, so the machine should be otherwise idle.

## Throughput

`run_throughput.sh` measures the events processed per second with several events
in flight. The events are first read into memory; N threads then share one
pattern finder, each taking the next unprocessed event until none are left. Each
thread count is run once to warm up and once timed. On the GPU, each event in
flight has its own CUDA stream and a fixed workspace (`--workspace-mb`, default
2048 MiB), so the result does not depend on N. Every pass must reproduce the
number of patterns of each event found with one thread.

`throughput.csv` holds, per thread count, the events per second, the wall and CPU
time, the CPU cores in use and the events that overflowed, failed or differ from
one thread. For a GPU run, `throughput_gpu.py` adds the mean utilisation and
power, the median SM clock and the peak memory sampled during each timed pass;
the samples are in `gpu.csv`.

`scripts/compare/plot_throughput.py` plots the events per second against the
number of threads for several runs.

## Comparing two runs

`run_compare.sh` writes `performance.csv`, the summaries of two runs side by side
with the speedup, and overlays their time per event against the number of space
points (`event_times.png`) and their stages (`stages.png`).

## Reproducibility

Absolute times depend on the machine, the build and the load at the time of the
run. A ratio between two implementations measured on the same machine is more
robust than either time. `run_info.txt` records, for each run, the settings, the
input files, the executable and its build time, the ACTS revision (noting local
changes), the revision of this repository, the CPU, the GPU and the dates. The
build configuration is not recorded and should be quoted separately.
