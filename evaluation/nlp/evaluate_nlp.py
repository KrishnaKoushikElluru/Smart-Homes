"""
Phase 2 NLP evaluator.

Runs BOTH the baseline (services/nlp/baseline.py) and the proposed
hybrid parser (services/nlp/parser.py) against evaluation/nlp/queries.json
and reports, for each:

  - Intent accuracy
  - Slot precision / recall / F1 (micro-averaged over every extracted
    field instance, not just per-query)
  - Query-level exact match accuracy
  - Per-field F1 (listing_type, property_type, bedrooms, price, area,
    amenities, location, furnishing)

Writes a machine-readable results file to
evaluation/nlp/results/latest.json (also timestamped, so a run never
silently overwrites the history of a prior run's numbers).

This script produces REAL numbers by actually running the parsers - it
does not fabricate or hand-edit results. Every number in
docs/PHASE_2_NLP_REPORT.md is copied from a results/*.json file this
script wrote.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from services.nlp.parser import parse
from services.nlp.baseline import parse_baseline

DATASET_PATH = Path(__file__).resolve().parent / "queries.json"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

PRICE_TOLERANCE = 1.0    # rupees
AREA_TOLERANCE = 0.5     # sqft
BHK_TOLERANCE = 0.01


# ============================================================
# SLOT EXTRACTION: turn a StructuredQuery dict (or an `expected` block)
# into a set of (field_name, value) tuples for P/R/F1 comparison.
# ============================================================

def _num_close(a, b, tol):
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def slots_from_dict(d: dict, is_prediction: bool) -> set:
    """d is either a full StructuredQuery.to_dict() (is_prediction=True)
    or a hand-written `expected` block (is_prediction=False, so missing
    keys just mean "not asserted", not "must be None")."""

    slots = set()

    def get_value(key, sub="value"):
        v = d.get(key)
        if v is None:
            return None
        if isinstance(v, dict):
            return v.get(sub)
        return v

    for field in ("listing_type", "property_type", "furnishing"):
        v = get_value(field)
        if v is not None:
            slots.add((field, v))

    bhk = get_value("bedrooms")
    if bhk is not None:
        # Round to 2dp so float noise never creates a spurious mismatch
        # in the SET itself (actual tolerance-based comparison happens
        # in compare_slots below; this is just for hashability).
        slots.add(("bedrooms", round(float(bhk), 2)))

    price = d.get("price")
    if price:
        if price.get("operator") == "between":
            slots.add(("price_operator", "between"))
            slots.add(("price_min", round(float(price["value_min"]), 2)))
            slots.add(("price_max", round(float(price["value_max"]), 2)))
        elif price.get("value") is not None:
            slots.add(("price_operator", price["operator"]))
            slots.add(("price_value", round(float(price["value"]), 2)))

    area = d.get("area")
    if area:
        if area.get("operator") == "between":
            slots.add(("area_operator", "between"))
            slots.add(("area_min", round(float(area["value_min"]), 2)))
            slots.add(("area_max", round(float(area["value_max"]), 2)))
        elif area.get("value") is not None:
            slots.add(("area_operator", area["operator"]))
            slots.add(("area_value", round(float(area["value"]), 2)))

    amenities = d.get("amenities")
    if amenities:
        for a in amenities:
            value = a["value"] if isinstance(a, dict) else a
            slots.add(("amenity", value))

    location = d.get("location")
    if location:
        if location.get("type"):
            slots.add(("location_type", location["type"]))
        if location.get("query"):
            slots.add(("location_query", location["query"].strip().lower()))

    return slots


FIELD_GROUPS = {
    "listing_type": {"listing_type"},
    "property_type": {"property_type"},
    "bedrooms": {"bedrooms"},
    "furnishing": {"furnishing"},
    "price": {"price_operator", "price_value", "price_min", "price_max"},
    "area": {"area_operator", "area_value", "area_min", "area_max"},
    "amenities": {"amenity"},
    "location": {"location_type", "location_query"},
}


def field_of(slot_key: str) -> str:
    for field, keys in FIELD_GROUPS.items():
        if slot_key in keys:
            return field
    return "other"


# ============================================================
# EVALUATION
# ============================================================

def evaluate(parse_fn, dataset: list) -> dict:
    intent_correct = 0
    exact_match = 0

    tp = fp = fn = 0
    per_field = {f: {"tp": 0, "fp": 0, "fn": 0} for f in FIELD_GROUPS}

    per_query_results = []

    for item in dataset:
        query = item["query"]
        expected = item["expected"]

        predicted_sq = parse_fn(query)
        predicted_dict = predicted_sq.to_dict()

        pred_intent = predicted_dict["intent"]
        gold_intent = expected.get("intent", "property_search")
        intent_ok = pred_intent == gold_intent
        if intent_ok:
            intent_correct += 1

        pred_slots = slots_from_dict(predicted_dict, is_prediction=True)
        gold_slots = slots_from_dict(expected, is_prediction=False)

        # Tolerance-aware matching for numeric slot keys: build a
        # matched set rather than relying on exact tuple equality for
        # every numeric field.
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
            if g in matched_gold:
                per_field[field]["tp"] += 1
            else:
                per_field[field]["fn"] += 1
        for p in pred_slots:
            if p not in matched_pred:
                per_field[field_of(p[0])]["fp"] += 1

        query_exact = intent_ok and query_fp == 0 and query_fn == 0
        if query_exact:
            exact_match += 1

        per_query_results.append({
            "id": item["id"], "query": query, "category": item["category"],
            "intent_correct": intent_ok, "exact_match": query_exact,
            "predicted": predicted_dict, "expected": expected,
            "missed_slots": sorted(str(s) for s in gold_slots - matched_gold),
            "extra_slots": sorted(str(s) for s in pred_slots - matched_pred),
        })

    n = len(dataset)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    per_field_metrics = {}
    for field, counts in per_field.items():
        p = counts["tp"] / (counts["tp"] + counts["fp"]) if (counts["tp"] + counts["fp"]) else None
        r = counts["tp"] / (counts["tp"] + counts["fn"]) if (counts["tp"] + counts["fn"]) else None
        f = (2 * p * r / (p + r)) if (p is not None and r is not None and (p + r) > 0) else None
        per_field_metrics[field] = {
            "precision": p, "recall": r, "f1": f,
            "support": counts["tp"] + counts["fn"],
        }

    return {
        "n_queries": n,
        "intent_accuracy": intent_correct / n if n else 0.0,
        "exact_match_accuracy": exact_match / n if n else 0.0,
        "slot_precision": precision,
        "slot_recall": recall,
        "slot_f1": f1,
        "per_field": per_field_metrics,
        "per_query": per_query_results,
    }


def category_breakdown(per_query_results: list) -> dict:
    by_cat = defaultdict(lambda: {"n": 0, "exact_match": 0, "intent_correct": 0})
    for r in per_query_results:
        c = by_cat[r["category"]]
        c["n"] += 1
        c["exact_match"] += int(r["exact_match"])
        c["intent_correct"] += int(r["intent_correct"])
    return {
        cat: {
            "n": v["n"],
            "exact_match_accuracy": v["exact_match"] / v["n"],
            "intent_accuracy": v["intent_correct"] / v["n"],
        }
        for cat, v in sorted(by_cat.items())
    }


def main():
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(dataset)} queries from {DATASET_PATH}")

    baseline_results = evaluate(parse_baseline, dataset)
    proposed_results = evaluate(parse, dataset)

    def summary(name, res):
        print(f"\n=== {name} ===")
        print(f"  Intent accuracy:       {res['intent_accuracy']:.3f}")
        print(f"  Exact match accuracy:  {res['exact_match_accuracy']:.3f}")
        print(f"  Slot precision:        {res['slot_precision']:.3f}")
        print(f"  Slot recall:           {res['slot_recall']:.3f}")
        print(f"  Slot F1:               {res['slot_f1']:.3f}")
        print("  Per-field F1:")
        for field, m in res["per_field"].items():
            f1 = f"{m['f1']:.3f}" if m["f1"] is not None else "N/A"
            print(f"    {field:15s} F1={f1:>6s}  support={m['support']}")

    summary("BASELINE (keyword/rule, no unit conversion, no operators)", baseline_results)
    summary("PROPOSED (hybrid pipeline)", proposed_results)

    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    output = {
        "generated_at_utc": timestamp,
        "dataset_path": str(DATASET_PATH),
        "dataset_size": len(dataset),
        "baseline": {k: v for k, v in baseline_results.items() if k != "per_query"},
        "proposed": {k: v for k, v in proposed_results.items() if k != "per_query"},
        "proposed_category_breakdown": category_breakdown(proposed_results["per_query"]),
        "baseline_category_breakdown": category_breakdown(baseline_results["per_query"]),
    }

    detailed_output = dict(output)
    detailed_output["baseline_per_query"] = baseline_results["per_query"]
    detailed_output["proposed_per_query"] = proposed_results["per_query"]

    (RESULTS_DIR / "latest.json").write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    (RESULTS_DIR / f"run_{timestamp}.json").write_text(json.dumps(detailed_output, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print(f"\nSaved summary to {RESULTS_DIR / 'latest.json'}")
    print(f"Saved detailed per-query results to {RESULTS_DIR / f'run_{timestamp}.json'}")


if __name__ == "__main__":
    main()
