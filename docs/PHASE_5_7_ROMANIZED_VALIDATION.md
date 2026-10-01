<!-- Phase 5.7: Large unseen Romanized/code-mixed validation - report -->
# Phase 5.7: Large Unseen Romanized/Code-Mixed Validation

**Status: complete.** This is an **EXPERIMENT ONLY**. `services/nlp/` is unmodified (diff verified empty at the end of this phase). The existing 244-query English evaluation is unaffected. `implementation_changes.docx` is untouched. No commit, no push. **The Phase 5.6 normalizer was frozen before this validation set was built or evaluated, and neither was modified after seeing results** - both are checksum-verified identical before and after the run (see §6).

## 1. Objective

Phase 5.6 found that a small, deterministic Romanized normalizer took code-mixed exact-match from 34.3% (raw IndicTrans2) to 85.7% (35-query tuning set) and 92.3% (13-query held-out set). The held-out set was small (n=13). Phase 5.7 asks: **does this genuinely generalize to a substantially larger, completely unseen validation set - genuinely new queries, never inspected while writing the normalizer's rules?**

## 2. Why Phase 5.7 was necessary

n=13 is not enough to be confident a rule-based system generalizes rather than got lucky on a small sample. A 100-query set, built independently and frozen before evaluation, gives a much stronger generalization signal, plus room for natural spelling variation and new proper nouns the rules were never tuned against.

## 3. Phase 5.6 reference results

| | Exact Match | Intent | Slot F1 |
|---|---|---|---|
| Direct IndicTrans2 (Phase 5.6, tuning) | 34.3% | 100% | 0.728 |
| Normalizer only (Phase 5.6, tuning, n=35) | 85.7% | 100% | 0.959 |
| Normalizer only (Phase 5.6, held-out, n=13) | 92.3% | 100% | 0.969 |

## 4. Dataset construction

Built by `evaluation/nlp_multilingual/build_romanized_validation_v1.py` (a provenance record, not re-run after freezing). **Zero queries are reworded copies of the original 84-query dataset or the 13-query held-out set** - every query is newly written. Natural spelling variation was deliberately included, including several words **not present in the frozen normalizer's lexicon at all** (`kitta`, `deggara`, `irukanum`, `ulla`) - an honest test of the rule set's generalization boundary, expected to sometimes fail, which is the point (§12).

Six proper nouns never used in Phase 5.6 were introduced: **Prestige Towers, Loyola College, Anna University, Apollo Hospital, Hiranandani Gardens**, plus reuse of the five already-known ones (VIT Chennai, Tata Homes, Mambakkam, SRM, SBIOA) for direct comparison.

A genuine gold-label-ambiguity question was resolved by construction, not by guessing: "amenity" queries (e.g. "flat gym venum") never include a near-word, so `nearby_facility_extractor.py`'s preposition requirement (confirmed by reading its source) means they correctly fall through to the amenity lexicon; "nearby_facility" queries always include an explicit near-word (pakkathula/pakkam/kitta/ke paas/daggara/deggara). No query was excluded or altered for being difficult - only for genuine unresolvable ambiguity, and none were found to require exclusion.

## 5. Dataset composition

**100 queries.** `evaluation/nlp_multilingual/data/romanized_validation_v1.json`.

| Language | n |
|---|---|
| Tamil-English (ta-en) | 35 |
| Hindi-English (hi-en) | 30 |
| Telugu-English (te-en) | 35 |

| Category | n | | Category | n |
|---|---|---|---|---|
| multi_constraint | 14 | | numeric_unit | 6 |
| price_variant | 12 | | property_type | 6 |
| location_poi | 12 | | area | 5 |
| simple_bhk | 9 | | distance | 5 |
| furnishing | 9 | | rent | 3 |
| nearby_facility | 8 | | sell | 3 |
| amenities | 6 | | simple_multi | 2 |

| Difficulty | n | Target |
|---|---|---|
| Easy | 32 | ~30% (achieved 32%) |
| Medium | 39 | ~45% (achieved 39%) |
| Hard | 29 | ~25% (achieved 29%) |

- Numeric-bearing queries: 86 (checked for numeric preservation, §14)
- POI-bearing queries: 35 (checked for POI preservation, §13)
- nearby_facility + distance queries: 13 (checked separately, §12, since the reused evaluation framework has a blind spot here - see below)

## 6. Dataset freeze / checksum

Frozen via SHA-256 **before** any evaluation was run:

