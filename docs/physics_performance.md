# Physics performance

The physics performance of a run is computed from its `patterns.root` and the
truth of the input n-tuple. The selection of truth muons, the matching of
patterns to muons and the fake rate follow the definitions of the ATLAS
`MuonFastRecoValidation` package, so the numbers can be compared with those of
Athena. They are implemented in `scripts/validation/gpfval.py`.

## Truth hits of a muon

The n-tuple carries no link from a space point to the particle that produced it.
Instead, each truth segment lists the measurement surfaces the muon crossed in a
chamber (`Segments_hitGeoIds`) and the straight line of its path through the
chamber (`Segments_localSegPars`).

On every surface a segment lists, the space point closest to the segment's line
is taken as the muon's hit. The distance is the χ² of the core library,
`CompSpacePointAuxiliaries::chi2Term`:

```
χ²(h, L) = Σ_i r_i(h, L)² / σ_i²
```

where `r_i` is the residual of hit `h` to line `L` in measured direction `i`
(for an MDT, the distance minus the drift radius) and `σ_i²` the variance of the
hit in that direction. One hit is taken per surface and measured direction (η, φ
or both). An MDT surface is a single tube and a strip surface a single gas gap.
A hit claimed by two segments goes to the closer one.

Space points that share a surface and a local y position hold the same strip
measurement combined with different strips of the other direction. They count
as one measurement: a pattern holding any of them holds the muon's hit.

## Selection and matching

A truth muon is **selected** when

- |η| < 2.4 and pT ≥ 10 GeV,
- it has at least two stations with at least four bending hits each
  (precision and trigger η),
- at least two trigger η hits in the middle and outer stations,
- at least eight precision hits.

A pattern **matches** muon T when T owns most of the pattern's hits and the
pattern holds more than half of T's stations and more than half of T's bending
hits. Of several matches, the one with the most of T's bending hits is T's
**best match**; ties are broken by the smaller mean normalised residual.

## Metrics

Written to `validation/scores.csv`:

| metric | definition |
| --- | --- |
| efficiency | selected muons with a best match / selected muons |
| fake rate | per event, patterns that are not a best match / patterns, averaged over the events with at least one pattern and one truth muon |
| fake fraction | patterns that are not a best match / all patterns |
| duplicates per found muon | (matching patterns − found muons) / found muons |
| purity | hits of the muon in the pattern / hits in the pattern, mean over matched patterns |
| completeness | hits of the muon in the best match / hits of the muon, mean over found muons |
| hits from another muon | fraction of a matched pattern's hits that belong to a different muon |
| hits taken | hits in the pattern / hits in the buckets it took hits from |
| mean squared pull | per matched pattern and chamber, the mean of (residual / σ)² of the muon's hits about the truth line in the bending plane; median over patterns |
| η and φ residuals | pattern direction minus the truth muon at production, mean and standard deviation |

The η and φ residuals are a consistency check rather than a resolution: the
pattern direction is taken from its seed hit, and the muon is bent by the toroid
between production and the spectrometer.

## Figures

Written to `validation/plots/`:

- `efficiency.png`: efficiency against truth pT, η and φ, with Clopper–Pearson
  68.3% intervals;
- `composition.png`: purity, completeness, hits from another muon and hits taken;
- `pulls.png`: the mean squared pull of the muon's hits and of the other hits;
- `direction.png`: the η and φ residuals, split by whether the pattern holds a
  φ-measuring hit.

## Comparing two runs

`run_compare.sh` puts the metrics and figures of two runs side by side and
compares their patterns hit by hit (`compare_patterns.py`). Each pattern is
paired with the pattern of the other run sharing most of its hits, and the
Jaccard index, shared hits over the hits in either pattern, is reported per
pair, together with the patterns left without a partner.

A hit is identified by its bucket and its index in the input, so the two runs
must read the same n-tuple and the same events in the same order.

## Limitations

- **No pile-up truth.** The samples contain only the truth of the gun muons. In
  PG200, a pattern built from a pile-up muon has no truth muon to match and
  counts as a fake, so the fake rate there is an upper bound.
- **Missing hits are replaced.** When the muon left no hit on a surface, for
  example in an inefficient channel, the closest other hit on that surface is
  taken as the muon's.
- **One identifier per space point.** A matched two-dimensional space point
  counts for both of its coordinates.
- **sTGC channel type.** The n-tuple does not hold it, so an sTGC space point
  counts as a precision hit only when it measures η alone.
