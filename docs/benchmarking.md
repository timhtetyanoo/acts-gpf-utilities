# Measuring execution time

How the timing is produced and what it means. The purpose is the CUDA
comparison: a speedup that somebody else could reproduce.

## What is measured

`bin/ActsUnitTestGlobalPatternFinderData` times each call of the pattern finder
on its own and writes one row per event:

```text
event,nSpacePoints,nBuckets,nPatterns,totalTime_us
```

The reader and the writer are separate calls in the test loop, so the clocks
cover the algorithm alone. `steady_clock` is monotonic, so a change of the
system time leaves the durations intact.

The hit counts share the row because they separate a busier event from a slower
one: `us_per_spacepoint` is flat when the cost per unit of work is unchanged and
the sample is merely denser.

`aggregate_event_timing.py` summarises the runs, dropping the first event of
each because it pays for cold caches, and quotes medians rather than means for
the same reason. `scripts/compare/compare_timing.py` divides two summaries into
a speedup.

## When there is a GPU

The phases go on the same row:

```text
totalTime_us, uploadTime_us, kernelTime_us, downloadTime_us
```

`totalTime_us` stays the end to end, which is below the sum of the phases by
however much transfer and compute overlap. The aggregator summarises every
column ending in `Time_us`, so the extra ones need no change to it.

Transfer and kernel have to be timed with CUDA events rather than a host clock:
a kernel launch returns before the work is done, so a wall clock around it times
the launch. Recording the bytes moved alongside the time gives an effective
bandwidth, which is what says whether a transfer is slow or merely large.

## Precedents

### ACTS, per algorithm

`Sequencer` wraps every algorithm's `execute` in an RAII stopwatch and reports at
the end, both as a printed table and as a csv:

```cpp
// Examples/Framework/src/Framework/Sequencer.cpp
struct StopWatch {
  Timepoint start = Clock::now();
  Duration& store;
  ~StopWatch() { store += Clock::now() - start; }
};
```

```text
identifier,time_total_s,time_perevent_s
```

Written to `Sequencer::Config::outputTimingFile`, `timing.csv` by default, in
`outputDir`. Wall clock, from `std::chrono::high_resolution_clock`.

`Examples/Scripts/Python/muon_global_pattern_finder.py` runs the finder through
the `Sequencer` and is where this view comes from, run by hand.

### ACTS, per call

`Tests/CommonHelpers/include/ActsTests/CommonHelpers/BenchmarkTools.hpp` provides

```cpp
microBenchmark(callable, iters_per_run, num_runs)
```

which runs in batches after a warm-up and reports a **median with an error**
rather than a single number. Its own comments say to choose `iters_per_run` so
that a batch takes a few tens of microseconds, which is what keeps it above the
timer resolution. `Tests/Benchmarks/` holds the existing users.

### ACTS, comparing configurations

`Tests/UnitTests/Core/Seeding/StrawLineFitterTest.cpp` is the closest precedent
in the repository to what we need, because it compares configurations rather
than timing one call. One function runs `nEvents` fits and returns the elapsed
milliseconds; several configurations are built by lambdas over the fitter's
config; the results are collected as `(label, future<long int>)` and written as a
labelled histogram of **time per event**, into the same ROOT file as the fit
results:

```cpp
auto timeHisto = std::make_unique<TH1D>("TestTimings", "timings",
                                        timings.size(), 0, timings.size());
for (auto& [label, result] : timings) {
  timeHisto->GetXaxis()->SetBinLabel(bin, label.c_str());
  timeHisto->SetBinContent(bin, static_cast<double>(result.get())
                                / static_cast<double>(nEvents));
  ++bin;
}
```

One bin per configuration, and the timing is reported rather than asserted: no
test fails because a fit got slower. Physics output and timing come out of the
same run, which is worth copying — it removes any doubt that the numbers describe
the same work.

Two things not to copy blindly:

- it launches the configurations concurrently with `std::async`, capped at
  `nThreads`. They then contend for the machine, so the absolute numbers are
  inflated and only comparable to each other under equal contention. For a CPU
  against GPU comparison this would be actively misleading, since a CPU run would
  steal cycles from the host thread driving the GPU. Run ours sequentially.
- it times with `std::chrono::system_clock`, which is wall clock and not
  monotonic, so it can jump if the system time is adjusted. `steady_clock` is the
  correct choice for measuring a duration.

### Athena

PerfMonMT. `MuonFastReconstructionTesterConfig.py` already exposes it through its
`--noPerfMon` switch.

### The Hough GPU work

`ActsUnitTestMuonHoughTransformBenchmarks` plus a timing campaign script and a
separate plotting script, in the sibling utilities repository. A dedicated
benchmark executable rather than timing inside the reconstruction job.

## Machine dependence

Absolute times are not comparable between machines. They depend on the CPU model,
the clock and its turbo behaviour, cache size, memory bandwidth, the build type
and compiler flags, and whatever else is running at the time.

Two things make the numbers usable anyway.

**Run both implementations in the same job on the same machine and quote the
ratio.** A speedup travels between machines far better than either time does.

**Record the context with any published figure**: the machine, the GPU model, the
build configuration, the input sample and the number of repetitions. This is
already the instruction in the repository's Reproducibility section.

A median with an error, which `microBenchmark` gives and a single wall-clock
measurement does not, is also worth having — it protects against one unlucky run
being reported as a result.