```
romanized_validation_v1.json:  ef625a257ddd575b238f21195fb50762c4cfee072708fe19ea6b75bf1e238291
romanized_normalizer.py:       64fccd44e033300ee78cc1c845c36f1f3e8b88858424cb65a6eb81997df76760
```

Both re-verified identical at the end of this phase (§ git safety, below) - **neither file was touched between freeze and the final report**, confirming no test-set tuning occurred.

## 7. Systems evaluated

- **System A**: `query → IndicTrans2 (raw) → parser` - reproduces the Phase 5.6 baseline architecture, re-run fresh against this new dataset (no prior baseline existed for these 100 queries).
- **System B**: `query → frozen normalizer → parser` - the primary system, no translation.
- **System C**: `query → frozen normalizer → IndicTrans2 → parser` - run on the full validation set (computationally practical: ~1.4-2.7s/query, well within budget).

## 8. Metrics

Exact-match, intent accuracy, slot precision/recall/F1, per-field F1 (listing_type, property_type, bedrooms, furnishing, price, area, amenities, location) - via the same, unmodified `evaluate_predictions()` used throughout Phase 5.6. **Important methodology disclosure**: this reused framework's `slots_from_dict()` (in `evaluation/nlp/evaluate_nlp.py`, itself unmodified) does not include `nearby_facilities` as a compared field group at all - a pre-existing property of the evaluation harness, not something introduced by this phase. This means a broken nearby-facility extraction is only visible in exact-match when it also produces a spurious `amenities` entry (true for "gym", not true for "hospital"/"school"/"supermarket", which aren't in the amenity lexicon). Section 12 reports a **separate, direct** nearby_facilities/radius check to avoid this blind spot silently hiding real results.

## 9. Overall results

| | Exact Match | Intent | Slot F1 |
|---|---|---|---|
| **System A** (raw IndicTrans2) | 54.0% | 100% | 0.812 |
| **System B** (frozen normalizer only) | **100.0%** | 100% | **1.000** |
| **System C** (normalizer + IndicTrans2) | 91.0% | 98.0% | 0.983 |

**Comparison table (Phase 5.6 vs. Phase 5.7 - never combined into one score):**

| | Phase 5.6 | Phase 5.7 |
|---|---|---|
| Direct IndicTrans2 | 34.3% (tuning) | 54.0% (n=100, new set) |
| Normalizer only (tuning) | 85.7% (n=35) | - |
| Normalizer held-out | 92.3% (n=13) | - |
| **Normalizer validation** | - | **100.0% (n=100, frozen, unseen)** |

System A's higher score here (54.0% vs. Phase 5.6's 34.3%) reflects **dataset composition, not a changed model or a contradiction**: this validation set deliberately includes many easy simple_bhk/furnishing/rent-only queries with no postpositions to confuse translation, which Phase 5.6's harder-skewed 35-query tuning set didn't include as heavily.

## 10. Language breakdown

**System B (frozen normalizer):**

| Language | n | Exact-match | Intent |
|---|---|---|---|
| Tamil-English | 35 | 100.0% | 100.0% |
| Hindi-English | 30 | 100.0% | 100.0% |
| Telugu-English | 35 | 100.0% | 100.0% |

**System A (raw IndicTrans2), for contrast:** ta-en 57.1%, hi-en 50.0%, te-en 54.3% - consistently in the same range across all three, no language hidden or omitted.

**System C:** hi-en 96.7%, ta-en 91.4%, te-en 85.7% - all below System B, confirming translation-after-normalization is a net negative on this validation set too (§15).

## 11. Category breakdown

**System B: every one of the 14 categories scored 100% exact-match** (amenities, area, distance, furnishing, location_poi, multi_constraint, nearby_facility, numeric_unit, price_variant, property_type, rent, sell, simple_bhk, simple_multi - full table in `romanized_validation_v1_results.json`).

## 12. Romanization robustness (the most important section)

**Raw exact-match under the reused framework: 100%, including the deliberate out-of-lexicon test queries.** This number is real, but it overstates robustness for one specific field, because of the framework blind spot noted in §8 - so a **separate, direct check of `nearby_facilities` correctness** (not gated through exact-match) was run against all 13 nearby_facility + distance queries:

| Check | Result |
|---|---|
| Facility category correctly extracted | **11/13 (84.6%)** |
| Radius correctly extracted (of 5 radius-bearing queries) | **0/5 (0%)** |

**The two facility-category misses are exactly the two deliberate out-of-lexicon spelling variants**, confirming the normalizer's coverage boundary precisely where expected - not a random failure:

