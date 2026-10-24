<!-- Phase 5.6: Romanized/code-mixed normalization experiment - report -->
# Phase 5.6: Romanized/Code-Mixed Normalization Experiment

**Status: experiment complete. Result: the normalization layer works, and dramatically.** This is an **EXPERIMENT ONLY**. Nothing here is integrated into SmartHomes production. `services/nlp/` is unmodified. The existing 244-query English evaluation is unmodified. `evaluation/nlp_multilingual/data/multilingual_dev_queries.json` is unmodified. No commit, no push.

> IndicTrans2 performs substantially better on native-script Indic input than Romanized/code-mixed input (see [PHASE 5.5's follow-on benchmark](indictrans2_benchmark.md), section 22.7: 73.3% vs. 34.3% exact-match). This experiment evaluates whether deterministic Romanized normalization can recover the lost performance.

To be precise about what was built: this is **a small, deterministic, offline regex/lexicon rewriter** (`evaluation/nlp_multilingual/romanized_normalizer.py`), not a multilingual AI model, not machine translation, and not an LLM. It rewrites a closed set of Romanized Tamil/Hindi/Telugu function words into their English equivalents before the query reaches either IndicTrans2 or the existing English parser.

## 1. Problem

`evaluation/nlp_multilingual/results/indictrans2_benchmark.md` (section 22.7) found that IndicTrans2's Indic→English checkpoint, trained on native-script text, behaves close to an identity pass-through on romanized/code-mixed queries: English words and proper nouns are left alone, but the Tamil/Hindi/Telugu function words embedded in Latin script (postpositions like "pakkathula"/"ke paas"/"daggara" = "near") are usually left untranslated. That breaks the existing, unmodified `services/nlp/location_extractor.py`'s preposition-dependent POI pattern downstream.

## 2. Motivation

Real users type exactly this way - "Chennai la 2 BHK flat venum", "VIT ke paas 2 BHK flat chahiye" - a large, real segment of code-mixed queries a production multilingual search would need to handle. If a lightweight, explainable rule layer can recover this accuracy without a bigger model or an LLM, that is a much cheaper and more auditable fix than trying to improve translation quality itself.

## 3. Existing IndicTrans2 result (System A, reference)

Restricting the completed IndicTrans2 benchmark (`indictrans2_run_20260911T134144Z.json`) to just the 35 code-mixed (ta-en/hi-en/te-en) queries, evaluated with the exact same primitives used throughout this experiment:

| Metric | Value |
|---|---|
| Exact-match accuracy | **34.3%** |
| Intent accuracy | 100% |
| Slot precision / recall / F1 | 0.835 / 0.645 / **0.728** |
| price field recall | 0.0% |
| location field recall | 47.6% |

## 4. Failure examples (from the real 84-query dataset, not invented)

| Language | Query | IndicTrans2 output | What broke |
|---|---|---|---|
| ta-en | `VIT Chennai pakkathula flat venum` | "VIT Chennai Pakkathula Flat Venum" | "pakkathula" (near) left untranslated → parser grabs "Chennai" as a city, not "VIT Chennai" as a POI |
| hi-en | `Chennai mein 30k ke andar 2 BHK flat chahiye` | "Chennai mein 30k ke andar 2 BHK flat chhaiye" | "ke andar" (under) left untranslated → no price extracted at all |
| te-en | `Mambakkam daggara 3 BHK illu kavali` | "Mambakkam Daggara 3 BHK illu kavali" | "illu" (house) and "daggara" (near) both left untranslated → neither property_type nor location extracted |

## 5. Normalization design

`evaluation/nlp_multilingual/romanized_normalizer.py` — see its module docstring for the full, cited derivation. Summary:

- **Proper-noun protection**: any maximal run of Title-Case/ALL-CAPS tokens in the *original* query (e.g. "VIT Chennai", "Tata Homes", "SRM University", "BHK") is swapped for a placeholder before any rule runs, and restored verbatim afterward. Generic (a heuristic, not a hardcoded POI list) - works on proper nouns never seen while writing the rules.
- **Six rule groups**, every one traced to a specific query in the 84-query dataset (not a blind dictionary):
  - `pakkathula/pakkam/daggara/ke paas` → **reordered** to `near <anchor>`, moved to the end of the sentence.
  - `kulla/lopala/ke andar` → **reordered** to `under <number>` (anchored on the number, not a bare word).
  - `veedu/ghar/illu` → `house` (in-place substitution).
  - `hazaar/hazar/vela/veta` → `thousand` (in-place substitution).
  - `venum/irukkanum/chahiye/kavali/undali` → `want` (in-place substitution; not required by any observed failure, included for completeness).
  - `la/mein/lo` ("in") — evaluated and **removed** (see §6, iteration 2).
- **Deliberately NOT done**: no LLM, no paid API, no network call, no POI translation, no hardcoded coordinates, no calls to Mappls/Ola/OSM. "wala" (a generic Hindi possessive suffix, not specifically a price word) is deliberately left untouched — gold itself expects an ambiguous "eq" price for the one query that uses it, not "under".

## 6. Two iterations - real regressions found and fixed, not hidden

**Iteration 1** (plain word-for-word substitution) was tested first and found to make things *worse* in two ways, both root-caused directly against the real, unmodified `services/nlp/` code:

1. Tamil/Hindi/Telugu proximity/price words are **postpositions** (word *after* the noun: "`<place>` pakkathula"); English is prepositional ("near `<place>`"). A plain swap produced English in the wrong order ("VIT Chennai near flat want"). Confirmed directly: `extract_price("under 30000")` → lte 30000; `extract_price("30000 under")` → `None`.
2. Placing "near" directly before a bare number (an artifact of the wrong order) collided with `numeric_parser.py`'s own existing "near `<number>`" approx-price pattern. Confirmed directly: `extract_price("near 3 bhk")` → `operator='approx', value=3.0` (a real pre-existing feature of the unmodified parser, not something this experiment introduced).

**Iteration 2** fixed both with *reordering* rules (move the postposition's anchor before it, e.g. `<place> pakkathula` → `near <place>`, and move the whole `near <clause>` to the end of the sentence, matching the only sentence shape the existing POI extractor was ever exercised against — the production example `"flat for rent near VIT Chennai"`). A further bug (price anchor grabbing only "thousand" instead of "30 thousand") was found and fixed the same way — by testing, not by assumption. Iteration 1's results are preserved in `romanized_normalizer.py`'s own module docstring and in the raw JSON, for an honest record.

## 7. Pipeline variants tested

- **System A** — reference only (not re-run): `query → IndicTrans2 → parser`.
- **System B** — `query → normalizer → parser` (no translation at all).
- **System C** — `query → normalizer → IndicTrans2 → parser`.
- **System D**, as the task describes it ("normalizer + parser without IndicTrans2"), is architecturally identical to System B — not duplicated.

## 8. Dataset

- **Tuning set**: the existing 35 code-mixed queries inside `evaluation/nlp_multilingual/data/multilingual_dev_queries.json` (**unmodified** — the normalizer's lexicon was read off these queries, so results here are development/tuning numbers, not unbiased).
- **Held-out set**: `evaluation/nlp_multilingual/data/romanized_extra_cases.json` (new file, 13 queries) — new POIs (SBIOA), new price values, new BHK counts, and genuinely new combinations (furnishing + house + POI + near, all in one query) never inspected while writing the lexicon. This is the fair generalization check.

## 9. Metrics used

Exact-match accuracy, intent accuracy, slot precision/recall/F1, per-field F1 (listing_type, property_type, bedrooms, furnishing, price, area, amenities, location) — all computed by the **unmodified** `evaluate_predictions()`/`slots_from_dict()`/`FIELD_GROUPS` primitives originally written for `evaluation/nlp/evaluate_nlp.py` and already reused once by the IndicTrans2 benchmark; nothing new was invented for scoring.

## 10. Results

### Headline comparison

|                              | Exact Match | Intent | Slot F1 |
|---|---|---|---|
| **Current IndicTrans2** (System A, tuning) | 34.3% | 100% | 0.728 |
| **Normalizer only** (System B, tuning) | **85.7%** | 100% | **0.959** |
| **Normalizer + IndicTrans2** (System C, tuning) | 85.7% | 100% | 0.959 |
| Normalizer only (System B, **held-out**) | **92.3%** | 100% | 0.969 |
| Normalizer + IndicTrans2 (System C, held-out) | 92.3% | 100% | 0.969 |

**System B (normalizer alone, zero translation) took code-mixed exact-match from 34.3% to 85.7% on the tuning set and 92.3% on a genuinely held-out set never used to write the rules.** System C is identical to System B on every metric, while adding ~1.4-1.8 seconds of IndicTrans2 latency per query for **zero accuracy benefit** — inspecting the translated text confirms IndicTrans2 essentially passes already-normalized English straight through (e.g. `"flat want near VIT Chennai"` → `"flat want near vit chennai"`, a no-op besides casing).

### Per-field F1 (System B, tuning set)

| Field | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| listing_type | 1.000 | 1.000 | 1.000 | 3 |
| bedrooms | 1.000 | 1.000 | 1.000 | 15 |
| area | 1.000 | 1.000 | 1.000 | 6 |
| furnishing | 1.000 | 1.000 | 1.000 | 3 |
| location | 1.000 | 0.952 | 0.976 | 42 |
| price | 1.000 | 0.857 | 0.923 | 14 |
| property_type | 0.844 | 1.000 | 0.915 | 27 |

Every field improved versus System A; price recall (0.0% → 85.7%) and location (47.6% → 95.2%) are the largest jumps — exactly the two fields the original benchmark's failure analysis pointed at.

## 11. Language breakdown (System B, tuning set)

| Language | n | Exact-match |
|---|---|---|
| Tamil-English (ta-en) | 11 | **90.9%** |
| Hindi-English (hi-en) | 13 | 76.9% |
| Telugu-English (te-en) | 11 | **90.9%** |

All three far exceed System A's 34.3% blended average (System A's own per-language code-mixed numbers, for reference, were ta-en 36.4%, hi-en 30.8%, te-en 36.4%).

## 12. Failure breakdown (System B, tuning set - only 5 of 35 remain)

| Query | Category | Root cause |
|---|---|---|
| `30 hazaar wala flat` | numeric_unit | **Deliberate, not a bug.** "wala" is not mapped (generic possessive suffix, gold itself expects an ambiguous "eq" price). Repeated identically on the held-out set (`50 hazaar wala 3 BHK flat`) — confirms this is a consistent, understood limitation, not a one-off. |
| `SRM University pakkam flat venum` | location_poi | `missed=[]`, only an *extra* `property_type=apartment` that gold didn't assert. The parse is actually correct ("flat" does mean apartment) — this is a **gold-label completeness gap** in the original dataset, not a normalizer or parser defect. |
| `hospital ke paas flat` | nearby_facility | Same pattern as above — correct parse, extra unasserted property_type. |
| `mall daggara flat kavali` | nearby_facility | Same pattern again. |
| `Mambakkam mein flat chahiye` | location_poi | The one query using "mein" (in), not a near-word, for a POI. The "in" rule was deliberately removed (§6) since it caused a worse regression elsewhere with no net benefit — this single case remains an accepted, disclosed limitation rather than resurrecting that regression. |

Of these 5, **3 are not real parser failures at all** (correct parses marked wrong only by an incomplete gold label), 1 is an intentional, disclosed non-fix ("wala"), and 1 is an accepted trade-off. Zero are attributable to genuinely broken normalization logic.

## 13. POI (proper-noun) preservation

Checked **through normalization alone** (before any translation), on every query containing a tracked proper noun (VIT Chennai, Tata Homes, Mambakkam, SRM/SRM University, SBIOA):

| | Before (raw query, trivially 100% — untouched) | After normalization |
|---|---|---|
| Tuning set (n=16 POI-bearing queries) | 100% | **100%** |
| Held-out set (n=8 POI-bearing queries) | 100% | **100%** |

Every proper noun survived normalization verbatim, every time, on both the tuning and held-out sets. No hardcoded coordinates were used or needed — protection is via the generic Title-Case/ALL-CAPS heuristic (§5), which is why it generalized cleanly to the held-out set's new POI ("SBIOA") without being told about it in advance.

## 14. Numeric preservation

Checked the same way (normalization alone, before translation):

| | Rate |
|---|---|
| Tuning set (n=19 numeric-bearing queries) | **100%** |
| Held-out set (n=11 numeric-bearing queries) | **100%** |

No digit or unit value was altered, dropped, or reinterpreted by normalization in either set.

## 15. Native-script regression

`services/nlp` was never touched, and `romanized_normalizer.normalize()` is invoked **only** on `ta-en`/`hi-en`/`te-en` items — never on `ta`/`hi`/`te`/`en`. Verified directly: all 30 native-script (Tamil/Hindi/Telugu) queries in the main dataset pass through `normalize()` completely unchanged (`n_changed_by_normalizer: 0`) — a structural guarantee, since none of the regexes can match non-Latin Unicode script, not merely an empirical accident. The original native-script IndicTrans2 benchmark result (73.3% exact-match) is untouched and unaffected by anything in this experiment.

## 16. Limitations

- **Closed vocabulary.** The lexicon covers exactly the words observed in the 84-query dataset (plus a few explicitly-requested synonyms like "irukkanum"/"undali"). A genuinely novel Romanized word or dialectal variant not in this list will simply pass through unrecognized — this is a rule-based system, not a model, and does not generalize beyond its lexicon the way a trained model might.
- **"wala" and similar generic suffixes remain unhandled** by design — mapping them would require semantic disambiguation this deterministic layer deliberately does not attempt.
- **Single-anchor reordering only.** The "near"/"under" reorder rules assume exactly one postposition clause per query and a single-token (or placeholder) anchor immediately before it — true for every query in this 84+13-query dataset, but a more complex sentence structure (e.g. two separate POIs, or an anchor phrase that isn't Title-Case-protected and contains multiple lowercase words) is out of this experiment's tested scope.
- **This is not machine translation and does not claim to be.** It is a deterministic, auditable regex/lexicon rewriter targeting the exact function words this dataset's failures were traced to. It will not help with code-mixed vocabulary or sentence structures outside that scope.
- **Gold-label completeness gaps exist in the underlying dataset** (§12) independent of this experiment — 3 of the 5 remaining "failures" are really correct parses marked wrong by an incompletely-specified `expected` block, a pre-existing dataset-authoring nuance, not a normalizer or parser defect.

## Recommendation

**Proceed with this normalization approach as the practical path forward for code-mixed queries** — it is simple, deterministic, fully auditable, requires no model, no GPU, no network call, and no new dependency, and it took code-mixed exact-match from 34.3% to 85.7% (tuning) / 92.3% (held-out), matching or exceeding even the native-script IndicTrans2 result (73.3%). **IndicTrans2 itself adds no value on top of it for code-mixed queries** (System C = System B, plus ~1.4-1.8s of unnecessary latency) — if code-mixed support were ever integrated, IndicTrans2 would not be needed for that specific language mode, only for genuine native-script queries (where it remains the viable option, per the prior benchmark).

This remains **an experiment only.** No production integration has been made. If the team wants to pursue this further, the next step is a separate, explicitly-scoped integration decision (where to route code-mixed vs. native-script vs. English queries, how to expand the lexicon safely over time, and whether/how to test it against a larger, independently-collected code-mixed sample) — not a continuation of this benchmark phase.
