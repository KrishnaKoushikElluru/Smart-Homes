"""
EXPERIMENT-ONLY. Phase 5.7 validation runner.

Evaluates the FROZEN Phase 5.6 normalizer (evaluation/nlp_multilingual/
romanized_normalizer.py - NOT modified in this phase, checksum recorded
in docs/PHASE_5_7_ROMANIZED_VALIDATION.md) against a FROZEN, genuinely
new 100-query validation set (evaluation/nlp_multilingual/data/
romanized_validation_v1.json - also not modified in this phase, its own
checksum likewise recorded) that was never used to design or debug any
normalization rule.

Three systems (same architecture as Phase 5.6's run_romanized_experiment.py,
reused rather than re-derived):
    SYSTEM A: query -> IndicTrans2 (raw, no normalizer) -> parser
    SYSTEM B: query -> normalizer -> parser (no translation)
    SYSTEM C: query -> normalizer -> IndicTrans2 -> parser

PER PHASE 5.7'S OWN RULE: no rule or gold-label change is made after
seeing these results, no matter what this run finds. A genuine bug found
here is recorded as a failure and written up as a Phase 5.8 candidate in
the report - never silently fixed and re-run.

Writes: evaluation/nlp_multilingual/results/romanized_validation_v1_results.json
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
DATA_PATH = HERE / "data" / "romanized_validation_v1.json"
OUT_DIR = HERE / "results"
BATCH = 8
N_RESAMPLES = 2000
SEED = 20260911  # fixed for reproducibility, same percentile-bootstrap method as evaluation/nlp/bootstrap_ci.py

# This dataset's POI set includes 6 names never used in Phase 5.6 -
# extend the reused POI_TERMS list (imported, not modified) for this
# run's own POI-preservation check only.
VALIDATION_POI_TERMS = POI_TERMS + [
    "Prestige Towers", "Loyola College", "Anna University",
    "Apollo Hospital", "Hiranandani Gardens",
]


def check_poi_preserved_v2(original_query: str, transformed_text: str):
    hits = [t for t in VALIDATION_POI_TERMS if t.lower() in original_query.lower()]
    if not hits:
        return None
    preserved = [t for t in hits if t.lower() in (transformed_text or "").lower()]
    return {"expected_terms": hits, "preserved_terms": preserved,
            "fully_preserved": len(preserved) == len(hits)}


def translate_raw(items, tokenizer, model, ip, text_fn):
    """text_fn(item) -> the string to translate for this item (raw query
    for System A, normalized text for System C)."""
    translations, latencies_ms = {}, []
    by_flores = defaultdict(list)
    for it in items:
        by_flores[LANG_TO_FLORES[it["language"]]].append(it)

    for flores_lang, group in by_flores.items():
        for i in range(0, len(group), BATCH):
            chunk = group[i:i + BATCH]
            sentences = [text_fn(it) for it in chunk]
            t0 = time.time()
            try:
                outputs = translate_batch(sentences, flores_lang, tokenizer, model, ip)
                per_item_ms = (time.time() - t0) * 1000 / len(chunk)
                for it, out in zip(chunk, outputs):
                    translations[it["id"]] = out
                    latencies_ms.append(per_item_ms)
            except Exception:
                for it in chunk:
                    translations[it["id"]] = None
                    latencies_ms.append((time.time() - t0) * 1000 / len(chunk))
    return translations, latencies_ms


def bootstrap_ci_from_pairs(pairs: list, n_resamples: int, seed: int) -> dict:
    """Percentile bootstrap over PRECOMPUTED (item, predicted_dict) pairs -
    same method as evaluation/nlp/bootstrap_ci.py (query-level resampling
    with replacement, 2.5/97.5 percentile CI) but resampling already-
    computed predictions instead of re-running parse()/translation on
    every one of the 2000 resamples (which would be prohibitively slow
    for the translation-involving systems)."""
    import random
    rng = random.Random(seed)
    n = len(pairs)
    point = evaluate_predictions(pairs)
    samples = {"intent_accuracy": [], "slot_f1": [], "exact_match_accuracy": []}
    for _ in range(n_resamples):
        resample = [rng.choice(pairs) for _ in range(n)]
        res = evaluate_predictions(resample)
        samples["intent_accuracy"].append(res["intent_accuracy"])
        samples["slot_f1"].append(res["slot_f1"])
        samples["exact_match_accuracy"].append(res["exact_match_accuracy"])

    def pct(values, p):
        values = sorted(values)
        k = (len(values) - 1) * (p / 100.0)
        f, c = int(k), min(int(k) + 1, len(values) - 1)
        if f == c:
            return values[f]
        return values[f] + (values[c] - values[f]) * (k - f)

    return {
        metric: {
            "point_estimate": point[metric],
            "ci_lower_2.5": pct(vals, 2.5),
            "ci_upper_97.5": pct(vals, 97.5),
            "bootstrap_mean": sum(vals) / len(vals),
        }
        for metric, vals in samples.items()
    }


def summarize(label, ev):
    print(f"=== {label} ===  n={ev['n_queries']}  exact_match={ev['exact_match_accuracy']:.3f}  "
          f"intent_acc={ev['intent_accuracy']:.3f}  slot_F1={ev['slot_f1']:.3f}")


def main():
    dataset = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(dataset)} FROZEN validation queries from {DATA_PATH}")

    print("Loading IndicTrans2 model ...")
    t0 = time.time()
    tokenizer, model, ip = load_model()
    model_load_s = time.time() - t0
    print(f"  model loaded in {model_load_s:.1f}s")

    # ---- System A: raw query -> IndicTrans2 -> parser ----
    trans_a, lat_a = translate_raw(dataset, tokenizer, model, ip, text_fn=lambda it: it["query"])
    pairs_a = []
    for it in dataset:
        text = trans_a.get(it["id"]) or ""
        pairs_a.append((it, parse(text).to_dict()))
    ev_a = evaluate_predictions(pairs_a)
    summarize("SYSTEM A (raw IndicTrans2)", ev_a)

    # ---- System B: normalizer -> parser (no translation) ----
    t0 = time.time()
    norm_text = {it["id"]: normalize(it["query"]) for it in dataset}
    norm_latency_total_s = time.time() - t0
    pairs_b = [(it, parse(norm_text[it["id"]]).to_dict()) for it in dataset]
    ev_b = evaluate_predictions(pairs_b)
    summarize("SYSTEM B (frozen normalizer only)", ev_b)

    # ---- System C: normalizer -> IndicTrans2 -> parser ----
    trans_c, lat_c = translate_raw(dataset, tokenizer, model, ip, text_fn=lambda it: norm_text[it["id"]])
    pairs_c = []
    for it in dataset:
        text = trans_c.get(it["id"]) or ""
        pairs_c.append((it, parse(text).to_dict()))
    ev_c = evaluate_predictions(pairs_c)
    summarize("SYSTEM C (normalizer + IndicTrans2)", ev_c)

    # ---- breakdowns ----
    lang_a, lang_b, lang_c = (language_breakdown(e["per_query"]) for e in (ev_a, ev_b, ev_c))
    cat_a, cat_b, cat_c = (category_breakdown(e["per_query"]) for e in (ev_a, ev_b, ev_c))

    # ---- POI / numeric preservation: normalization alone (System B path) ----
    poi_results, num_results = [], []
    for it in dataset:
        norm = norm_text[it["id"]]
        poi = check_poi_preserved_v2(it["query"], norm)
        if poi is not None:
            poi.update({"id": it["id"], "query": it["query"], "normalized": norm})
            poi_results.append(poi)
        num = check_numeric_preserved(it["query"], norm)
        if num is not None:
            num.update({"id": it["id"], "query": it["query"], "normalized": norm})
            num_results.append(num)

    # ---- bootstrap CI (System B - the primary system) ----
    print("\nBootstrapping 95% CI (System B, 2000 resamples) ...")
    ci_b = bootstrap_ci_from_pairs(pairs_b, N_RESAMPLES, SEED)
    for metric, m in ci_b.items():
        print(f"  {metric:22s}  point={m['point_estimate']:.3f}  "
              f"95% CI=[{m['ci_lower_2.5']:.3f}, {m['ci_upper_97.5']:.3f}]")

    def strip_pq(ev):
        return {k: v for k, v in ev.items() if k != "per_query"}

    output = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset_path": str(DATA_PATH),
        "dataset_size": len(dataset),
        "model_load_seconds": model_load_s,
        "system_a_raw_indictrans2": strip_pq(ev_a),
        "system_b_frozen_normalizer": strip_pq(ev_b),
        "system_c_normalizer_plus_indictrans2": strip_pq(ev_c),
        "language_breakdown": {"system_a": lang_a, "system_b": lang_b, "system_c": lang_c},
        "category_breakdown": {"system_a": cat_a, "system_b": cat_b, "system_c": cat_c},
        "poi_preservation_through_normalization": {
            "n": len(poi_results),
            "rate": sum(1 for r in poi_results if r["fully_preserved"]) / len(poi_results) if poi_results else None,
            "details": poi_results,
        },
        "numeric_preservation_through_normalization": {
            "n": len(num_results),
            "rate": sum(1 for r in num_results if r["fully_preserved"]) / len(num_results) if num_results else None,
            "details": num_results,
        },
        "bootstrap_ci_system_b": {
            "method": "nonparametric percentile bootstrap, query-level resampling of precomputed predictions",
            "n_resamples": N_RESAMPLES,
            "random_seed": SEED,
            "metrics": ci_b,
        },
        "latency": {
            "system_a_avg_translation_ms": sum(lat_a) / len(lat_a) if lat_a else None,
            "system_b_total_normalization_seconds": norm_latency_total_s,
            "system_b_avg_normalization_ms_per_query": (norm_latency_total_s * 1000) / len(dataset),
            "system_c_avg_translation_ms": sum(lat_c) / len(lat_c) if lat_c else None,
        },
        "per_query": {
            "system_a": ev_a["per_query"],
            "system_b": ev_b["per_query"],
            "system_c": ev_c["per_query"],
            "normalized_text": norm_text,
            "translated_text_system_a": trans_a,
            "translated_text_system_c": trans_c,
        },
    }

    OUT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / "romanized_validation_v1_results.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nWrote {out_path}")

    print("\n=== HEADLINE (n=100) ===")
    print(f"System A (raw IndicTrans2):              exact-match={ev_a['exact_match_accuracy']:.3f}  intent={ev_a['intent_accuracy']:.3f}  slotF1={ev_a['slot_f1']:.3f}")
    print(f"System B (frozen normalizer only):        exact-match={ev_b['exact_match_accuracy']:.3f}  intent={ev_b['intent_accuracy']:.3f}  slotF1={ev_b['slot_f1']:.3f}")
    print(f"System C (normalizer + IndicTrans2):      exact-match={ev_c['exact_match_accuracy']:.3f}  intent={ev_c['intent_accuracy']:.3f}  slotF1={ev_c['slot_f1']:.3f}")


if __name__ == "__main__":
    main()