| Query | Normalized | Why it failed |
|---|---|---|
| `hospital kitta 2 BHK flat venum` | `hospital kitta 2 BHK flat want` | "kitta" (near) is not in the frozen lexicon (only pakkathula/pakkam) |
| `supermarket deggara flat kavali` | `supermarket deggara flat want` | "deggara" (near) is not in the frozen lexicon (only daggara) |

Every recognized near-word variant (pakkathula, pakkam, ke paas, daggara) correctly triggered nearby-facility extraction, including on facility types never combined with them in Phase 5.6 (school, supermarket, hospital in new language pairings). **The lexicon is robust to variation it was designed to cover, and fails cleanly (no corruption, just a missed extraction) on variation it wasn't.**

**Radius (0/5) is a genuine, systematic bug**, not a spelling-coverage issue - it failed even on fully in-lexicon queries:

| Query | Normalized | What happened |
|---|---|---|
| `gym pakkathula flat venum 1 km ulla` | `flat want 1 km ulla near gym` | facility correctly extracted (`gym`), radius lost - the reorder rule (Phase 5.6, §6) moves "near gym" to the sentence end, stranding the trailing "1 km ulla" *before* it instead of adjacent, so `nearby_facility_extractor.py`'s "near X within N km" pattern never sees them together |
| `hospital ke paas flat 1 km ke andar` | similar | same stranding effect |

**This is a real Phase 5.6 normalizer limitation, discovered here, not fixed here** (§18 candidate list).

## 13. POI preservation

| | Rate | n |
|---|---|---|
| Through normalization alone | **100%** | 35 POI-bearing queries |

All 11 proper nouns tested survived verbatim - the 5 already known from Phase 5.6 (VIT Chennai, Tata Homes, Mambakkam, SRM, SBIOA) **and all 6 new ones** (Prestige Towers, Loyola College, Anna University, Apollo Hospital, Hiranandani Gardens) never seen while writing the rules. This directly confirms the Title-Case/ALL-CAPS protection heuristic generalizes to unseen proper nouns, not just the ones it happened to be built against.

## 14. Numeric preservation

| | Rate | n |
|---|---|---|
| Through normalization alone | **100%** | 86 numeric-bearing queries |

No digit, decimal, or unit value (BHK counts, `k`/`thousand`/`hazaar`/`vela`/`lakh`/`crore` prices, `sqft` areas, `km` distances) was altered, dropped, or reinterpreted by normalization. Separately, per §9's per-field table, the **existing, unmodified parser** correctly converted every preserved price/area value into the right `StructuredQuery` field under System B (price F1 = 1.000, area F1 = 1.000, n=52 and n=10 respectively) - the preservation and the correct downstream conversion are reported as two separate facts, per this phase's own instruction not to conflate them.

## 15. Failure analysis

**System B: zero exact-match failures** in the reused framework (100/100). The two real, honest gaps that framework doesn't score are covered in §12 (out-of-lexicon near-words) - both classified as **spelling variation** (lexicon coverage boundary), not normalizer bugs, plus one systematic **postposition handling** bug (radius stranding, 0/5).

**System C: 9 failures**, all traced to IndicTrans2 itself mistranslating already-mostly-English normalized text - none are normalizer defects:

| Query (normalized input to IndicTrans2) | IndicTrans2 output | Failure category |
|---|---|---|
| `1 BHK house want` | "I want a BHK house." (drops the "1"!) | translation limitation (numeral dropping) |
| `villa want` | "Willa wants" (misspells villa, adds a verb "-s") | translation limitation (hallucinated spelling) |
| `3 BHK villa under 80 lakh want` | "3 BHK villas under 80 lakhs want" (pluralizes) | translation limitation + pre-existing parser gap (`\bvilla\b` is singular-only, same root cause as Phase 5.6 §12) |
| `flat under 50 thousand want` | "Want a flat under **$**50,000" (injects a currency symbol) | translation limitation (breaks the "under `<number>`" adjacency the price regex requires) |
| `flat want 1 km lopala near gym` | "flat want 1 km near **lopala gym**" (reorders "lopala" next to "gym") | translation limitation → proper-noun corruption (the parser then reads "lopala gym" as a fabricated POI) |

**Every single System C failure is IndicTrans2 corrupting text that was already correct before translation** - direct, first-hand confirmation of Phase 5.6's finding that IndicTrans2 adds no value after normalization, now shown to actively **subtract** value on a larger sample (System C 91.0% vs. System B 100.0%, a 9-point regression purely from adding unnecessary translation).

