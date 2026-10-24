"""
Phase 2.5 ablation study.

Measures how much each pipeline stage actually contributes by running
the SAME evaluator (evaluate_nlp.evaluate) against five configurations:

  baseline_rule_only    - services/nlp/baseline.py, the pre-existing
                           Baseline A (unmodified - see its own
                           docstring for why it must stay a legitimate,
                           un-improved simpler comparator).
  no_normalization       - services/nlp/parser._parse_configured with
                           use_normalization=False: raw_query is only
                           lowercased, none of normalize_query()'s
                           currency/digit-splitting/comma cleanup runs.
  no_location_masking    - use_location_masking=False: location is
                           still extracted and still appears in the
                           output, but its matched span is NOT blanked
                           out of the text before entity/amenity
                           extraction runs - reproduces the
                           "Guindy National Park" -> amenity "park" bug
                           the development set caught during Phase 2.
  no_numeric_parser      - use_numeric=False: extract_price/extract_area
                           are never called; price and area are always
                           None.
  full_hybrid             - parse(), i.e. every stage enabled - the
                           actual production pipeline.

No stage is ever permanently disabled in the production code - all four
"disabled" configs go through the same _parse_configured() entry point
services/nlp/parser.parse() uses, just with different keyword flags.
See services/nlp/parser.py's module docstring.

Run against BOTH the development set and the held-out test set, so the
ablation table itself isn't vulnerable to the same "measured only
against a tuned set" criticism Phase 2.5 exists to address.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from services.nlp.parser import parse, _parse_configured
from services.nlp.baseline import parse_baseline
from evaluation.nlp.evaluate_nlp import evaluate, DEV_DATASET_PATH, TEST_DATASET_PATH, RESULTS_DIR

CONFIGS = {
    "baseline_rule_only": lambda q: parse_baseline(q),
    "no_normalization": lambda q: _parse_configured(q, use_normalization=False),
    "no_location_masking": lambda q: _parse_configured(q, use_location_masking=False),
    "no_numeric_parser": lambda q: _parse_configured(q, use_numeric=False),
    "full_hybrid": lambda q: parse(q),
}

# Print order (spec's own table order, Step 11).
DISPLAY_ORDER = [
    "baseline_rule_only", "no_normalization", "no_location_masking",
    "no_numeric_parser", "full_hybrid",
]

DISPLAY_NAMES = {
    "baseline_rule_only": "Baseline (rule-only, A)",
    "no_normalization": "No normalization",
    "no_location_masking": "No location masking",
    "no_numeric_parser": "No numeric parser",
    "full_hybrid": "Full hybrid",
}


def run_ablation(dataset_path: Path, label: str) -> dict:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    results = {}
    for name, fn in CONFIGS.items():
        res = evaluate(fn, dataset)
        results[name] = {k: v for k, v in res.items() if k != "per_query"}

    print(f"\n{'=' * 90}\nABLATION - {label} (n={len(dataset)})\n{'=' * 90}")
    header = f"{'Configuration':26s} | {'Intent Acc':10s} | {'Slot P':7s} | {'Slot R':7s} | {'Slot F1':7s} | {'Exact Match':11s}"
    print(header)
    print("-" * len(header))
    for key in DISPLAY_ORDER:
        r = results[key]
        print(f"{DISPLAY_NAMES[key]:26s} | {r['intent_accuracy']:10.3f} | {r['slot_precision']:7.3f} | "
              f"{r['slot_recall']:7.3f} | {r['slot_f1']:7.3f} | {r['exact_match_accuracy']:11.3f}")

    return {
        "label": label,
        "dataset_path": str(dataset_path),
        "dataset_size": len(dataset),
        "configs": results,
    }


def markdown_table(ablation_result: dict) -> str:
    lines = [
        "| Configuration | Intent Acc | Slot P | Slot R | Slot F1 | Exact Match |",
        "|---|---|---|---|---|---|",
    ]
    for key in DISPLAY_ORDER:
        r = ablation_result["configs"][key]
        lines.append(
            f"| {DISPLAY_NAMES[key]} | {r['intent_accuracy']:.3f} | {r['slot_precision']:.3f} | "
            f"{r['slot_recall']:.3f} | {r['slot_f1']:.3f} | {r['exact_match_accuracy']:.3f} |"
        )
    return "\n".join(lines)


def main():
    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    dev_result = run_ablation(DEV_DATASET_PATH, "DEVELOPMENT SET")
    test_result = run_ablation(TEST_DATASET_PATH, "HELD-OUT TEST SET")

    dev_result["generated_at_utc"] = timestamp
    test_result["generated_at_utc"] = timestamp

    (RESULTS_DIR / "ablation_development.json").write_text(json.dumps(dev_result, indent=2, ensure_ascii=False), encoding="utf-8")
    (RESULTS_DIR / "ablation_test.json").write_text(json.dumps(test_result, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n\n--- Markdown table (development set) ---\n")
    print(markdown_table(dev_result))
    print("\n\n--- Markdown table (held-out test set) ---\n")
    print(markdown_table(test_result))

    print(f"\n\nSaved {RESULTS_DIR / 'ablation_development.json'}")
    print(f"Saved {RESULTS_DIR / 'ablation_test.json'}")


if __name__ == "__main__":
    main()
