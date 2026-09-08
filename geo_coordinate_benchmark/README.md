# Geo Coordinate Benchmark: OSM vs Overture (Mappls-resolved input)

Standalone research only. Does **not** touch SmartHomes production code
(`routes/`, `templates/`, `services/`, `app.py`, MongoDB, or the existing
GeoSpatial implementation). Excluded from git the same way `mappls_geo_test/`
and `osm_test/` are (matches the repo's existing `*test` gitignore pattern
is NOT applicable here since this folder doesn't end in "test" -- see repo
root `.gitignore` if you want it excluded too).

## Question being tested

```
User query -> Mappls -> resolved POI (placeName + placeAddress + eLoc)
                                |
                                v
                  [can OSM or Overture recover coordinates
                   for that SAME entity, independently?]
```

Geoapify is intentionally excluded (already evaluated separately in
`../geo_reconciliation_test/`).

## Files

- `dataset.py` -- loads the 31 Mappls-resolved test cases (30 reused from
  `../geo_reconciliation_test/results/benchmark_results.json`, 1 new).
- `matcher.py` -- shared transparent multi-signal entity-matching scorer
  used identically by both resolvers, so OSM and Overture are judged by
  the same yardstick. Deliberately separates entity-match scoring from
  geometry-quality evaluation (never merged).
- `osm_resolver.py` -- Nominatim-based resolver, policy-compliant (throttled,
  cached, identifying User-Agent, no autocomplete/bulk use).
- `overture_resolver.py` -- Overture Places resolver via the official
  `overturemaps` CLI (bounding-box download + local matching).
- `run_osm_benchmark.py` / `run_overture_benchmark.py` -- runners (kept
  separate because the two sources have wildly different practical
  performance -- see Performance below).
- `ground_truth.py` -- reference coordinates used ONLY for post-hoc
  geometry evaluation, each labeled with its confidence basis; cases with
  no reliable reference are explicitly `unknown`, never guessed.
- `evaluation.py` -- combines both result sets + ground truth into
  `results/benchmark_results.json`.
- `make_summary_csv.py` -- flattens that into `results/summary.csv`.

## Why OSM got all 31 cases but Overture only got a 12-case subset

Nominatim is a live search API: each of the 31 lookups took a few seconds
(31 queries completed in ~95 seconds total, policy-compliant throttling
included).

Overture Places is **not** a search API -- it's a versioned Parquet dataset
on public cloud storage. Every access method tested (the official
`overturemaps` CLI, and raw DuckDB `read_parquet` against S3 directly) took
**~4-5 minutes for a single ~16 km² bounding-box query**, because the
dataset has no geographic partitioning in its storage layout -- a query has
to touch a large fraction of the global file set regardless of how small
the requested area is. A single query covering the whole Chennai metro area
was extrapolated (from observed per-place overhead) to take multiple hours,
and was not attempted in full. This performance profile is itself an
important finding (see the final report), not an artifact of a
mis-implementation -- both tested access methods showed the same cost.

Given that, Overture was tested against a **deliberately chosen
representative subset of 12 cases** covering every "difficult case" this
task named, run as parallel background downloads. Each subset case's
bounding-box center is documented in `run_overture_benchmark.py` -- almost
always OSM's own independently-found coordinate for that same query, used
only to narrow the download window, never as an answer fed into matching.

## Reproducing

```bash
python run_osm_benchmark.py        # ~2 minutes, hits public Nominatim (respects 1 req/s)
python run_overture_benchmark.py   # ~10-20 minutes, parallel downloads, hits public Overture S3
python evaluation.py               # combine + apply ground truth -> results/benchmark_results.json
python make_summary_csv.py         # -> results/summary.csv
```

All external responses are cached under `cache/` so re-running after the
first pass does not re-hit either public service.
