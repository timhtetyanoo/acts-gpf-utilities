# Measuring execution time

Notes, not decisions. Nothing here is implemented yet. The purpose is the CUDA
comparison: knowing which part of the pattern finding is worth moving to the GPU,
and being able to state a speedup that somebody else could reproduce.

## What already exists

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

**The catch for us:** our run stage uses the C++ data test, not the `Sequencer`,
so this is not available unless the chain moves to
`Examples/Scripts/Python/muon_global_pattern_finder.py`. That entry point has to
survive to the pull request anyway, since the data test is a development aid
that will be removed, so switching is worth doing for its own sake.

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

## What we could measure, and with what

### The three stages, for free

`GlobalPatternFinderAlgorithm::execute` already separates them:

```cpp
SearchTreeData treeData{constructTree(gctx, inSpacePoints)};   // 1 build the tree
... m_globPatFinder->findPatterns(gctx, treeData.tree, ...)    // 2 find patterns
MuonGlobalPatternContainer patterns{convertToPattern(...)};    // 3 convert
```

All three are callable, so `microBenchmark` reaches them without touching
anything. This is the first measurement worth having: if building the search
tree dominates, porting the seed loop to the GPU buys little, and that changes
what the project is.

### Inside the Core, not with microBenchmark

`findPatternsInEta`, the seed loop, `getPhiOnlyHits` and `resolveOverlaps` are
private members of the Core template and cannot be called from a benchmark. A
breakdown there needs either a profiler or instrumentation in the Core.

A sampling profiler needs no code change and attributes time inside the
templates:

```bash
perf record -g ./bin/ActsUnitTestGlobalPatternFinderData && perf report
```

Timers inside the Core would give boundaries that match the port's structure
rather than the compiler's function boundaries, but they mean changing the Core,
which is a last resort. Only worth asking for once `perf` shows the function
level view is too coarse.

### Suggested order

1. the three stages, to find out whether the Core is even the thing to optimise;
2. `perf` inside whichever stage dominates;
3. Core instrumentation only if 2 proves too coarse, with a concrete reason to
   give lmonaco.

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

## Open

- whether to move the run stage onto the `Sequencer` entry point, which would
  give the per-algorithm csv for free;
- whether the benchmark lives in a separate executable, as the Hough work did, or
  inside the existing test, as `StrawLineFitterTest` does;
- whether to report per-event time in a labelled histogram, following
  `StrawLineFitterTest`, or a median with an error from `microBenchmark`. The
  first is simpler and matches the repository; the second says how much of a
  difference is noise;
- what sample and event count a timing campaign should use, which only matters
  once there is something to compare.