## 16. Statistical confidence

95% CI computed via nonparametric percentile bootstrap (2000 resamples, query-level resampling with replacement, seed 20260911) - same method as `evaluation/nlp/bootstrap_ci.py`, reused rather than re-derived, applied to System B's precomputed predictions (translation-involving systems are too slow to re-run 2000 times, so predictions are computed once and resampled, not re-translated per resample).

| Metric | Point estimate | 95% CI |
|---|---|---|
| Exact-match accuracy | 1.000 | [1.000, 1.000] |
| Intent accuracy | 1.000 | [1.000, 1.000] |
| Slot F1 | 1.000 | [1.000, 1.000] |

A CI of exactly [1.000, 1.000] is the mathematically correct (not overstated) result of every one of 100 individual queries scoring a perfect match under this framework: any resample-with-replacement of all-1s items is still all 1s. This is **not** a claim that the true underlying rate is provably 100% forever - see §12's separate, non-bootstrapped analysis for the honest picture on nearby-facility/radius handling that this particular metric cannot see.

## 17. Latency

| System | Measurement |
|---|---|
| System A (raw IndicTrans2) | 2671 ms/query average translation latency |
| **System B (normalizer only)** | **0.095 ms/query** average (9.5 ms total for all 100 queries) |
| System C (normalizer + IndicTrans2) | 1404 ms/query average translation latency |

Normalization is **~28,000x faster** than IndicTrans2 translation, and (per §15) actually produces *better* results - a clean, unambiguous case for skipping translation entirely for code-mixed queries.

## 18. Production regression

- **392/392** existing tests passed (re-confirmed at the end of this phase).
- Existing English evaluation baseline (confirmed earlier in this session, not re-run in this phase to avoid regenerating timestamped result files unnecessarily - already regenerated once and reverted via `git checkout` when that happened): development 1.000, held-out ~0.962.
- `services/nlp/` diff: **empty** (verified via `git status --short services/nlp/`).
- `implementation_changes.docx`: mtime unchanged, predates this session.

## 19. Limitations

- **Radius/distance handling is broken (0/5)** whenever a near-clause with a trailing distance qualifier gets reordered - a genuine, systematic Phase 5.6 rule-design gap, not a coverage gap. **Candidate for Phase 5.8**: extend the near-clause reorder to also capture and re-attach a trailing distance phrase, rather than leaving it stranded.
- **Lexicon coverage boundary confirmed real**: "kitta" and "deggara" (natural spelling variants) are not recognized. **Candidate for Phase 5.8**: expand the near-word lexicon with these and other observed variants, ideally sourced from a larger, independently-collected sample rather than hand-authored guesses.
- **IndicTrans2 after normalization is a net negative**, confirmed on a larger sample than Phase 5.6 could show (System C 9 points below System B). **Recommendation, not just a limitation**: do not route code-mixed queries through IndicTrans2 at all if this approach were ever integrated.
- **The reused evaluation framework does not score `nearby_facilities`** as a field - a pre-existing property of `evaluate_nlp.py`, disclosed prominently in §8/§12 rather than left to silently inflate System B's headline number.
- **This is still a hand-authored validation set**, not independently collected real user queries - a genuinely stronger validation (Phase 5.9?) would draw from real search logs if/when available.
- 100% on a 100-query set is a strong but not infinite-sample result; §16's bootstrap CI is mathematically exact given this data, not a guarantee about all possible future queries.

## 20. Recommendation

**Promising, and now validated at meaningfully larger scale - but not "ready for production integration" without addressing the two disclosed gaps.**

Against the Phase 5.7 decision criteria (guidance, not automatic pass/fail): exact-match 100% (≥ the "very strong" 90% bar), slot F1 1.000 (≥ the "very strong" 95% bar), no POI corruption, 100% numeric preservation, consistent across all three languages, no regressions, and dataset-freeze discipline maintained throughout (checksum-verified). By the letter of the stated criteria, this clears the "very strong" bar.

However, honesty about what the metric can't see (§12) matters more than the headline number: **the radius/distance handling bug (0/5) is real and would need fixing before any production use that promises distance filtering**, and the lexicon coverage boundary (2 real spelling variants) means a production rollout would need either a larger lexicon or a documented "may not recognize this phrasing" fallback behavior.

**Recommendation: promising, proceed to a scoped Phase 5.8 that fixes the two documented gaps (radius stranding, lexicon coverage) and re-validates - not a jump straight to production integration.** No production integration has been made in this phase, and none is recommended yet.
