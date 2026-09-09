"""
Phase 2.5 error analysis.

Reads the most recent held-out test run (evaluation/nlp/results/test_run_*.json,
written by evaluate_nlp.py) and produces a categorized, machine-readable
breakdown of every query where the proposed (hybrid) parser did NOT
reach an exact match - not just the one aggregate exact-match number.
Every failure is kept and classified, never silently dropped (Phase
2.5's Step 16: "if the test reveals failures, KEEP THEM").

Classification buckets (a failure can appear in more than one, if e.g.
it both missed a field and added a spurious one):
  - missed_field: a gold slot the parser did not produce (false negative)
  - extra_field:  a slot the parser produced that isn't in gold (false positive)
  - typo:         the query is tagged category=="typo" in the dataset -
                   a documented, deliberate, un-fixed capability gap
  - other:        anything not covered above

Writes evaluation/nlp/results/test_error_analysis.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"


def latest_test_run() -> Path:
    runs = sorted(RESULTS_DIR.glob("test_run_*.json"))
    if not runs:
        raise SystemExit("No test_run_*.json found - run evaluate_nlp.py first.")
    return runs[-1]


def field_of_slot_repr(slot_repr: str) -> str:
    """slot_repr looks like "('price_value', 25000.0)" (str() of a tuple).
    Map the inner key back to a reportable field name."""
    key = slot_repr.split(",", 1)[0].strip("(' ")
    if key.startswith("price"):
        return "price"
    if key.startswith("area"):
        return "area"
    if key == "bedrooms":
        return "bedrooms"
    if key == "amenity":
        return "amenities"
    if key.startswith("location"):
        return "location"
    if key in ("listing_type", "property_type", "furnishing"):
        return key
    return "other"


def main():
    run_path = latest_test_run()
    data = json.loads(run_path.read_text(encoding="utf-8"))
    per_query = data["proposed_per_query"]

    failures = [r for r in per_query if not r["exact_match"]]

    categorized = []
    field_failure_counts = {}
    for r in failures:
        missed_fields = sorted({field_of_slot_repr(s) for s in r["missed_slots"]})
        extra_fields = sorted({field_of_slot_repr(s) for s in r["extra_slots"]})
        is_typo = r["category"] == "typo"

        for f in missed_fields + extra_fields:
            field_failure_counts[f] = field_failure_counts.get(f, 0) + 1

        categorized.append({
            "id": r["id"],
            "query": r["query"],
            "dataset_category": r["category"],
            "intent_correct": r["intent_correct"],
            "missed_slots": r["missed_slots"],
            "extra_slots": r["extra_slots"],
            "missed_fields": missed_fields,
            "extra_fields": extra_fields,
            "classification": "typo (documented, uncorrected)" if is_typo else "genuine_parser_gap",
        })

    output = {
        "source_run": str(run_path),
        "n_total_queries": len(per_query),
        "n_failures": len(failures),
        "n_typo_failures": sum(1 for c in categorized if c["classification"].startswith("typo")),
        "n_genuine_parser_gap_failures": sum(1 for c in categorized if c["classification"] == "genuine_parser_gap"),
        "field_failure_counts": field_failure_counts,
        "failures": categorized,
    }

    out_path = RESULTS_DIR / "test_error_analysis.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Read {run_path}")
    print(f"{output['n_failures']} / {output['n_total_queries']} queries did not reach exact match "
          f"({output['n_failures'] / output['n_total_queries']:.1%})")
    print(f"  typo-attributable (documented, uncorrected): {output['n_typo_failures']}")
    print(f"  genuine parser gaps:                         {output['n_genuine_parser_gap_failures']}")
    print("Field failure counts:", field_failure_counts)
    for c in categorized:
        print(f"  [{c['classification']}] id={c['id']} category={c['dataset_category']!r} query={c['query']!r}")
        if c["missed_fields"]:
            print(f"      missed: {c['missed_fields']}")
        if c["extra_fields"]:
            print(f"      extra:  {c['extra_fields']}")
    print(f"\nSaved {out_path}")


if __name__ == "__main__":
    main()
