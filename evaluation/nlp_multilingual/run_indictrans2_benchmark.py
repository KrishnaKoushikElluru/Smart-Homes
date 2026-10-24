"""
IndicTrans2 translation-then-parse benchmark runner (WSL/Linux ONLY).

    Indic/code-mixed query
        |
    IndicTrans2 (ai4bharat/indictrans2-indic-en-dist-200M), Indic -> English
        |
    services/nlp/parser.py  (UNMODIFIED - the existing production English parser)
        |
    StructuredQuery
        |
    evaluation, reusing evaluation/nlp/evaluate_nlp.py's slot-comparison
    primitives (slots_from_dict, FIELD_GROUPS, field_of, category_breakdown)
    rather than duplicating that logic.

English-language queries in the dataset are NOT translated - IndicTrans2's
indic-en checkpoint has no English source direction, so they serve as the
untranslated baseline/control the translated-Indic path is compared against.

Run ONLY inside the isolated WSL benchmark venv:
    ~/smarthomes_benchmark/.venv
Never run this against the project's production venv/requirements.txt - it
is not a project dependency and must never become one without a separate,
explicit decision.

Writes:
    evaluation/nlp_multilingual/results/indictrans2_run_<timestamp>.json
        (full per-query detail: every translation + parse + comparison)
This script does NOT overwrite indictrans2_benchmark.json/.md - those are
hand-composed narrative reports; a separate step reads this run file's
numbers and writes them in there deliberately, so no number is silently
auto-formatted into prose.
"""
from __future__ import annotations

import json
import re
import resource
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from services.nlp.parser import parse  # noqa: E402
from evaluation.nlp.evaluate_nlp import (  # noqa: E402
    slots_from_dict, FIELD_GROUPS, field_of, category_breakdown,
    PRICE_TOLERANCE, AREA_TOLERANCE, BHK_TOLERANCE, _num_close,
)

DATA_PATH = REPO_ROOT / "evaluation" / "nlp_multilingual" / "data" / "multilingual_dev_queries.json"
OUT_DIR = REPO_ROOT / "evaluation" / "nlp_multilingual" / "results"

CKPT = "ai4bharat/indictrans2-indic-en-dist-200M"
LANG_TO_FLORES = {
    "ta": "tam_Taml", "ta-en": "tam_Taml",
    "hi": "hin_Deva", "hi-en": "hin_Deva",
    "te": "tel_Telu", "te-en": "tel_Telu",
}
TGT_LANG = "eng_Latn"
BATCH_SIZE = 8

# Terms that must survive translation verbatim (or near-verbatim) for the
# location_poi / nearby_facility categories - proper nouns IndicTrans2 has
# no reason to know, so silent mistranslation here is exactly the failure
# mode this benchmark most needs to catch.
POI_TERMS = ["VIT Chennai", "VIT", "Tata Homes", "Mambakkam", "SRM", "SBIOA",
             "railway station", "hospital", "mall", "metro", "gym", "school", "park"]


