# Validating the muon global pattern finder

What each test measures, how it is computed, and what it cannot tell you.

Two references are used throughout. Athena's `MuonFastRecoTester` decides what
is worth counting and writes counts without defining a figure of merit from
them. `MuonFastRecoValidation` (houghidipuffvalidation, branch `LeonardoDev`)
defines the figures: which truth muons count, when a pattern matches one, and
what a fake is. Those definitions are transcribed in `scripts/validation/gpfval.py`
so that the numbers here are the ones its plots show. Where neither settles a
question the choice is ours and is stated so it can be argued with.

The five tests:

1. [Efficiency](#1-efficiency)
2. [What a pattern is made of](#2-what-a-pattern-is-made-of)
3. [Are the hits on the muon's path](#3-are-the-hits-on-the-muons-path)
4. [Fake and duplicate rate](#4-fake-and-duplicate-rate)
5. [Direction](#5-direction)

---

## 1. Efficiency

### What it measures

The fraction of the truth muons that the finder could be expected to find for
which it produced a pattern that is that muon's.

### Definition

The selection, the matching and the choice of the pattern that stands for a muon
are those of `MuonFastRecoValidTuple.h`:

```
selected truth muon (tpHitSel), all of
    |eta| < 2.4 and pT >= 10 GeV
    at least 2 stations with >= 4 bending hits each   (precision + trigger eta)
    at least 2 trigger eta hits in the middle and outer layers
    at least 8 precision hits

a pattern P matches its muon T (effQuality) when
    T is the muon that shares the most hits with P
    stations of T that P crosses / stations of T       >  0.5
    bending hits of T held by P  / bending hits of T   >  0.5

the pattern that stands for T (isBestMatch) is the match with the most of T's
    bending hits, ties to the smallest mean normalised residual. It has to beat
    every other match of T strictly.

efficiency = selected muons that have a best match / selected muons
```

Both thresholds are compared with a strict `>`, as in the source, and the counts
are read as `UChar_t`, clipped at 255 per station, because the plotting package
reads them that way.

### Where the definitions come from

They are transcribed, not chosen: `gpfval.truth_selection`,
`gpfval.pattern_quality` and `gpfval.best_match` are `tpHitSel`, `effQuality` and
`isBestMatch`, and each names its original. The thresholds are the constants of
that header: `tpEtaMax`, `tpPtMin`, `minTrigEtaHits`, `minPrecHits`,
`minStations`, `minBendPerStation`, `stationEffThr`, `NBendingEffThr`, and
`seedingLayers`, which are the stations BM, BO, EM and EO. On `cpu_pg0_all` the
efficiency from `compute_metrics.py`, 0.9827, agrees with the cumulative
efficiency the plotting package draws for the same patterns, about 0.983.

A change there has to be made here as well, or the two stop agreeing.

### Where the numbers come from

| quantity | source |
| --- | --- |
| the truth muons | `Muons_*` of the `MuonTruth` tree, one row per muon |
| the hits a muon left per station | its identifiers (`Segments_hitGeoIds`) that produced a space point in that event, split into precision, trigger eta and phi |
| the hits of a pattern per station | `hit_station` and the muon identifier of its hits |
| the truth hits of a pattern per station | those of its hits whose identifier is one of the muon's |

Nothing else is used. The efficiency does not touch the tracking geometry.

### Why the truth is counted in identifiers

Athena matches a measurement to a truth particle through the sim hit behind it,
a link the export does not carry. The substitute is the surface: a hit belongs to
a muon when its identifier is one of the identifiers of that muon's truth
segments, which `TruthSegmentWriter` fills with the surfaces of exactly those sim
hits. Counting distinct identifiers also reproduces Athena's deduplication for
free, since a strip identifier is a gas gap and an MDT identifier a tube.

### How it is presented

Against truth pT (45 bins from 10 to 100 GeV), η (25 bins from -2.4 to 2.4) and
φ (50 bins over ±180 degrees), the binning of the plotting package. The error
bars are Clopper-Pearson intervals at 68.3%, ROOT's `TEfficiency` default.

The selection is applied to the denominator, so the coverage edge of the
spectrometer does not appear: muons outside |η| < 2.4 are not counted. A single
figure is quoted together with this selection, and the plot is the primary
result. The number of selected muons is `truth_muons` in `scores.csv`, next to
`truth_muons_all`.

### What changed

Earlier versions counted every truth muon and called a muon found when a pattern
had at least half of its findable identifiers and at least half of the pattern's
hits were its own, in two stations (ACTS's `TrackTruthMatcher`). That criterion
is gone. Numbers from runs made before the change are not comparable with the
ones made after it.

### What it cannot tell you

- **A wrong hit on a right surface counts as found.** An identifier is one tube
  for an MDT but a whole gas gap for a strip chamber, so a pattern holding the
  wrong strip of the right gap is indistinguishable here. Test 3 exists for that.
- **It says nothing about what else the pattern picked up.** A pattern
  containing the whole muon and fifty stray hits is fully efficient. That is
  purity's job.
- **The selection reads the muon's hits, not the finder's configuration**, so
  loosening the finder cannot change which muons are counted. A muon that left
  too few hits is excluded, and nothing here says how many those are beyond
  `truth_muons_all` minus `truth_muons`.
- **Two best matches that are equal in both quantities leave the muon without
  one.** The source requires a strict win, so such a muon counts as missed and
  both patterns as fakes. It is rare, since the residual is a real number, but it
  happens for patterns with identical hits.
- **The samples carry no pile-up truth particles**, only the one or two gun
  muons, so every truth muon is a signal muon.


---

## 2. What a pattern is made of

### What it measures

Efficiency says the finder got the muon. This says what else it got with it.

One test, three numbers, all from the same operation: take every hit of a
pattern and sort it into three piles.

| pile | |
| --- | --- |
| **A** | hits of the muon the pattern was assigned to |
| **B** | hits of a *different* truth muon |
| **C** | hits of no truth muon at all |

### Definition

```
purity              = A / (A + B + C)
mismatched fraction = B / (A + B + C)
selectivity         = (A + B + C) / (all hits in the buckets the pattern took hits from)
```

Reported per pattern and summarised over the matched patterns.

Only one of the three carries a verdict.

**The mismatched fraction has a right answer.** It is the fraction of the
pattern that came from another muon, so a high value means the pattern ran
through two tracks and took hits from both, ruining the one it was assigned to
and stealing hits from the other. If a pass/fail gate is ever wanted on pattern
quality, it belongs here and nowhere else.

**Purity and selectivity are descriptive**, and only mean anything as a pair. A
pattern finder is deliberately inclusive: it defines a road and collects what
lies in it, leaving the choice of which hits are really on the track to the
segment fit. So a low purity is not by itself a defect. Selectivity is what
makes it readable — a pattern at 60% purity that took a third of the available
hits is doing real work, while one at 60% purity that took everything in the
chambers it crossed is not selecting at all and only looks acceptable because
those chambers happened to be clean.

Selectivity is Athena's `eAll` comparison: `fillGlobPatternInfo` counts every
hit of every bucket the pattern drew a hit from, precisely so the hits it took
can be read against the hits it could have taken.

### Where the numbers come from

| quantity | source |
| --- | --- |
| a pattern's hits | `hit_geometryId` and `hit_patternIdx` |
| which muon a hit belongs to | its identifier looked up in each muon's set, as in test 1 |
| the buckets a pattern touched | `hit_bucketId` |
| the hits available in those buckets | `spacePoint_bucketId` of the event |

The same primitive as test 1, so nothing new has to be extracted and none of the
geometry is involved.

### What it cannot tell you

- **Purity is an upper bound.** An identifier is a whole gas gap for a strip
  chamber, so a pattern holding the wrong strip of a right gap counts it in pile
  A. Test 3 is what sees that.
- **Pile-up cannot be separated from noise.** The truth tree carries no
  pile-up particles, so pile-up muons, cavern background and detector noise all
  land in pile C together. It is reported as one category and named as such
  rather than being split into numbers we cannot support.
- **Pile C is slightly contaminated with real muon hits.** A hit genuinely left
  by the muon that the truth segment fit rejected as an outlier is not in that
  muon's identifier set, so it is counted as belonging to nothing.
- **The mismatched fraction is only meaningful where there is more than one
  muon to confuse.** The particle-gun samples carry one or two, so it measures
  merging between those and nothing else.



---

## 3. Are the hits on the muon's path

### What it measures

Tests 1 and 2 decide what a hit belongs to by its identifier. For an MDT an
identifier is one tube, which is precise; for a strip chamber it is a whole gas
gap holding dozens of strips. So a pattern that took the wrong strip of the
right gap is perfectly pure by test 2.

This test never looks at identifiers. It looks at where the hit physically is.
Its purpose is to measure the error in test 2.

### Definition

Per hit, against the truth segment of the chamber that hit is in:

```
distance  = perpendicular distance to that segment's line, bending plane only
residual  = distance - driftRadius   for an MDT
          = distance                 otherwise
pull      = residual / sqrt(variance in the bending direction)
```

Reported as the **mean squared pull, per pattern and chamber**, separately for
the hits attributed to the muon and for the rest.

A hit genuinely on the muon's path gives a pull of about 1, so a mean squared
pull of about 1 means the pattern's hits lie on the trajectory and a large value
means they do not.

The two populations are kept apart because averaging them together describes
neither. The hits attributed to the muon answer the question this test exists
for — did test 2 count them rightly — and a large value there is a defect. The
remaining hits answer how far from the muon's path the pattern reached, and a
large value there is expected rather than wrong. On the sample the separation is
complete: about 1 for the muon's hits against some thousands for the others.

### Why a pull and not a distance

In millimetres the number would need a different threshold for every technology.
A strip chamber records where the particle crossed, so a correct hit lies a
fraction of a millimetre from the path; an MDT records a drift radius, and its
wire is up to a tube radius away from the path even when the hit is perfect. Five
millimetres is a defect for one and normal for the other.

Two things remove that. The residual for a tube subtracts the drift radius, so a
correct tube hit gives about zero rather than about fifteen millimetres — this
is the Core's own definition, `CompSpacePointAuxiliaries`:

```cpp
if (hit.isStraw()) {
    chiSq = Acts::square(dist - hit.driftRadius()) / hit.covariance()[bendIdx];
}
```

and dividing by each hit's own uncertainty folds in the precision of its
technology. The result is one distribution over every technology, with one
threshold. The difference between a tube and a strip lives inside the standard
residual formula, not in the metric.

### Per chamber, not per pattern

The muon's path is straight only inside one chamber; the toroid bends it between
stations, which is why the truth segments are per chamber. A pattern crossing
three chambers therefore gives three sets of pulls, and it can be right in one
chamber and wrong in another. The natural unit is the pattern-and-chamber pair,
and collapsing to one number per pattern would hide exactly that.

The segment that applies to a hit is the one whose `Segments_hitGeoIds` claims
that hit's identifier — an exact assignment, not a geometric guess. Hits claimed
by no segment are measured against the assigned muon's segment in the same
chamber, since for them the question is how far from the muon's path the pattern
reached.

### The comparison that makes it useful

The finder already reports this exact quantity against its **own** line:

```cpp
meanNormResidual2 += Acts::square(residual / resSigma);
```

which is `pattern_meanNormResidual2`, and it accepts patterns on it. This test is
the same formula with the **truth** line substituted. Two references, one
quantity: a pattern that fits its own line well but the truth line badly found a
line, just not the muon's.

### Where the numbers come from

| quantity | source |
| --- | --- |
| hit position | `spacePoint_localPos`, sector frame |
| the truth line | `Segments_localSegPars`, same frame, no transform |
| which line applies | `Segments_hitGeoIds` |
| drift radius | `spacePoint_driftRadius` |
| measurement uncertainty | `spacePoint_covLoc0`, the bending direction |
| is it a tube | technology field of `spacePoint_muonId` |

The pairing of `localSegPars` with `hitGeoIds` was checked against the data: a
segment's own hits sit 4 to 9 mm from its own line in the bending plane, and
hundreds of millimetres from it in the other direction. No tracking geometry is
involved.

### What it cannot tell you

- **Only the bending plane.** A segment barely constrains the coordinate along
  the tube, so a distance taken in three dimensions would fold a well measured
  direction together with a badly measured one. This was measured on the data,
  not assumed.
- **Hits in a chamber where the muon left no segment cannot be measured at all.**
  They have no line to compare against and are counted separately rather than
  quietly dropped.
The bending direction is `covLoc0`, established from the data rather than from
an enum: for an MDT its median is 0.02 mm², the square of the drift resolution,
while `covLoc1` is 1.8e6 mm², the square of half a tube length — the coordinate
along the wire, which is not measured. Micromegas and sTGC show the same
pattern. This agrees with `CovIdx::etaCov = 0` in the example's own definitions;
the Core's `ResidualIdx::bending = 1` indexes a different array in a different
event model and must not be applied here.

---

## 4. Fake and duplicate rate

### What it measures

Efficiency and the composition tests look at the patterns that correspond to a
muon. These look at the patterns that don't, and at the muons that got more than
one.

- an **unmatched pattern** is one that matches no truth muon
- a **duplicate** is a second, third, … pattern for a muon that already has one

### Definition

```
fake       a pattern that is not the best match of a muon: it matches no muon,
           or it is a further match of one
fake rate  per event, fake patterns / patterns, averaged over the events that
           have a pattern and a truth muon        (MuonFastRecoValidation)
fake fraction = fake patterns / all patterns of the sample

unmatched  a pattern that matches no truth muon, at the criterion of test 1
duplicate  a match that is not the best one of its muon
duplicates per found muon
```

The fake rate is the figure the plotting package draws as `CumulativeFakeRate`:
the fraction is taken per event and then averaged, so an event with two patterns
weighs as much as one with twenty, and duplicates count as fakes. The two
fractions differ a lot where the fakes sit in a few busy events: on
`cpu_pg0_all` the fake rate is 0.079 and the fake fraction 0.231. Quote the
fake rate next to the plotting package's number and the fraction when the
share of the patterns is what matters.

Unmatched and duplicates are the two parts of the fakes, kept apart because they
are different failures: an unmatched pattern corresponds to no muon, a duplicate
to a muon that was found already.

### Only in a sample without pile-up is this a fake rate

Without pile-up every particle that crossed the spectrometer is in the truth
tree, so a pattern matching nothing corresponds to nothing: noise, background,
or a genuine failure of the finder. **There the number is exact and is called
the fake rate.**

With pile-up it is not. A pattern built from the hits of a pile-up muon is a
perfectly good pattern of a real particle, but the truth tree carries only the
signal muons, so it has nothing to match. We cannot tell that pattern from a
genuine fake, and the export will not be extended to tell us.

So in a pile-up sample the number is reported as **unmatched patterns per
event** and not as a fake rate. The name claims only what was observed. Calling
it a fake rate would assert something the data cannot support.

### What pile-up samples are for instead

The useful question under pile-up is not which pattern is fake but how much
extra work pile-up creates, and that is measured exactly by comparing the two
samples:

```
patterns per event      no pile-up   vs   with pile-up
unmatched per event     no pile-up   vs   with pile-up
```

The increase is the pile-up load. It needs no knowledge of which individual
pattern came from pile-up, so it is a real result rather than an upper bound.

### Everything else survives pile-up intact

Only this one metric degrades, because every other test is anchored on the
signal muons, which *are* in the truth tree: efficiency, the mismatched
fraction, duplicates, the hit-on-path pull and the direction residual are all
exact under pile-up.

### Where the numbers come from

Nothing new. Both follow from the pattern-to-muon assignment already built for
tests 1 and 2.

### What it cannot tell you

- **Which unmatched patterns in a pile-up sample are real muons.** Reporting the
  fraction of a pattern's hits that belong to no truth muon narrows it — a
  pattern made entirely of such hits is more likely a pile-up muon than a
  failure — but it does not decide it.
- **Duplicates say nothing about which of the two patterns is better.** They are
  counted, not ranked, beyond taking the one with the most shared identifiers as
  the muon's.


---

## 5. Direction

### What it measures

Whether the direction a pattern reports points where the muon really went.

### Definition

```
dEta = eta of the pattern  -  eta of the truth muon at production
dPhi = phi of the pattern  -  phi of the truth muon at production
```

reported as mean and width. The phi residual is drawn as **two curves**: the
patterns that have phi-measuring hits, and the patterns that do not. See below.

### This is a sanity check, not a resolution measurement

A pattern's theta is the polar angle of the global position of its seed hit,
never refitted, and the truth eta is the muon's direction at production. The
toroid bends the muon between the two, so the width of this residual is set by
the magnetic field and not by the pattern finder. Improving the finder would
barely narrow it.

What it does catch, and catches reliably: a sign flip, a wrong sector, a side
confusion, a broken phi convention, a units error. Those are exactly the
failures that efficiency and purity stay blind to, which makes this the most
useful regression check against a future CUDA implementation.

### Athena stores this pair and does not compare it

`MuonFastRecoTester` writes `pat_Eta` and `pat_Phi` alongside `gen_Eta` and
`gen_Phi` and stops there: no subtraction, no histogram, no threshold anywhere
in the tester, and the package holds no plotting code. The comparison is left to
whatever analysis reads the ntuple, which is what this test is.

### The phi split

When a pattern holds no phi-measuring hit the finder does not estimate phi at
all. It assigns the centre of the sector, with an uncertainty the width of the
sector:

```cpp
if (nPhiLayers == 0) {
    patPhi = expSect.phi();
    patPhiCov = Acts::square(expSect.sectorSize()) / 3.;
}
```

Those patterns therefore have a phi residual spread across the sector width
however good they are. They are drawn as a separate curve rather than folded in,
so the measured population shows the real agreement and the sector-centre
population shows how often the finder is flying blind in phi — which is worth
knowing in its own right.

### Where the numbers come from

| quantity | source |
| --- | --- |
| the pattern's direction | `pattern_theta` and `pattern_phi` |
| the muon's direction | `Muons_eta` and `Muons_phi` |
| whether phi was measured | `pattern_nPhiLayers` |

Indexed by muon rather than by segment, so none of the shifted segment branches
are involved.

### What it cannot tell you

- **Nothing about resolution.** The width is bending, not performance.
- **Nothing about the trajectory inside the spectrometer.** A sharper comparison
  against a point of the muon's path in the chambers would need a global
  position for a truth segment, and no branch combination in the export supplies
  one that can be trusted: `Segments_posX/Y/Z` is shifted by one segment
  relative to the identifiers that select the segment, and
  `Segments_localToGlobal` does not reproduce the position of the hits it should
  belong to either.

---

## Comparing two runs

`compare_patterns.py` checks whether two runs found the same patterns. It pairs
them by the hits they share and then reports the differences, so a pattern that
lost one borderline hit stays one pattern rather than being counted as one
missing and one appeared.

A hit is named by its place in the input space point container, the bucket and
the index within it. Neither the order of the hits in a pattern nor the order of
the patterns in an event carries meaning, because both sides are compared as
sets of those names.

### The two runs have to read the same events

That name is a **position in the input**, not a property of the hit. Two runs
over the same n-tuple and the same event range name the same hit the same way.
Two runs over different samples, or over different numbers of events, or over
the same file read in a different order, do not: the same bucket and index then
point at different hits.

Nothing detects this. The comparison does not fail, it reports differences that
are an artefact of the pairing rather than of the finder. So the precondition is
on the runs, not on the tool:

- the same n-tuple,
- the same events, in the same order,
- one thread, since the Sequencer finishes events out of order with more and
  the entries of the pattern file are then no longer in event order.

Everything else may differ: the machine, the build, the implementation.
