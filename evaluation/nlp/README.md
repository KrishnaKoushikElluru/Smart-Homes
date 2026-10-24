# NLP evaluation datasets (Phase 2 / Phase 2.5)

This directory holds the evaluation harness for `services/nlp/` (the
Phase 2 query-understanding pipeline). Phase 2.5 (see
`docs/PHASE_2_5_NLP_EVALUATION.md`) split what was originally a single
dataset into two, to answer a specific, valid criticism: *"your parser
got 100% because you tested only a small curated dataset it was tuned
against."*

## The two datasets

| | Development set | Held-out test set |
|---|---|---|
| Path | `data/development_queries.json` (also readable at the original `queries.json`, identical content, kept for backward compatibility) | `data/test_queries.json` |
| Built by | `build_dataset.py` | `build_test_dataset.py` |
| Size | 112 | 132 |
| Composition | 67 hand-crafted, 45 generated | 86 hand-authored, 46 generated |
| Purpose | Iteratively design and debug the parser against | Measure generalization ONCE, honestly, without further tuning |
| Geographic bias | Chennai / Tamil Nadu-heavy | Deliberately multi-city (Bengaluru, Hyderabad, Mumbai, Delhi, Pune, Kolkata, Coimbatore, Vellore, plus non-gazetteer towns) |

**Combined: 244 queries**, above the 150-200 target in the Phase 2.5
brief - more genuine held-out data only strengthens the measurement, so
the extra volume was kept rather than trimmed for a round number.

## The no-tuning-against-the-test-set rule

This is the one rule Phase 2.5 exists to enforce, so it is written down
explicitly:

**The parser (`services/nlp/*.py`) may never be modified specifically to
make `data/test_queries.json` score higher.** The workflow, in order:

1. Write/modify parser code.
2. Evaluate against the **development** set. Fix real bugs there,
   iterate freely - that dataset exists to be iterated against.
3. Freeze the parser.
4. Run the held-out test set **once**, as a final check.
5. If a held-out failure is found: record it, classify it (genuine bug
   / documented unsupported capability / dataset annotation mistake),
   and only fix the underlying **parser** if it's a genuine, general
   bug - verified by re-running the development set (must not regress)
   and adding a **new regression case to `test_nlp_parser.py`**, never
   by editing `test_queries.json`'s `expected` block to match whatever
   the parser happened to output.

This rule was exercised for real during Phase 2.5, not just written
down: the held-out run found one genuine bug (`"terrace garden"` also
producing a spurious bare `"garden"` amenity - a real pattern-overlap
defect in `services/nlp/entity_extractor.py`, invisible to the
development set because it never combined those two amenities in one
query). It was fixed in the parser, a regression test was added to
`test_nlp_parser.py`, the development set was re-run to confirm no
regression (stayed at 1.000), and only then was the held-out set
re-run. See `docs/PHASE_2_5_NLP_EVALUATION.md` section 12 for the full
account.

## Annotation methodology

- **Hand-authored queries** (67 dev + 86 test = 153 total): each one
  individually written and its `expected` block individually reasoned
  through against the actual documented regex behavior of
  `services/nlp/*.py` (operator-word lists, property-type lexicon
  order, the location-masking pipeline, known-city gazetteer) - not
  generated, not copy-pasted from another query with values swapped.
  There is no second human annotator on this project, so no
  inter-annotator-agreement statistic is claimed; these are described
  honestly as **manually authored and reviewed by the project author**,
  not independently double-annotated.
- **Generated queries** (45 dev + 46 test = 91 total): built by a
  parameter-grid generator where the query text and its `expected`
  ground truth are **computed from the same parameters** (e.g. a price
  operator word + a magnitude number produces both the query string and
  its expected `RangeConstraint`). This guarantees correctness at a
  volume that would be impractical to hand-transcribe reliably -
  standard practice for NLU evaluation sets (the ATIS/SNIPS
  methodology). Generated data is **not** a substitute for
  independently-authored human queries and is never presented as such -
  every dataset file and every report table states the hand-authored /
  generated split plainly.
- The development and held-out generated grids deliberately use
  **different axes** (different property-type words, different price
  operators/magnitudes, different cities, different amenity codes) so
  the held-out generated half is not simply the development grid
  re-run with new numbers.

## Typos: measured, not fixed

`data/test_queries.json`'s `"typo"` category (4 queries) contains
genuine, realistic misspellings (`"appartment"`, `"furnshed"`,
`"parkin"`, `"villaa"`) with **ideal, correct** `expected` ground truth
- i.e. what a human reader would want extracted despite the typo, not
what the regex-based parser can actually produce. This is intentional:
the resulting score drop is real and documents an honest, known
limitation (no fuzzy/edit-distance matching), rather than being
papered over by writing `expected` to match the parser's degraded
output. See `docs/PHASE_2_5_NLP_EVALUATION.md` sections 9 and 12.

## Regenerating the datasets

```
python evaluation/nlp/build_dataset.py       # development set
python evaluation/nlp/build_test_dataset.py  # held-out test set
python evaluation/nlp/evaluate_nlp.py        # runs both, writes results/
python evaluation/nlp/ablation.py            # ablation study, both datasets
python evaluation/nlp/bootstrap_ci.py        # 95% CI on the held-out set
python evaluation/nlp/error_analysis.py      # categorized failure breakdown
```

## Known dataset limitations

- Still small by general NLU-research standards (244 combined) - large
  enough to support the bootstrap confidence intervals in
  `docs/PHASE_2_5_NLP_EVALUATION.md` section 10, not large enough to
  treat a single point estimate as precise to the third decimal place.
- Single-annotator (no inter-annotator agreement statistic).
- Still India/English-only, still real-estate-domain-only by design -
  this is a domain-specific parser for a specific application, not a
  general-purpose NLU benchmark.
- The held-out set's typo coverage (4 queries) is illustrative, not
  exhaustive - it demonstrates that typos are a real, uncorrected gap,
  not a full characterization of every misspelling class.
- `property_type == "other"` has no way to be triggered from free text
  at all (no lexicon phrase maps to it - it exists as a catch-all UI
  option in `services/property_fields.py`), so neither dataset can test
  it. Not a bug; noted here so its absence from every results table
  isn't mistaken for an oversight.