def load_model():
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    from IndicTransToolkit.processor import IndicProcessor

    tokenizer = AutoTokenizer.from_pretrained(CKPT, trust_remote_code=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(CKPT, trust_remote_code=True)
    model.eval()
    ip = IndicProcessor(inference=True)
    return tokenizer, model, ip


def translate_batch(sentences, src_lang, tokenizer, model, ip):
    import torch
    batch = ip.preprocess_batch(sentences, src_lang=src_lang, tgt_lang=TGT_LANG)
    inputs = tokenizer(batch, truncation=True, padding="longest",
                        return_tensors="pt", return_attention_mask=True)
    with torch.no_grad():
        # use_cache=False: AI4Bharat's shipped modeling_indictrans.py (custom
        # remote code, pinned internally to transformers==4.32.1) indexes
        # past_key_values as a legacy tuple ("past_key_values[0][0].shape[2]").
        # transformers>=4.4x's generate() now pre-populates an empty
        # DynamicCache object instead of None even on the first decoding
        # step, so that indexing throws AttributeError: 'NoneType' object
        # has no attribute 'shape'. Disabling the cache avoids the
        # incompatible object entirely (verified: translation succeeds with
        # use_cache=False, crashes 100% of the time with use_cache=True on
        # this transformers version) at the cost of slower, uncached
        # decoding - a real, disclosed latency cost of this version
        # mismatch, not hidden by this benchmark.
        generated = model.generate(
            **inputs, use_cache=False, min_length=0, max_length=256,
            num_beams=5, num_return_sequences=1,
        )
    with tokenizer.as_target_tokenizer():
        decoded = tokenizer.batch_decode(
            generated.detach().cpu().tolist(),
            skip_special_tokens=True, clean_up_tokenization_spaces=True,
        )
    return ip.postprocess_batch(decoded, lang=TGT_LANG)


def extract_numbers(text: str) -> set:
    # Digits with optional comma grouping/decimals, e.g. "30,000" "1.5"
    return set(re.findall(r"\d[\d,]*\.?\d*", text or ""))


def check_poi_preserved(original_query: str, translated_text: str) -> dict | None:
    hits = [t for t in POI_TERMS if t.lower() in original_query.lower()]
    if not hits:
        return None
    preserved = [t for t in hits if t.lower() in (translated_text or "").lower()]
    return {"expected_terms": hits, "preserved_terms": preserved,
            "fully_preserved": len(preserved) == len(hits)}


def check_numeric_preserved(original_query: str, translated_text: str) -> dict | None:
    orig_nums = extract_numbers(original_query)
    if not orig_nums:
        return None
    trans_nums = extract_numbers(translated_text)
    # normalize by stripping commas for comparison
    orig_norm = {n.replace(",", "") for n in orig_nums}
    trans_norm = {n.replace(",", "") for n in trans_nums}
    preserved = orig_norm & trans_norm
    return {
        "original_numbers": sorted(orig_nums),
        "translated_numbers": sorted(trans_nums),
        "fully_preserved": orig_norm.issubset(trans_norm) if orig_norm else True,
        "partially_preserved": len(preserved) > 0,
    }


def evaluate_predictions(items_with_predictions: list) -> dict:
    """Mirrors evaluation/nlp/evaluate_nlp.py's evaluate() aggregate loop,
    but takes pre-computed (item, predicted_dict) pairs instead of calling
    a parse_fn(query) itself - because here `query` (original) and what
    gets parsed (translated text) are different strings. Reuses that
    module's slots_from_dict/FIELD_GROUPS/field_of/tolerance constants
    rather than re-deriving slot-comparison logic."""
    intent_correct = 0
    exact_match = 0
    tp = fp = fn = 0
    per_field = {f: {"tp": 0, "fp": 0, "fn": 0} for f in FIELD_GROUPS}
    per_query_results = []

    for item, predicted_dict in items_with_predictions:
        expected = item["expected"]
        pred_intent = predicted_dict["intent"]
        gold_intent = expected.get("intent", "property_search")
        intent_ok = pred_intent == gold_intent
        if intent_ok:
            intent_correct += 1

        pred_slots = slots_from_dict(predicted_dict, is_prediction=True)
        gold_slots = slots_from_dict(expected, is_prediction=False)

        matched_gold = set()
        matched_pred = set()
        for g in gold_slots:
            for p in pred_slots:
                if p in matched_pred:
                    continue
                if g[0] == p[0]:
                    if g[0] in ("bedrooms",):
                        ok = _num_close(g[1], p[1], BHK_TOLERANCE)
                    elif g[0] in ("price_value", "price_min", "price_max"):
                        ok = _num_close(g[1], p[1], PRICE_TOLERANCE)
                    elif g[0] in ("area_value", "area_min", "area_max"):
                        ok = _num_close(g[1], p[1], AREA_TOLERANCE)
                    else:
                        ok = g[1] == p[1]
                    if ok:
                        matched_gold.add(g)
                        matched_pred.add(p)
                        break

        query_tp = len(matched_gold)
        query_fp = len(pred_slots) - len(matched_pred)
        query_fn = len(gold_slots) - len(matched_gold)
        tp += query_tp
        fp += query_fp
        fn += query_fn

        for g in gold_slots:
            field = field_of(g[0])
            per_field[field]["tp" if g in matched_gold else "fn"] += 1
        for p in pred_slots:
            if p not in matched_pred:
                per_field[field_of(p[0])]["fp"] += 1

        query_exact = intent_ok and query_fp == 0 and query_fn == 0
        if query_exact:
            exact_match += 1

        per_query_results.append({
            "id": item["id"], "query": item["query"], "category": item["category"],
            "language": item["language"],
            "intent_correct": intent_ok, "exact_match": query_exact,
            "predicted": predicted_dict, "expected": expected,
            "missed_slots": sorted(str(s) for s in gold_slots - matched_gold),
            "extra_slots": sorted(str(s) for s in pred_slots - matched_pred),
        })

    n = len(items_with_predictions)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    per_field_metrics = {}
    for field, counts in per_field.items():
        p = counts["tp"] / (counts["tp"] + counts["fp"]) if (counts["tp"] + counts["fp"]) else None
        r = counts["tp"] / (counts["tp"] + counts["fn"]) if (counts["tp"] + counts["fn"]) else None
        f = (2 * p * r / (p + r)) if (p is not None and r is not None and (p + r) > 0) else None
        per_field_metrics[field] = {"precision": p, "recall": r, "f1": f,
                                     "support": counts["tp"] + counts["fn"]}

    return {
        "n_queries": n,
        "intent_accuracy": intent_correct / n if n else 0.0,
        "exact_match_accuracy": exact_match / n if n else 0.0,
        "slot_precision": precision, "slot_recall": recall, "slot_f1": f1,
        "per_field": per_field_metrics,
        "per_query": per_query_results,
    }


def language_breakdown(per_query_results: list) -> dict:
    by_lang = defaultdict(lambda: {"n": 0, "exact_match": 0, "intent_correct": 0})
    for r in per_query_results:
        lg = by_lang[r["language"]]
        lg["n"] += 1
        lg["exact_match"] += int(r["exact_match"])
        lg["intent_correct"] += int(r["intent_correct"])
    return {
        lang: {"n": v["n"],
               "exact_match_accuracy": v["exact_match"] / v["n"],
               "intent_accuracy": v["intent_correct"] / v["n"]}
        for lang, v in sorted(by_lang.items())
    }


def main():
    print(f"Loading dataset from {DATA_PATH}")
    dataset = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    print(f"  {len(dataset)} queries loaded")

    print(f"Loading model {CKPT} ...")
    t0 = time.time()
    tokenizer, model, ip = load_model()
    model_load_s = time.time() - t0
    print(f"  model loaded in {model_load_s:.1f}s")

    english_items = [it for it in dataset if it["language"] == "en"]
    indic_items = [it for it in dataset if it["language"] != "en"]

    by_lang_group = defaultdict(list)
    for it in indic_items:
        by_lang_group[LANG_TO_FLORES[it["language"]]].append(it)

    translations = {}  # id -> translated text (or None on failure)
    translation_errors = {}
    translation_latencies_ms = []
    peak_rss_kb_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    bench_start = time.time()
    for flores_lang, items in by_lang_group.items():
        print(f"Translating {len(items)} queries [{flores_lang} -> {TGT_LANG}] ...")
        for i in range(0, len(items), BATCH_SIZE):
            chunk = items[i:i + BATCH_SIZE]
            sentences = [it["query"] for it in chunk]
            t0 = time.time()
            try:
                outputs = translate_batch(sentences, flores_lang, tokenizer, model, ip)
                elapsed_ms = (time.time() - t0) * 1000
                per_item_ms = elapsed_ms / len(chunk)
                for it, out in zip(chunk, outputs):
                    translations[it["id"]] = out
                    translation_latencies_ms.append(per_item_ms)
            except Exception as e:
                elapsed_ms = (time.time() - t0) * 1000
                for it in chunk:
                    translations[it["id"]] = None
                    translation_errors[it["id"]] = f"{type(e).__name__}: {e}"
                    translation_latencies_ms.append(elapsed_ms / len(chunk))

    total_translation_s = time.time() - bench_start
    peak_rss_kb_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    n_translated = len(indic_items)
    n_translation_failed = len(translation_errors)
    translation_success_rate = (n_translated - n_translation_failed) / n_translated if n_translated else None

    # Build (item, predicted_dict) pairs for evaluation.
    items_with_predictions = []
    poi_preservation_results = []
    numeric_preservation_results = []

    for it in english_items:
        predicted_sq = parse(it["query"])
        items_with_predictions.append((it, predicted_sq.to_dict()))

    for it in indic_items:
        translated = translations.get(it["id"])
        text_to_parse = translated if translated else ""
        predicted_sq = parse(text_to_parse)
        items_with_predictions.append((it, predicted_sq.to_dict()))

        poi_check = check_poi_preserved(it["query"], translated or "")
        if poi_check is not None:
            poi_check.update({"id": it["id"], "query": it["query"], "language": it["language"],
                               "translated": translated})
            poi_preservation_results.append(poi_check)

        num_check = check_numeric_preserved(it["query"], translated or "")
        if num_check is not None:
            num_check.update({"id": it["id"], "query": it["query"], "language": it["language"],
                               "translated": translated})
            numeric_preservation_results.append(num_check)

    overall = evaluate_predictions(items_with_predictions)
    cat_breakdown = category_breakdown(overall["per_query"])
    lang_breakdown = language_breakdown(overall["per_query"])

    # code-mixed-only subset
    code_mixed_rows = [r for r in overall["per_query"] if r["language"] in ("ta-en", "hi-en", "te-en")]
    code_mixed_summary = {
        "n": len(code_mixed_rows),
        "exact_match_accuracy": sum(r["exact_match"] for r in code_mixed_rows) / len(code_mixed_rows) if code_mixed_rows else None,
        "intent_accuracy": sum(r["intent_correct"] for r in code_mixed_rows) / len(code_mixed_rows) if code_mixed_rows else None,
    }

    # native-script-only subset (ta, hi, te)
    native_script_rows = [r for r in overall["per_query"] if r["language"] in ("ta", "hi", "te")]
    native_script_summary = {
        "n": len(native_script_rows),
        "exact_match_accuracy": sum(r["exact_match"] for r in native_script_rows) / len(native_script_rows) if native_script_rows else None,
        "intent_accuracy": sum(r["intent_correct"] for r in native_script_rows) / len(native_script_rows) if native_script_rows else None,
    }

    english_rows = [r for r in overall["per_query"] if r["language"] == "en"]
    english_control_summary = {
        "n": len(english_rows),
        "exact_match_accuracy": sum(r["exact_match"] for r in english_rows) / len(english_rows) if english_rows else None,
        "intent_accuracy": sum(r["intent_correct"] for r in english_rows) / len(english_rows) if english_rows else None,
    }

    poi_fully_preserved = sum(1 for r in poi_preservation_results if r["fully_preserved"])
    numeric_fully_preserved = sum(1 for r in numeric_preservation_results if r["fully_preserved"])

    representative_examples = []
    # pick a few representative translation examples spanning languages
    seen_langs = set()
    for it in indic_items:
        if it["language"] in seen_langs:
            continue
        seen_langs.add(it["language"])
        representative_examples.append({
            "id": it["id"], "language": it["language"], "category": it["category"],
            "original": it["query"], "translated": translations.get(it["id"]),
        })

    failures = [r for r in overall["per_query"] if not r["exact_match"] and r["language"] != "en"][:20]

    output = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": CKPT,
        "dataset_path": str(DATA_PATH),
        "dataset_size": len(dataset),
        "model_load_seconds": model_load_s,
        "translation": {
            "n_queries_requiring_translation": n_translated,
            "n_translation_failures": n_translation_failed,
            "translation_success_rate": translation_success_rate,
            "translation_errors": translation_errors,
            "total_translation_wall_seconds": total_translation_s,
            "avg_latency_ms_per_query": sum(translation_latencies_ms) / len(translation_latencies_ms) if translation_latencies_ms else None,
            "max_latency_ms_per_query": max(translation_latencies_ms) if translation_latencies_ms else None,
            "min_latency_ms_per_query": min(translation_latencies_ms) if translation_latencies_ms else None,
            "peak_rss_kb_before": peak_rss_kb_before,
            "peak_rss_kb_after": peak_rss_kb_after,
        },
        "overall": {k: v for k, v in overall.items() if k != "per_query"},
        "english_control": english_control_summary,
        "native_script_indic": native_script_summary,
        "code_mixed": code_mixed_summary,
        "category_breakdown": cat_breakdown,
        "language_breakdown": lang_breakdown,
        "poi_preservation": {
            "n_poi_queries": len(poi_preservation_results),
            "n_fully_preserved": poi_fully_preserved,
            "rate": poi_fully_preserved / len(poi_preservation_results) if poi_preservation_results else None,
            "details": poi_preservation_results,
        },
        "numeric_preservation": {
            "n_numeric_queries": len(numeric_preservation_results),
            "n_fully_preserved": numeric_fully_preserved,
            "rate": numeric_fully_preserved / len(numeric_preservation_results) if numeric_preservation_results else None,
            "details": numeric_preservation_results,
        },
        "representative_translation_examples": representative_examples,
        "failures_sample": failures,
        "per_query": overall["per_query"],
    }

    OUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = OUT_DIR / f"indictrans2_run_{ts}.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nWrote {out_path}")

    print("\n=== SUMMARY ===")
    print(f"Translation success rate: {translation_success_rate}")
    print(f"Overall exact-match accuracy: {overall['exact_match_accuracy']:.3f}")
    print(f"Overall intent accuracy: {overall['intent_accuracy']:.3f}")
    print(f"Overall slot F1: {overall['slot_f1']:.3f}")
    print(f"English control exact-match: {english_control_summary['exact_match_accuracy']}")
    print(f"Native-script Indic exact-match: {native_script_summary['exact_match_accuracy']}")
    print(f"Code-mixed exact-match: {code_mixed_summary['exact_match_accuracy']}")
    print(f"POI preservation rate: {output['poi_preservation']['rate']}")
    print(f"Numeric preservation rate: {output['numeric_preservation']['rate']}")


if __name__ == "__main__":
    main()
