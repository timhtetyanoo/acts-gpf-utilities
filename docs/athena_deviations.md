# Where the example differs from Athena

A reference for when the efficiency is not what it should be. Each entry says
what Athena does, what we do, why, and what it would look like if that
difference were the cause.

Entries are marked **verified** when the difference was read out of both code
bases or measured in the data, and **suspected** when it is reasoning that has
not been tested.

---

## 1. sTGC hits are classified differently — verified

**Athena** asks the measurement what kind of channel it is
(`MuonSpacePoint/src/SpacePointHelpers.cxx`):

```cpp
return hit.type() == MdtDriftCircleType || hit.type() == MMClusterType ||
       (hit.type() == sTgcStripType &&
        static_cast<const xAOD::sTgcMeasurement*>(hit.primaryMeasurement())->channelType() ==
        sTgcIdHelper::sTgcChannelTypes::Strip);
```

**We cannot.** The exported identifier carries technology, `measuresEta`,
`measuresPhi`, layer and channel, and nothing that distinguishes a strip from a
pad or a wire. So the example uses a proxy:

```cpp
return hit.id().technology() == Mdt || hit.id().technology() == Mm ||
       (hit.id().technology() == sTgc && hit.id().measuresEta() &&
        !hit.id().measuresPhi());
```

**The difference:** an sTGC space point measuring *both* coordinates is a
precision hit in Athena when the channel is a strip, and a trigger hit for us.
We only ever undercount sTGC precision hits, never overcount.

**What it would look like:** the finder requires `minPrecisionLayers`, so
undercounting suppresses seeding where sTGC dominates. The NSW is forward, so
this shows as a loss confined to large |eta| while the barrel is unaffected.

**How to test it:** take the muons lost in the affected band and count how many
of their findable hits are sTGC with both `measuresEta` and `measuresPhi` set —
those are exactly the hits the two definitions disagree about.

---

## 2. The layer number is truncated to four bits — verified

**Athena** computes a full layer number per sector
(`SpacePointPerLayerSorter::sectorLayerNum`), an `unsigned int` taken from the
readout element's logical layer index, with no upper bound.

**We** read it from the `detLayer` field of the exported identifier, which
`SpacePointWriter` packs as `((n - 1) & 0xF) << 17` — **four bits**. The example
then uses it directly:

```cpp
std::uint8_t locLayer{static_cast<std::uint8_t>(spacePoint()->id().detLayer())};
```

`locLayer` decides `sameLayer` and `layerSorter`, and therefore how many layers
a pattern is counted to have.

**The difference:** any sector layer number above 16 folds back onto a low one.
Two physically different layers then compare equal, and the ordering between
them is wrong.

**Measured:** the distribution of `detLayer` over 3000 events declines smoothly
from 12 to 15 and then triples at 16 — 11924, 11477, 9850, 7923, then 24095.
A physical distribution does not do that; folding does.

**What it would look like:** patterns credited with fewer layers than they have,
so `minPrecisionLayers` and `minStripEtaLayers` reject candidates that should
pass. It hits the regions with the most layers per sector hardest.

**This one cannot be fixed on our side.** The information is already lost in the
export; widening the field is a change to `SpacePointWriter`.

---

## 3. `resolveOverlaps` compares different things — verified

**Athena** decides whether two patterns share a hit by comparing
`primaryMeasurement()`. **The Core port** compares the space points themselves,
because the example event model has no `primaryMeasurement()`. Recorded in
`docs/acts_changes.md` as a local Core change.

**The difference:** two space points built from the same measurement are one hit
for Athena and two for us, so patterns overlap less by our count than by theirs.

**What it would look like:** more duplicates, since patterns that Athena merges
we keep apart. Look at `duplicates_per_found_muon` before suspecting anything
else.

---

## 4. The loop counter over candidate hits — verified, and currently a risk

**Athena:**

```cpp
for (std::size_t i {1}; i < candidateHits.size(); ++i) {
```

**The Core port** uses `typename Topology_t::LayerIdx` for the same loop. With
an 8-bit `LayerIdx` this overflows above 256 candidate hits, `OrderedHits[i - 1]`
reads out of bounds, and the job segfaults inside `sameLayer`. That crash was
seen and is what `ce223d6b1` fixed by restoring `std::size_t`.

`a5e42546d` then changed it back to `Topology_t::LayerIdx` and widened
`LayerIdx` to `std::uint32_t` instead. That removes the overflow, but
`nBendingLayers()` returns `LayerIdx`, and `GlobalPatternFinder.ipp:444` still
has

```cpp
const int nLayerDiff {a.nBendingLayers() - b.nBendingLayers()};
```

`uint32 - uint32` is `unsigned int`, and brace-initialising an `int` from it is
a narrowing conversion. **Confirm the branch still compiles.** Reverting the
counter to `std::size_t` and leaving `LayerIdx` at `std::uint8_t` matches Athena
and avoids both problems.

The first validation run was taken at `ce223d6b1`, so its results predate this
and are unaffected.

---

## 5. Sector neighbourhood at the wrap — fixed

`ExpandedSector::isNeighbour` used `(other.sector() - sector()) % nExpanded`,
which misses that sectors 0 and 31 meet. Fixed in `a4bb7aa16` with a unit test.
Listed here because a pattern crossing that boundary would have been silently
split before that commit, and any result produced earlier carries it.

---

## 6. Only hits measuring eta enter the search tree — suspected

The example skips a hit when it does not measure eta, and skips MDTs when
`useMdtHits` is off:

```cpp
if (!hit.id().measuresEta() || (!m_cfg.useMdtHits && hit.isStraw())) { continue; }
```

Phi-only hits are attached later by the `OnlyPhiHitsProvider`. Whether Athena
populates its tree from exactly the same set has not been checked against its
source, so this is listed as unverified rather than as a known difference.

---

# Differences that affect how the numbers are read

These are not differences in the reconstruction; they change what the
validation can measure about it. They belong here because they can look like
inefficiency when they are not.

**Truth association is by surface, not by sim hit.** Athena follows the sim hit
behind a measurement to its truth particle. The export carries no such link, so
a hit belongs to a muon when its geometry identifier is one of that muon's. An
identifier is one tube for an MDT but a whole gas gap for a strip chamber, so a
wrong strip in a right gap counts as matched. Purity is therefore an upper
bound, and test 3 exists to measure by how much.

**There are no pile-up truth particles.** A pattern built from a pile-up muon
has nothing to match and is counted as unmatched. In a pile-up sample the
unmatched rate is not a fake rate.

**Two groups of segment branches are misaligned.** In this export
`Segments_hitGeoIds`, `Segments_localSegPars` and `Segments_localToGlobal` are
rotated by one segment, within each muon, relative to `Segments_chamberIdx`,
`Segments_posX/Y/Z` and `Segments_dirTheta/dirPhi`. The validation never pairs
across the two groups, so no test is affected — but anything new that reads a
segment's kinematics next to its identifiers will be wrong.
