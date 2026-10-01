"""
EXPERIMENT-ONLY. Romanized/code-mixed normalization experiment runner.

Answers one question: does evaluation/nlp_multilingual/romanized_normalizer.py
(a small, deterministic, offline lexicon of Romanized Tamil/Hindi/Telugu
function words) recover any of the accuracy IndicTrans2 loses on
Romanized/code-mixed input (34.3% exact-match vs. 73.3% for native
script - see indictrans2_benchmark.md section 22.7)?

Three systems, all reusing the existing, UNMODIFIED English parser
(services/nlp/parser.py) and the existing evaluation primitives
(evaluation/nlp/evaluate_nlp.py, via run_indictrans2_benchmark.py) rather
than re-deriving slot-comparison logic a third time:

    SYSTEM A (reference, not re-run): the already-completed IndicTrans2
        baseline from indictrans2_run_20260911T134144Z.json, restricted
        to the code-mixed (ta-en/hi-en/te-en) subset.
    SYSTEM B: query -> romanized_normalizer.normalize() -> parser.
        No IndicTrans2 involved at all.
    SYSTEM C: query -> romanized_normalizer.normalize() -> IndicTrans2
        -> parser.
    (System D, as the task describes it, is architecturally identical to
    System B - "normalizer + parser without IndicTrans2" - so its
    numbers are B's; no separate run is duplicated.)

Run on the TUNING set (the existing 84-query dataset's 35 code-mixed
rows - the same queries the normalizer's lexicon was read off of, see
romanized_normalizer.py's module docstring) AND on a genuinely separate
HELD-OUT set (evaluation/nlp_multilingual/data/romanized_extra_cases.json,
13 new queries in new combinations, never looked at while writing the
lexicon) so the tuning-set numbers are never mistaken for an unbiased
result.

Run ONLY inside the isolated WSL benchmark venv (~/smarthomes_benchmark/.venv)
for the System C leg (needs IndicTrans2); System B needs nothing but the
stdlib and can run anywhere Python + this repo are available.

Writes: evaluation/nlp_multilingual/results/romanized_experiment.json
Does not touch indictrans2_benchmark.json/.md, multilingual_dev_queries.json,
services/nlp/, or the production English evaluation.
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from services.nlp.parser import parse  # noqa: E402
from romanized_normalizer import normalize  # noqa: E402
from run_indictrans2_benchmark import (  # noqa: E402
    load_model, translate_batch, LANG_TO_FLORES, TGT_LANG,
    evaluate_predictions, category_breakdown, language_breakdown,
    check_poi_preserved, check_numeric_preserved, POI_TERMS,
)

HERE = Path(__file__).resolve().parent
DATA_PATH = HERE / "data" / "multilingual_dev_queries.json"
HELDOUT_PATH = HERE / "data" / "romanized_extra_cases.json"
BASELINE_RUN_PATH = HERE / "results" / "indictrans2_run_20260911T134144Z.json"
OUT_DIR = HERE / "results"

CODE_MIXED_LANGS = ("ta-en", "hi-en", "te-en")
NATIVE_LANGS = ("ta", "hi", "te")


def system_a_reference(main_dataset: list) -> dict:
    """System A: NOT re-run - reuses the already-completed IndicTrans2
    baseline (indictrans2_run_20260911T134144Z.json), restricted to the
    code-mixed subset, via the SAME evaluate_predictions aggregation the
    other two systems use, for a like-for-like comparison."""
    raw = json.loads(BASELINE_RUN_PATH.read_text(encoding="utf-8"))
    by_id = {it["id"]: it for it in main_dataset}
    pairs = []
    for row in raw["per_query"]:
        if row["language"] in CODE_MIXED_LANGS:
            pairs.append((by_id[row["id"]], row["predicted"]))
    return evaluate_predictions(pairs)


def system_b(items: list) -> tuple[dict, dict]:
    """query -> normalize() -> parse(). No translation. Returns
    (evaluation_dict, {id: normalized_text})."""
    pairs = []
    normalized_text = {}
    for it in items:
        norm = normalize(it["query"])
        normalized_text[it["id"]] = norm
        predicted_sq = parse(norm)
        pairs.append((it, predicted_sq.to_dict()))
    return evaluate_predictions(pairs), normalized_text


def system_c(items: list, tokenizer, model, ip) -> tuple[dict, dict, dict, list]:
    """query -> normalize() -> IndicTrans2 -> parse(). Returns
    (evaluation_dict, {id: normalized_text}, {id: translated_text}, latencies_ms)."""
    normalized_text = {}
    translations = {}
    latencies_ms = []
    by_flores = defaultdict(list)
    for it in items:
        norm = normalize(it["query"])
        normalized_text[it["id"]] = norm
        by_flores[LANG_TO_FLORES[it["language"]]].append(it)

    BATCH = 8
    for flores_lang, group in by_flores.items():
        for i in range(0, len(group), BATCH):
            chunk = group[i:i + BATCH]
            sentences = [normalized_text[it["id"]] for it in chunk]
            t0 = time.time()
            try:
                outputs = translate_batch(sentences, flores_lang, tokenizer, model, ip)
                per_item_ms = (time.time() - t0) * 1000 / len(chunk)
                for it, out in zip(chunk, outputs):
                    translations[it["id"]] = out
                    latencies_ms.append(per_item_ms)
            except Exception as e:
                for it in chunk:
                    translations[it["id"]] = None
                    latencies_ms.append((time.time() - t0) * 1000 / len(chunk))

    pairs = []
    for it in items:
        text = translations.get(it["id"]) or ""
        predicted_sq = parse(text)
        pairs.append((it, predicted_sq.to_dict()))
    return evaluate_predictions(pairs), normalized_text, translations, latencies_ms


def poi_and_numeric_through_normalization(items: list, normalized_text: dict) -> tuple[list, list]:
    """Phase 7/8: does normalize() ALONE (before any translation) preserve
    proper nouns and numbers? Reuses the same check_* helpers the
    IndicTrans2 benchmark used for translation, applied here to
    (original, normalized) pairs instead of (original, translated)."""
    poi_results, numeric_results = [], []
    for it in items:
        norm = normalized_text[it["id"]]
        poi = check_poi_preserved(it["query"], norm)
        if poi is not None:
            poi.update({"id": it["id"], "query": it["query"], "normalized": norm})
            poi_results.append(poi)
        num = check_numeric_preserved(it["query"], norm)
        if num is not None:
            num.update({"id": it["id"], "query": it["query"], "normalized": norm})
            numeric_results.append(num)
    return poi_results, numeric_results


def native_script_passthrough_check(main_dataset: list) -> dict:
    """Phase 9: normalize() must be a no-op on native-script input."""
    native_items = [it for it in main_dataset if it["language"] in NATIVE_LANGS]
    unchanged = [it["id"] for it in native_items if normalize(it["query"]) == it["query"]]
    changed = [it["id"] for it in native_items if normalize(it["query"]) != it["query"]]
    return {
        "n_native_script_queries": len(native_items),
        "n_unchanged_by_normalizer": len(unchanged),
        "n_changed_by_normalizer": len(changed),
        "changed_ids": changed,
        "passthrough_confirmed": len(changed) == 0,
    }


def summarize(label, ev):
    print(f"\n=== {label} ===")
    print(f"  n={ev['n_queries']}  exact_match={ev['exact_match_accuracy']:.3f}  "
          f"intent_acc={ev['intent_accuracy']:.3f}  slot_P={ev['slot_precision']:.3f}  "
          f"slot_R={ev['slot_recall']:.3f}  slot_F1={ev['slot_f1']:.3f}")


def main():
    print(f"Loading main dataset from {DATA_PATH}")
    main_dataset = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    code_mixed = [it for it in main_dataset if it["language"] in CODE_MIXED_LANGS]
    print(f"  {len(main_dataset)} total, {len(code_mixed)} code-mixed (tuning set)")

    print(f"Loading held-out dataset from {HELDOUT_PATH}")
    heldout = json.loads(HELDOUT_PATH.read_text(encoding="utf-8"))
    print(f"  {len(heldout)} held-out queries (never seen while writing romanized_normalizer.py)")

    # ---- System A: reference, not re-run ----
    a_tuning = system_a_reference(main_dataset)
    summarize("SYSTEM A (IndicTrans2 baseline, reference) - tuning set", a_tuning)

    # ---- System B: normalizer + parser, no translation ----
    b_tuning, b_tuning_norm = system_b(code_mixed)
    summarize("SYSTEM B (normalizer only) - tuning set", b_tuning)
    b_heldout, b_heldout_norm = system_b(heldout)
    summarize("SYSTEM B (normalizer only) - HELD-OUT set", b_heldout)

    # ---- Phase 7/8 (normalization-only preservation) ----
    poi_tuning, num_tuning = poi_and_numeric_through_normalization(code_mixed, b_tuning_norm)
    poi_heldout, num_heldout = poi_and_numeric_through_normalization(heldout, b_heldout_norm)

    # ---- Phase 9 (native-script regression) ----
    native_check = native_script_passthrough_check(main_dataset)
    print(f"\nNative-script pass-through check: {native_check}")

    # ---- System C: normalizer + IndicTrans2 + parser ----
    print(f"\nLoading IndicTrans2 model for System C ...")
    t0 = time.time()
    tokenizer, model, ip = load_model()
    model_load_s = time.time() - t0
    print(f"  model loaded in {model_load_s:.1f}s")

    c_tuning, c_tuning_norm, c_tuning_trans, c_tuning_lat = system_c(code_mixed, tokenizer, model, ip)
    summarize("SYSTEM C (normalizer + IndicTrans2) - tuning set", c_tuning)
    c_heldout, c_heldout_norm, c_heldout_trans, c_heldout_lat = system_c(heldout, tokenizer, model, ip)
    summarize("SYSTEM C (normalizer + IndicTrans2) - HELD-OUT set", c_heldout)

    # ---- language breakdowns (tuning set) ----
    lang_b = language_breakdown(b_tuning["per_query"])
    lang_c = language_breakdown(c_tuning["per_query"])
    cat_b = category_breakdown(b_tuning["per_query"])
    cat_c = category_breakdown(c_tuning["per_query"])

    def strip_pq(ev):
        return {k: v for k, v in ev.items() if k != "per_query"}

    output = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "purpose": "Does a deterministic Romanized/code-mixed normalization layer improve IndicTrans2's code-mixed result (34.3% baseline)?",
        "tuning_set_note": "SYSTEM B and SYSTEM C numbers on 'tuning_set' below are development/tuning results - the normalizer's lexicon was read directly off these 35 queries (see romanized_normalizer.py's module docstring). They are NOT an unbiased estimate. 'held_out_set' (13 queries, new POIs/values/combinations, never inspected while writing the lexicon) is the fair generalization check.",
        "model_load_seconds": model_load_s,

        "system_a_reference": strip_pq(a_tuning),
        "system_b_normalizer_only": {
            "tuning_set": strip_pq(b_tuning),
            "held_out_set": strip_pq(b_heldout),
        },
        "system_c_normalizer_plus_indictrans2": {
            "tuning_set": strip_pq(c_tuning),
            "held_out_set": strip_pq(c_heldout),
            "translation_latency_ms": {
                "tuning_set_avg": sum(c_tuning_lat) / len(c_tuning_lat) if c_tuning_lat else None,
                "held_out_avg": sum(c_heldout_lat) / len(c_heldout_lat) if c_heldout_lat else None,
            },
        },
        "system_d_note": "System D as described in the task (normalizer + parser, no IndicTrans2) is architecturally identical to System B - see system_b_normalizer_only above, not duplicated.",

        "language_breakdown": {"system_b": lang_b, "system_c": lang_c},
        "category_breakdown": {"system_b": cat_b, "system_c": cat_c},

        "poi_preservation_through_normalization_alone": {
            "tuning_set": {"n": len(poi_tuning), "rate": sum(1 for r in poi_tuning if r["fully_preserved"]) / len(poi_tuning) if poi_tuning else None, "details": poi_tuning},
            "held_out_set": {"n": len(poi_heldout), "rate": sum(1 for r in poi_heldout if r["fully_preserved"]) / len(poi_heldout) if poi_heldout else None, "details": poi_heldout},
        },
        "numeric_preservation_through_normalization_alone": {
            "tuning_set": {"n": len(num_tuning), "rate": sum(1 for r in num_tuning if r["fully_preserved"]) / len(num_tuning) if num_tuning else None, "details": num_tuning},
            "held_out_set": {"n": len(num_heldout), "rate": sum(1 for r in num_heldout if r["fully_preserved"]) / len(num_heldout) if num_heldout else None, "details": num_heldout},
        },
        "native_script_regression_check": native_check,

        "per_query_tuning_set": {
            "system_b": b_tuning["per_query"],
            "system_c": c_tuning["per_query"],
            "normalized_text": b_tuning_norm,
            "translated_text_system_c": c_tuning_trans,
        },
        "per_query_held_out_set": {
            "system_b": b_heldout["per_query"],
            "system_c": c_heldout["per_query"],
            "normalized_text": b_heldout_norm,
            "translated_text_system_c": c_heldout_trans,
        },
    }

    OUT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / "romanized_experiment.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nWrote {out_path}")

    print("\n=== HEADLINE COMPARISON (tuning set, code-mixed, n=35) ===")
    print(f"System A (IndicTrans2 baseline):        exact-match={a_tuning['exact_match_accuracy']:.3f}  intent={a_tuning['intent_accuracy']:.3f}  slotF1={a_tuning['slot_f1']:.3f}")
    print(f"System B (normalizer only):              exact-match={b_tuning['exact_match_accuracy']:.3f}  intent={b_tuning['intent_accuracy']:.3f}  slotF1={b_tuning['slot_f1']:.3f}")
    print(f"System C (normalizer + IndicTrans2):      exact-match={c_tuning['exact_match_accuracy']:.3f}  intent={c_tuning['intent_accuracy']:.3f}  slotF1={c_tuning['slot_f1']:.3f}")
    print("\n=== HELD-OUT (n=13) ===")
    print(f"System B (normalizer only):              exact-match={b_heldout['exact_match_accuracy']:.3f}  intent={b_heldout['intent_accuracy']:.3f}  slotF1={b_heldout['slot_f1']:.3f}")
    print(f"System C (normalizer + IndicTrans2):      exact-match={c_heldout['exact_match_accuracy']:.3f}  intent={c_heldout['intent_accuracy']:.3f}  slotF1={c_heldout['slot_f1']:.3f}")


if __name__ == "__main__":
    main()
