# The ACTS side

The pattern finder, its tests and the programs these scripts run all live in
ACTS, on the branches of [timhtetyanoo/acts](https://github.com/timhtetyanoo/acts).
This page says which branch holds what and which files are ours.

## Branches

| branch | content |
| --- | --- |
| `glob-pat-finder-example` | CPU reference: the Core pattern finder and the CPU example |
| `cuda-glob-pat-finder-v2` | the GPU implementation (v2), merged on top of the example branch; the version of the results |
| `cuda-glob-pat-finder` | the first GPU implementation (v1), on an older Core; kept for comparison |
| `experimental` | ideas tried on top of v2 that were not adopted |
| `gpf-cpu-example` | the CPU example as an upstream pull request, stacked on the Core PR |

The Core pattern finder is Leonardo Monaco's, from
[lmonaco99/acts `globPatFinder`](https://github.com/lmonaco99/acts/tree/globPatFinder),
acts-project/acts PR 6277. It is taken unchanged into `glob-pat-finder-example`
and merged from there into v2. The example's settings follow the ATLAS
`MuonGlobalPatternFindingAlg` of
[lmonaco/athena `actsGlobPatFinder`](https://gitlab.cern.ch/lmonaco/athena/-/tree/actsGlobPatFinder).
The results in this repository use the Core at `e4141b599` and that algorithm
at `aaa4316c1a8`.

When the Core changes: copy the four Core files onto `glob-pat-finder-example`
in one commit, adapt the example's settings to Athena, merge into v2 and port
the changes to the GPU code.

## Files

Core, Leonardo's (`Core/include/Acts/Seeding/`):
`GlobalPatternFinder.hpp`, `GlobalPatternFinder.ipp`,
`detail/GlobalPatternFinderAuxiliaries.hpp`, `detail/GlobalPatternFinderAuxiliaries.ipp`.

CPU example:

| file | content |
| --- | --- |
| `Examples/Algorithms/TrackFinding/.../GlobalPatternFinderAlgorithm.hpp`, `src/GlobalPatternFinderAlgorithm.cpp` | the algorithm, the hit payload, sectors, station topology, seed selector and phi-only hits for the ATLAS muon spectrometer |
| `Examples/Scripts/Python/muon_global_pattern_finder.py` | run script: reader, algorithm |
| `Python/Examples/src/TrackFinding.cpp` | Python binding of the algorithm |
| `Tests/UnitTests/Examples/Algorithms/TrackFinding/GlobalPatternFinderTests.cpp` | unit tests on constructed hits |
| `Examples/Io/Root/.../RootMuonGlobalPatternWriter.hpp`, `.cpp` | writes the found patterns for the validation (not in the pull request) |

GPU implementation (`Examples/CudaGlobalPatternFinder/`, built with
`-DACTS_BUILD_EXAMPLES_CUDA_GLOBAL_PATTERN_FINDER=ON`):

| file | content |
| --- | --- |
| `include/ActsExamples/TrackFinding/CudaPatternFinder.hpp` | the algorithm, its configuration and the device-side mathematics shared with the tests |
| `include/ActsExamples/EventData/CudaPatternFinderData.hpp`, `src/CudaPatternFinderData.cpp` | the data on the device: hits, candidate lists, pattern records |
| `src/CudaPatternFinder.cpp` | host side: packing an event, the transfers, phi-only hits and the output |
| `src/CudaPatternFinder.cu` | the kernels: search, seed checks, pattern building, overlap resolution |
| `Python/Examples/src/plugins/CudaGlobalPatternFinder.cpp`, `Examples/Scripts/Python/muon_global_pattern_finder_cuda.py` | Python binding and run script |
| `Tests/UnitTests/Examples/CudaGlobalPatternFinder/CudaPatternFinderTests.cpp` | the GPU functions against the CPU's |

Development aids, to remove before a pull request: the two data tests, which
read the external n-tuples and are what `run_finder.sh` and `run_throughput.sh`
run.

| file | environment variables |
| --- | --- |
| `Tests/UnitTests/Examples/Algorithms/TrackFinding/GlobalPatternFinderDataTests.cpp` | CPU |
| `Tests/UnitTests/Examples/CudaGlobalPatternFinder/CudaGlobalPatternFinderDataTests.cpp` | GPU |

Both read `ACTS_GPF_NTUPLE`, `ACTS_GPF_GEOMETRY`, `ACTS_GPF_MAX_EVENTS`,
`ACTS_GPF_OUTPUT` (pattern file), `ACTS_GPF_TIMING` (per-event csv),
`ACTS_GPF_SEED_FROM_MDT`, `ACTS_GPF_SEED_FROM_INNER`, and for the throughput case
`ACTS_GPF_THREADS` and `ACTS_GPF_THROUGHPUT`; the GPU test also
`ACTS_GPF_WORKSPACE_MB`. The scripts set them; a test case whose inputs are
unset is skipped.
