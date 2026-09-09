"""
Phase 2.5 bootstrap confidence intervals.

The held-out test set (n=132) is still small by NLU-research standards,
so a single point estimate ("97.0% exact match") invites overclaiming
precision it doesn't have. This script computes a 95% confidence
interval for the three headline metrics - intent accuracy, slot F1,
exact-match accuracy - via the standard nonparametric bootstrap:

  1. Draw a resample of size n (= the test set size) BY SAMPLING QUERIES
     WITH REPLACEMENT from the held-out test set (query-level resampling,
     not slot-level - this is what a real distribution of "a different
     132 queries drawn from the same population" would look like).
  2. Re-run the actual evaluator (evaluate_nlp.evaluate) on that
     resampled query list, recording intent_accuracy, slot_f1, and
     exact_match_accuracy.
  3. Repeat N_RESAMPLES times, then report the [2.5th, 97.5th] percentile
     of each metric's distribution as the 95% CI.

Method: percentile bootstrap. Resamples: 2000. Random seed: 20260909
(fixed for reproducibility - re-running this script produces identical
output). Uses Python's stdlib `random` module only - no new dependency.

Run ONLY against the held-out test set's PROPOSED (hybrid) results - the
baseline's score is low enough (exact match 0.038) that a CI adds little
interpretive value there, and the held-out proposed number is the one
figure this report is making a claim about.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from services.nlp.parser import parse
from evaluation.nlp.evaluate_nlp import evaluate, TEST_DATASET_PATH, RESULTS_DIR

N_RESAMPLES = 2000
SEED = 20260909


def percentile(sorted_values: list, pct: float) -> float:
    """Linear-interpolation percentile, stdlib-only (no numpy)."""
    if not sorted_values:
        return float("nan")
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def bootstrap_ci(dataset: list, parse_fn, n_resamples: int, seed: int) -> dict:
    rng = random.Random(seed)
    n = len(dataset)

    point = evaluate(parse_fn, dataset)
    point_metrics = {
        "intent_accuracy": point["intent_accuracy"],
        "slot_f1": point["slot_f1"],
        "exact_match_accuracy": point["exact_match_accuracy"],
    }

    samples = {"intent_accuracy": [], "slot_f1": [], "exact_match_accuracy": []}
    for _ in range(n_resamples):
        resample = [rng.choice(dataset) for _ in range(n)]
        res = evaluate(parse_fn, resample)
        samples["intent_accuracy"].append(res["intent_accuracy"])
        samples["slot_f1"].append(res["slot_f1"])
        samples["exact_match_accuracy"].append(res["exact_match_accuracy"])

    ci = {}
    for metric, values in samples.items():
        values_sorted = sorted(values)
        ci[metric] = {
            "point_estimate": point_metrics[metric],
            "ci_lower_2.5": percentile(values_sorted, 2.5),
            "ci_upper_97.5": percentile(values_sorted, 97.5),
            "bootstrap_mean": sum(values) / len(values),
        }
    return ci


def main():
    dataset = json.loads(TEST_DATASET_PATH.read_text(encoding="utf-8"))
    print(f"Bootstrapping {N_RESAMPLES} resamples (seed={SEED}) over {len(dataset)} held-out test queries...")

    ci = bootstrap_ci(dataset, parse, N_RESAMPLES, SEED)

    print(f"\n{'Metric':22s} | {'Point':7s} | {'95% CI':17s} | {'Bootstrap mean':14s}")
    print("-" * 68)
    for metric, m in ci.items():
        ci_str = f"[{m['ci_lower_2.5']:.3f}, {m['ci_upper_97.5']:.3f}]"
        print(f"{metric:22s} | {m['point_estimate']:.3f}   | {ci_str:17s} | {m['bootstrap_mean']:.3f}")

    output = {
        "method": "nonparametric percentile bootstrap, query-level resampling",
        "n_resamples": N_RESAMPLES,
        "random_seed": SEED,
        "dataset": "held-out test set",
        "dataset_path": str(TEST_DATASET_PATH),
        "dataset_size": len(dataset),
        "metrics": ci,
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / "bootstrap_ci_test.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {out_path}")


if __name__ == "__main__":
    main()
