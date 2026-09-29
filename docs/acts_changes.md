# Changes to the ACTS checkout

State of `glob-pat-finder-example` in `~/cern/acts` as of 2026-09-25, relative
to the upstream commit it branches from, `a6a3bb87b`.

Keep this file updated whenever a file is added to or changed in the ACTS
checkout, so the eventual pull request can be assembled from it.

## 1. Ours, new files

| file | content |
| --- | --- |
| `Examples/Algorithms/TrackFinding/include/ActsExamples/TrackFinding/GlobalPatternFinderDefs.hpp` | `ExpandedSector`, `StIndex`, `LayerIndex` & helpers, `HitPayload`, `PatternTopology`, `SeedSelector`, `OnlyPhiHitsProvider`, `GlobalPatternFinder_t`, `SearchTreeData`, `localToGlobalTransform` |
| `Examples/Algorithms/TrackFinding/src/GlobalPatternFinderDefs.cpp` | their implementation, plus the ported parts of the Athena sector mapping |
| `Examples/Algorithms/TrackFinding/include/ActsExamples/TrackFinding/GlobalPatternFinderAlgorithm.hpp` | the algorithm, its `Config` and the output type `MuonGlobalPattern` |
| `Examples/Algorithms/TrackFinding/src/GlobalPatternFinderAlgorithm.cpp` | constructor, `execute`, `constructTree`, `convertToPattern` |
| `Examples/Io/Root/include/ActsExamples/Io/Root/RootMuonGlobalPatternWriter.hpp` | writer of the found patterns |
| `Examples/Io/Root/src/RootMuonGlobalPatternWriter.cpp` | its implementation |
| `Examples/Scripts/Python/muon_global_pattern_finder.py` | run script: reader, algorithm, optional writer |
| `Tests/UnitTests/Examples/Algorithms/TrackFinding/GlobalPatternFinderTests.cpp` | synthetic unit tests, no input files |
| `Tests/UnitTests/Examples/Algorithms/TrackFinding/GlobalPatternFinderDataTests.cpp` | end-to-end run on real files, driven by `ACTS_GPF_*`. **Development aid, to be removed before a pull request** |

## 2. Ours, changes to upstream files

| file | change |
| --- | --- |
| `Examples/Algorithms/TrackFinding/CMakeLists.txt` | builds the two new sources |
| `Examples/Io/Root/CMakeLists.txt` | builds the writer, and links `Acts::ExamplesTrackFinding` so the module sees `MuonGlobalPattern` |
| `Python/Examples/src/TrackFinding.cpp` | binding of `GlobalPatternFinderAlgorithm` |
| `Python/Examples/src/plugins/Root.cpp` | binding of `RootMuonGlobalPatternWriter` |
| `Tests/UnitTests/Examples/Algorithms/TrackFinding/CMakeLists.txt` | both test targets; the data one behind `if(TARGET ActsExamplesIoRoot AND TARGET ActsPluginJson)`. **That block goes with the data test** |

## 3. lmonaco's, the Core pattern finder

Added by `641543970 last changes` and `29c211ec1 new pat finder`, which are the
base of this branch. They are not upstream yet.

| file | note |
| --- | --- |
| `Core/include/Acts/Seeding/GlobalPatternFinder.hpp` | **modified by us** in `870928b25`: missing include |
| `Core/include/Acts/Seeding/GlobalPatternFinder.ipp` | **modified by us** in `870928b25`: `VectorHelpers::phi`, `.norm()`, includes, and `resolveOverlaps` comparing space points instead of `primaryMeasurement()` |
| `Core/include/Acts/Seeding/detail/GlobalPatternFinderAuxiliaries.hpp` | unchanged by us |
| `Core/include/Acts/Seeding/detail/GlobalPatternFinderAuxiliaries.ipp` | **modified by us** in `870928b25`: `VectorHelpers::phi/theta`, `measuresLoc0()`, includes |

The behaviour-neutral part of those fixes was pushed to his branch as
`91281b8fe Update globpatfinder to use ACTS vector helpers`. Still only local:
the `resolveOverlaps` line, since his version calls `primaryMeasurement()`,
which the example EDM does not have. Drop our version once he fixes it.

## 4. lmonaco's, the bucket transform (acts-project/acts#6128)

Cherry-picked from his `addTransform` branch as `5a1dfb694`, `9392c8ef6` and
`e9c3f92e9`. They will arrive upstream as one squashed commit, so expect to
`git rebase --skip` all three at that point.

| file | change |
| --- | --- |
| `Examples/Framework/include/ActsExamples/EventData/MuonSpacePoint.hpp` | `toSectorTransform()` / `setToSectorTransform()` on the space point |
| `Examples/Io/Root/include/ActsExamples/Io/Root/RootMuonSpacePointReader.hpp` | nine `spacePoint_toSectorFrame*` branches |
| `Examples/Io/Root/src/RootMuonSpacePointReader.cpp` | fills the transform per space point |
| `Examples/Scripts/Python/muon_hough.py` | his config style & import fix, unrelated to us |
| `Python/Examples/src/TrackFinding.cpp` | `extendWithPhi` in the `MuonHoughSeeder` binding. **We also changed this file**, see section 2 |

## Outside the ACTS checkout

`~/cern/acts-gpf-utilities`, pushed to `timhtetyanoo/acts-gpf-utilities`: the
validation driver, the validation tables, the metrics, the plots, the run
comparison and this document.

The validation needs nothing from ACTS beyond what the pattern writer and the
space point reader already produce.

## Before a pull request

- remove `GlobalPatternFinderDataTests.cpp` and its `if(TARGET …)` block;
- drop the three cherry-picked commits once #6128 is merged;
- rebase onto lmonaco's Core branch once it is upstream, so only sections 1 & 2
  remain;
- revisit the `resolveOverlaps` deviation.
