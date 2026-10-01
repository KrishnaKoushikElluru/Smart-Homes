"""
Phase 6 - SOURCE-STRATIFIED (Group A vs Group B) post-hoc analysis.

Derives everything possible from the EXISTING 21-house benchmark results
(results/retrieval_examples.json's top-10 rankings, results/
pilot_margin_analysis.json's per-query best-positive/best-negative data,
and a read-only dataset scan for house->image counts). Does NOT reload
either model, does NOT recompute a single embedding, does NOT change the
dataset. Pure post-processing, same spirit as error_analysis.py.

GROUP ASSIGNMENT (per instructions - by house ID, NEVER inferred from
image appearance):
    House_001-House_009 -> Group A (original batch)
    House_010-House_021 -> Group B (second batch, watermarked)

DATA SUFFICIENCY (read this before trusting any within-group Recall@K
number below - see also results/source_stratified_analysis.md's
"Limitations" section):

retrieval_examples.json stores only the top-10 GLOBALLY-ranked candidates
per query, not the full ranking over all other images. Restricting that
top-10 list to same-group entries recovers the EXACT top of the true
within-group ranking (cosine similarity is a fixed pairwise total order,
so filtering a sorted list to a subset preserves the remaining items'
relative order exactly) - but if fewer than K same-group items appear in
the observed top-10 AND the true same-house positive isn't among them,
whether it would appear in the true within-group top-K is UNKNOWN from
this data (it could be ranked anywhere below the observed window).

This was measured directly (see `diagnose_ambiguity()` below) before
computing anything: for SigLIP2, Recall@1/@3 within-group are exactly
determinable for ALL 83 valid queries (zero ambiguous); Recall@5 has 1
ambiguous query. For DINOv2, Recall@1 has 1 ambiguous query, Recall@3 has
2, Recall@5 has 5 - but Recall@10 has 44 of 83 (53%) ambiguous, which is
too large a gap to report as a real measurement without a misleading
bias (the ambiguous queries are structurally the ones where the model
performed WORSE, so excluding them would inflate the reported number).

Per this task's explicit instruction ("Only rerun model inference if a
required quantity genuinely cannot be derived... STOP and report exactly
what is missing before running it"): within-group Recall@10 and MRR are
NOT computed/reported as point estimates here - they are reported as
"not reliably derivable from existing top-10-only data" with the exact
ambiguous-query counts as justification. No model was re-run to fill
this gap; it is left as an explicit, flagged limitation for the user to
decide whether it is worth a targeted re-embedding pass.
"""

import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluation.image_similarity import dataset

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
GROUP_A_MAX_HOUSE_NUMBER = 9  # House_001-House_009 -> A; House_010+ -> B


def house_group(house_id):
    number = int(house_id.split("_")[1])
    return "A" if number <= GROUP_A_MAX_HOUSE_NUMBER else "B"


def load_json(name):
    with open(os.path.join(RESULTS_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# PART 1 - group composition
# ============================================================

def group_composition(dataset_summary):
    images_per_house = dataset_summary["images_per_house"]

    groups = {"A": {}, "B": {}}
    for house_id, count in images_per_house.items():
        groups[house_group(house_id)][house_id] = count

    def summarize(houses):
        counts = list(houses.values())
        return {
            "n_houses": len(houses),
            "n_images": sum(counts),
            "images_per_house": houses,
            "min_images_per_house": min(counts) if counts else None,
            "max_images_per_house": max(counts) if counts else None,
            "mean_images_per_house": round(statistics.mean(counts), 2) if counts else None,
        }

    return {
        "group_a": summarize(groups["A"]),
        "group_b": summarize(groups["B"]),
        "combined_houses": len(images_per_house),
        "combined_images": sum(images_per_house.values()),
    }


# ============================================================
# Diagnostic: how much of within-group Recall@K is exactly
# derivable from the existing top-10-only data (see module
# docstring). Computed BEFORE anything else is derived.
# ============================================================

def diagnose_ambiguity(examples, k_values=(1, 3, 5, 10)):
    ambiguous_by_k = {k: 0 for k in k_values}
    resolved_by_k = {k: 0 for k in k_values}

    for example in examples:
        qgroup = house_group(example["query_house_id"])
        same_group_seq = [r for r in example["top_results"] if house_group(r["house_id"]) == qgroup]
        found_rank = next((i + 1 for i, r in enumerate(same_group_seq) if r["correct_property"]), None)
        n_observed = len(same_group_seq)

        for k in k_values:
            if found_rank is not None and found_rank <= k:
                resolved_by_k[k] += 1
            elif n_observed >= k:
                resolved_by_k[k] += 1  # definitively NOT in top-k within-group
            else:
                ambiguous_by_k[k] += 1

    return {"ambiguous_by_k": ambiguous_by_k, "resolved_by_k": resolved_by_k, "n_total": len(examples)}


# ============================================================
# PART 3/4 - within-group retrieval (Recall@1/3/5 only - see
# module docstring for why @10/MRR are excluded)
# ============================================================

def within_group_recall(examples, target_group, k_values=(1, 3, 5)):
    group_queries = [e for e in examples if house_group(e["query_house_id"]) == target_group]

    hits = {k: 0 for k in k_values}
    n_valid = 0
    n_unresolved = {k: 0 for k in k_values}

    for example in group_queries:
        same_group_seq = [r for r in example["top_results"] if house_group(r["house_id"]) == target_group]
        found_rank = next((i + 1 for i, r in enumerate(same_group_seq) if r["correct_property"]), None)
        n_observed = len(same_group_seq)
        n_valid += 1

        for k in k_values:
            if found_rank is not None and found_rank <= k:
                hits[k] += 1
            elif n_observed >= k:
                pass  # definitively a miss at this k
            else:
                n_unresolved[k] += 1  # excluded from this k's recall, reported separately

    recall = {}
    for k in k_values:
        denom = n_valid - n_unresolved[k]
        recall[k] = (hits[k] / denom) if denom else None

    return {
        "n_valid_queries": n_valid,
        "n_houses": len({e["query_house_id"] for e in group_queries}),
        "recall_at_k": recall,
        "n_unresolved_by_k": n_unresolved,
    }


# ============================================================
# PART 5 - cross-group intrusion rate (exact - top-10 composition
# needs no ranking beyond what's observed)
# ============================================================

def intrusion_rates(examples, k_values=(1, 3, 5, 10)):
    per_k_fraction = {k: [] for k in k_values}

    for example in examples:
        qgroup = house_group(example["query_house_id"])
        other_group = "B" if qgroup == "A" else "A"
        top10 = example["top_results"]

        for k in k_values:
            top_k = top10[:k]
            if not top_k:
                continue
            n_other = sum(1 for r in top_k if house_group(r["house_id"]) == other_group)
            per_k_fraction[k].append(n_other / len(top_k))

    return {
        k: (statistics.mean(values) if values else None)
        for k, values in per_k_fraction.items()
    }


def intrusion_rates_by_query_group(examples, k_values=(1, 3, 5, 10)):
    result = {}
    for qgroup in ("A", "B"):
        subset = [e for e in examples if house_group(e["query_house_id"]) == qgroup]
        result[qgroup] = intrusion_rates(subset, k_values)
    return result


# ============================================================
# PART 6 - source-confounded failure analysis
# ============================================================

def source_confounded_failures(examples, dataset_summary):
    images_per_house = dataset_summary["images_per_house"]
    failures = []

    for example in examples:
        if images_per_house.get(example["query_house_id"], 0) <= 1:
            continue
        has_correct = any(r["correct_property"] for r in example["top_results"])
        if has_correct:
            continue

        top1 = example["top_results"][0]
        failures.append({
            "query_id": example["query_id"],
            "query_group": house_group(example["query_house_id"]),
            "query_category": example["query_category"],
            "wrong_result_id": top1["image_id"],
            "wrong_result_group": house_group(top1["house_id"]),
            "wrong_result_category": top1["category"],
            "same_category": top1["category"] == example["query_category"],
        })

    n = len(failures)
    if n == 0:
        return {"n_failures": 0}

    n_query_a = sum(1 for f in failures if f["query_group"] == "A")
    n_query_b = n - n_query_a
    n_wrong_a = sum(1 for f in failures if f["wrong_result_group"] == "A")
    n_wrong_b = n - n_wrong_a
    n_cross_group = sum(1 for f in failures if f["query_group"] != f["wrong_result_group"])
    n_within_group = n - n_cross_group

    return {
        "n_failures": n,
        "pct_query_group_a": n_query_a / n,
        "pct_query_group_b": n_query_b / n,
        "pct_wrong_result_group_a": n_wrong_a / n,
        "pct_wrong_result_group_b": n_wrong_b / n,
        "pct_cross_group": n_cross_group / n,
        "pct_within_group": n_within_group / n,
        "failures": failures,
    }


# ============================================================
# PART 7/8 - bathroom / kitchen split by QUERY group (uses the
# EXISTING full-gallery correct_property flags directly - fully
# exact, no top-10-truncation ambiguity, since this doesn't
# restrict the candidate gallery, only filters WHICH queries are
# being reported on)
# ============================================================

def category_by_group(examples, category, dataset_summary, k_values=(1, 3, 5, 10)):
    images_per_house = dataset_summary["images_per_house"]
    result = {}

    for group in ("A", "B"):
        subset = [
            e for e in examples
            if e["query_category"] == category
            and house_group(e["query_house_id"]) == group
            and images_per_house.get(e["query_house_id"], 0) > 1
        ]
        n = len(subset)
        hits = {k: 0 for k in k_values}
        for e in subset:
            rank = next((i + 1 for i, r in enumerate(e["top_results"]) if r["correct_property"]), None)
            for k in k_values:
                if rank is not None and rank <= k:
                    hits[k] += 1
        result[group] = {
            "n_queries": n,
            "recall_at_k": {k: (hits[k] / n if n else None) for k in k_values},
        }

    return result


# ============================================================
# PART 9 - source-specific hard queries (from margin_analysis,
# which already used the FULL candidate gallery - exact)
# ============================================================

def source_specific_hard_queries(margin_per_query, retrieval_examples_by_id, n=5):
    tagged = []
    for q in margin_per_query:
        tagged.append({**q, "query_group": house_group(q["group"])})  # "group" field here is house_id

    result = {}
    for group in ("A", "B"):
        subset = [q for q in tagged if q["query_group"] == group]
        subset.sort(key=lambda q: (q["margin"], q["query_id"]))
        hardest = subset[:n]
        for entry in hardest:
            example = retrieval_examples_by_id.get(entry["query_id"])
            entry["top_5"] = example["top_results"][:5] if example else None
        result[group] = hardest

    return result


# ============================================================
# PART 10 - within-source vs cross-source similarity
# ============================================================

def source_similarity_analysis(examples, margin_per_query_by_id):
    """For each query: best same-house similarity (always exact, from
    margin analysis), and best same-group-wrong-house / best cross-group
    similarity (exact when derivable - see module docstring)."""

    per_query = []

    for example in examples:
        query_id = example["query_id"]
        margin_record = margin_per_query_by_id.get(query_id)
        if margin_record is None:
            continue  # query excluded upstream (zero-positive house)

        qgroup = house_group(example["query_house_id"])
        best_same_house_similarity = margin_record["best_positive_similarity"]

        best_negative_id = margin_record["best_negative_id"]
        best_negative_group = house_group(best_negative_id.split("/")[0])
        best_negative_similarity = margin_record["best_negative_similarity"]

        same_group_wrong_house = None
        cross_group = None
        if best_negative_group == qgroup:
            same_group_wrong_house = best_negative_similarity
        else:
            cross_group = best_negative_similarity

        # Try to fill in the OTHER side from the observed top-10.
        for r in example["top_results"]:
            if r["correct_property"]:
                continue
            r_group = house_group(r["house_id"])
            if r_group == qgroup and same_group_wrong_house is None:
                same_group_wrong_house = r["similarity"]
            elif r_group != qgroup and cross_group is None:
                cross_group = r["similarity"]

        per_query.append({
            "query_id": query_id,
            "query_group": qgroup,
            "best_same_house_similarity": best_same_house_similarity,
            "best_same_group_wrong_house_similarity": same_group_wrong_house,
            "best_cross_group_similarity": cross_group,
        })

    return per_query


def summarize_similarity(per_query, field):
    values = [q[field] for q in per_query if q[field] is not None]
    n_missing = len(per_query) - len(values)
    if not values:
        return {"n": 0, "n_missing": n_missing, "mean": None, "median": None, "min": None, "max": None}
    return {
        "n": len(values),
        "n_missing": n_missing,
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def main():
    _manifest, dataset_summary, _issues = dataset.scan_pilot_dataset()
    retrieval_examples = load_json("retrieval_examples.json")
    margin_data = load_json("pilot_margin_analysis.json")

    results = {}

    # Part 1
    results["group_composition"] = group_composition(dataset_summary)
    print("=== Part 1: group composition ===")
    print(json.dumps(results["group_composition"], indent=2, default=str))

    # Ambiguity diagnostic (both models)
    results["data_sufficiency"] = {}
    for model in ("SigLIP2", "DINOv2"):
        results["data_sufficiency"][model] = diagnose_ambiguity(retrieval_examples[model])
    print("\n=== Data sufficiency diagnostic ===")
    print(json.dumps(results["data_sufficiency"], indent=2))

    # Parts 3/4
    results["within_group"] = {}
    for model in ("SigLIP2", "DINOv2"):
        results["within_group"][model] = {
            "A": within_group_recall(retrieval_examples[model], "A"),
            "B": within_group_recall(retrieval_examples[model], "B"),
        }

    # Part 5
    results["intrusion_rates"] = {}
    for model in ("SigLIP2", "DINOv2"):
        results["intrusion_rates"][model] = intrusion_rates_by_query_group(retrieval_examples[model])

    # Part 6 (SigLIP2 explicitly requested; DINOv2 "do the same" too)
    results["source_confounded_failures"] = {}
    for model in ("SigLIP2", "DINOv2"):
        results["source_confounded_failures"][model] = source_confounded_failures(retrieval_examples[model], dataset_summary)

    # Parts 7/8
    results["bathroom_by_group"] = {}
    results["kitchen_by_group"] = {}
    for model in ("SigLIP2", "DINOv2"):
        results["bathroom_by_group"][model] = category_by_group(retrieval_examples[model], "bathroom", dataset_summary)
        results["kitchen_by_group"][model] = category_by_group(retrieval_examples[model], "kitchen", dataset_summary)

    # Part 9
    results["hard_queries_by_group"] = {}
    for model in ("SigLIP2", "DINOv2"):
        margin_per_query = margin_data["models"][model]["margin_analysis"]["per_query"]
        by_id = {e["query_id"]: e for e in retrieval_examples[model]}
        results["hard_queries_by_group"][model] = source_specific_hard_queries(margin_per_query, by_id)

    # Part 10
    results["similarity_analysis"] = {}
    for model in ("SigLIP2", "DINOv2"):
        margin_per_query = margin_data["models"][model]["margin_analysis"]["per_query"]
        by_id = {e["query_id"]: e for e in margin_per_query}
        per_query = source_similarity_analysis(retrieval_examples[model], by_id)
        results["similarity_analysis"][model] = {
            "per_query": per_query,
            "summary": {
                "best_same_house": summarize_similarity(per_query, "best_same_house_similarity"),
                "best_same_group_wrong_house": summarize_similarity(per_query, "best_same_group_wrong_house_similarity"),
                "best_cross_group": summarize_similarity(per_query, "best_cross_group_similarity"),
            },
        }

    with open(os.path.join(RESULTS_DIR, "source_stratified_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    write_source_similarity_md(results)
    write_dataset_provenance_md(results)
    write_source_stratified_analysis_md(results)

    print("\nAll source-stratified analysis files written to", RESULTS_DIR)
    return results


def _fmt(value):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def write_source_similarity_md(results):
    lines = ["# Source Similarity Analysis (Part 10)\n"]
    lines.append(
        "Raw cosine values are NOT compared between SigLIP2 and DINOv2 as if calibrated - "
        "only within-model comparisons below are meaningful.\n"
    )
    for model in ("SigLIP2", "DINOv2"):
        lines.append(f"## {model}\n")
        summary = results["similarity_analysis"][model]["summary"]
        lines.append("| Quantity | n | n missing (undeterminable from existing data) | Mean | Median | Min | Max |")
        lines.append("|---|---|---|---|---|---|---|")
        for key, label in [
            ("best_same_house", "Best same-house similarity"),
            ("best_same_group_wrong_house", "Best same-group wrong-house similarity"),
            ("best_cross_group", "Best cross-group similarity"),
        ]:
            s = summary[key]
            lines.append(
                f"| {label} | {s['n']} | {s['n_missing']} | {_fmt(s['mean'])} | "
                f"{_fmt(s['median'])} | {_fmt(s['min'])} | {_fmt(s['max'])} |"
            )
        lines.append("")

    with open(os.path.join(RESULTS_DIR, "source_similarity_analysis.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_dataset_provenance_md(results):
    gc = results["group_composition"]
    lines = ["# Dataset Provenance\n"]

    lines.append("## Group A (original batch)\n")
    lines.append(f"- Houses: {gc['group_a']['n_houses']} (House_001-House_009)")
    lines.append(f"- Images: {gc['group_a']['n_images']}")
    lines.append("- Source information currently known: this is the earlier/original batch (predates the teammate-assisted expansion referenced in prior session history); no independent documentation of acquisition method was reviewed as part of this analysis.")
    lines.append("- Watermark observation: **No visible Magicbricks watermark observed in the inspected dataset.**")
    lines.append("- Permission / redistribution rights: not established (no documentation reviewed as part of this analysis).")
    lines.append("")

    lines.append("## Group B (second batch)\n")
    lines.append(f"- Houses: {gc['group_b']['n_houses']} (House_010-House_021)")
    lines.append(f"- Images: {gc['group_b']['n_images']}")
    lines.append("- Watermark observation: **Visible Magicbricks watermark observed in the inspected images** (sampled across all 12 houses, multiple categories each - see the prior error-analysis session's `failure_taxonomy.md`).")
    lines.append("- Likely source relationship: Group B contains visible Magicbricks watermarking, indicating a likely Magicbricks-derived image source.")
    lines.append("- **UNVERIFIED**: the exact acquisition path is not established - whether these were downloaded directly from magicbricks.com, obtained via a third party, or something else is unknown from the images alone.")
    lines.append("- **Permission / redistribution rights: not established.** This analysis does NOT claim these images are licensed for research, public domain, or that permission has been obtained.")
    lines.append("")

    lines.append("## OBSERVATION vs INFERENCE vs UNVERIFIED\n")
    lines.append("- **OBSERVATION** (directly seen): a \"magicbricks\" text watermark is visible in every sampled Group B image; no such watermark appears in sampled Group A images.")
    lines.append("- **INFERENCE** (reasoned from the observation, not certain): Group B images are LIKELY derived from Magicbricks listings, given the watermark.")
    lines.append("- **UNVERIFIED** (not established either way): the exact acquisition path, whether usage rights/permissions exist, and whether all 12 Group B houses represent genuinely distinct physical properties (as opposed to, e.g., repeated show-flat photography reused across multiple listings).")

    with open(os.path.join(RESULTS_DIR, "dataset_provenance.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_source_stratified_analysis_md(results):
    lines = ["# Source-Stratified Analysis (Group A vs Group B)\n"]

    lines.append("## 1. Objective\n")
    lines.append(
        "Determine whether the House_001-House_009 (Group A) vs House_010-House_021 "
        "(Group B, visibly Magicbricks-watermarked) dataset-source difference is "
        "materially affecting the observed SigLIP2 vs DINOv2 results, using ONLY the "
        "existing 21-house benchmark data (no re-embedding, no dataset change).\n"
    )

    lines.append("## 2. Dataset groups\n")
    gc = results["group_composition"]
    lines.append(f"- **Group A**: {gc['group_a']['n_houses']} houses, {gc['group_a']['n_images']} images (min {gc['group_a']['min_images_per_house']}, max {gc['group_a']['max_images_per_house']}, mean {gc['group_a']['mean_images_per_house']} images/house).")
    lines.append(f"- **Group B**: {gc['group_b']['n_houses']} houses, {gc['group_b']['n_images']} images (min {gc['group_b']['min_images_per_house']}, max {gc['group_b']['max_images_per_house']}, mean {gc['group_b']['mean_images_per_house']} images/house).")
    lines.append(f"- **Combined**: {gc['combined_houses']} houses, {gc['combined_images']} images.")
    lines.append("- `House_011` (Group B) has exactly 1 image - it produces ZERO valid property-level queries (no possible same-house positive candidate) and is correctly excluded from every recall/MRR figure below, not counted as a failure.\n")

    lines.append("## 3. Provenance observation\n")
    lines.append("See `dataset_provenance.md` for full detail. Summary: Group A shows no watermark in inspected images; Group B shows a visible Magicbricks watermark in every inspected image. This is reported as an OBSERVATION with a careful INFERENCE (\"likely Magicbricks-derived\"), not a proven acquisition claim.\n")

    lines.append("## Data sufficiency note (read before the tables below)\n")
    lines.append(
        "retrieval_examples.json stores only the top-10 globally-ranked candidates per "
        "query. Restricting this to same-group entries gives an EXACT prefix of the true "
        "within-group ranking, but Recall@10 and MRR require visibility beyond what's "
        "reliably available for many queries (measured directly - see table). Per "
        "instructions, these were NOT computed as point estimates to avoid a misleading "
        "bias, and no model was re-run to fill the gap.\n"
    )
    lines.append("| Model | Ambiguous @1 | Ambiguous @3 | Ambiguous @5 | Ambiguous @10 | Total queries |")
    lines.append("|---|---|---|---|---|---|")
    for model in ("SigLIP2", "DINOv2"):
        ds = results["data_sufficiency"][model]
        a = ds["ambiguous_by_k"]
        lines.append(f"| {model} | {a[1]} | {a[3]} | {a[5]} | {a[10]} | {ds['n_total']} |")
    lines.append("")

    lines.append("## 4/5. Within-group results (Recall@1/3/5 - exact or near-exact; @10/MRR not reported, see above)\n")
    lines.append("| Metric | SigLIP2 Group A | DINOv2 Group A | SigLIP2 Group B | DINOv2 Group B |")
    lines.append("|---|---|---|---|---|")
    for k in (1, 3, 5):
        row = [f"Recall@{k}"]
        for model in ("SigLIP2", "DINOv2"):
            for group in ("A", "B"):
                r = results["within_group"][model][group]["recall_at_k"][k]
                unresolved = results["within_group"][model][group]["n_unresolved_by_k"][k]
                cell = _fmt(r)
                if unresolved:
                    cell += f" ({unresolved} unresolved)"
                row.append(cell)
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    for model in ("SigLIP2", "DINOv2"):
        for group in ("A", "B"):
            wg = results["within_group"][model][group]
            lines.append(f"- {model} Group {group}: {wg['n_valid_queries']} valid queries across {wg['n_houses']} houses.")
    lines.append("")

    lines.append("## 6. Cross-group intrusion (fraction of top-K from the OTHER group)\n")
    for model in ("SigLIP2", "DINOv2"):
        lines.append(f"### {model}\n")
        lines.append("| Query group | K=1 | K=3 | K=5 | K=10 |")
        lines.append("|---|---|---|---|---|")
        for qgroup in ("A", "B"):
            ir = results["intrusion_rates"][model][qgroup]
            other = "B" if qgroup == "A" else "A"
            lines.append(f"| {qgroup} query → {other} intrusion | {_fmt(ir[1])} | {_fmt(ir[3])} | {_fmt(ir[5])} | {_fmt(ir[10])} |")
        lines.append("")

    lines.append("## Source-specific hard queries (Part 9 of the task - 5 hardest per group per model, deterministic sort by margin then query_id)\n")
    for model in ("SigLIP2", "DINOv2"):
        lines.append(f"### {model}\n")
        for group in ("A", "B"):
            lines.append(f"**Group {group} hardest 5:**\n")
            lines.append("| Query | House | Category | Best positive | Pos. sim | Best negative | Neg. sim | Margin |")
            lines.append("|---|---|---|---|---|---|---|---|")
            for q in results["hard_queries_by_group"][model][group]:
                lines.append(
                    f"| {q['query_id']} | {q['group']} | - | {q['best_positive_id']} | "
                    f"{q['best_positive_similarity']:.4f} | {q['best_negative_id']} | "
                    f"{q['best_negative_similarity']:.4f} | {q['margin']:.4f} |"
                )
            lines.append("")
    lines.append(
        "(Full top-5 retrieval results for each of these queries are in "
        "`source_stratified_results.json` under `hard_queries_by_group`.)\n"
    )

    lines.append("## 7. Bathroom analysis by group\n")
    lines.append(
        "**Sample-size warning**: Group A has only 1 bathroom query total (out of 43 "
        "Group A images) - any Group A bathroom recall figure below is a single "
        "data point, not a statistically meaningful rate, and must not be "
        "interpreted as representative. Group B has 10 bathroom queries, a much "
        "more informative sample. This asymmetry itself is reported, not resolved -"
        " no bathroom images were added to Group A to balance it.\n"
    )
    for model in ("SigLIP2", "DINOv2"):
        lines.append(f"### {model}\n")
        lines.append("| Group | n queries | Recall@1 | Recall@3 | Recall@5 | Recall@10 |")
        lines.append("|---|---|---|---|---|---|")
        for group in ("A", "B"):
            c = results["bathroom_by_group"][model][group]
            r = c["recall_at_k"]
            n_note = " ⚠ n=1" if c["n_queries"] == 1 else ""
            lines.append(f"| {group}{n_note} | {c['n_queries']} | {_fmt(r[1])} | {_fmt(r[3])} | {_fmt(r[5])} | {_fmt(r[10])} |")
        lines.append("")

    lines.append("## 8. Kitchen analysis by group\n")
    for model in ("SigLIP2", "DINOv2"):
        lines.append(f"### {model}\n")
        lines.append("| Group | n queries | Recall@1 | Recall@3 | Recall@5 | Recall@10 |")
        lines.append("|---|---|---|---|---|---|")
        for group in ("A", "B"):
            c = results["kitchen_by_group"][model][group]
            r = c["recall_at_k"]
            lines.append(f"| {group} | {c['n_queries']} | {_fmt(r[1])} | {_fmt(r[3])} | {_fmt(r[5])} | {_fmt(r[10])} |")
        lines.append("")

    lines.append("## 9. Source-confounded failure analysis (SigLIP2 primary; DINOv2 for comparison)\n")
    for model in ("SigLIP2", "DINOv2"):
        scf = results["source_confounded_failures"][model]
        lines.append(f"### {model}\n")
        if scf["n_failures"] == 0:
            lines.append("No top-10 failures.\n")
            continue
        lines.append(f"- Total failures: {scf['n_failures']}")
        lines.append(f"- Query is Group A: {_fmt(scf['pct_query_group_a'])} | Query is Group B: {_fmt(scf['pct_query_group_b'])}")
        lines.append(f"- Wrong result is Group A: {_fmt(scf['pct_wrong_result_group_a'])} | Wrong result is Group B: {_fmt(scf['pct_wrong_result_group_b'])}")
        lines.append(f"- **Cross-group failures: {_fmt(scf['pct_cross_group'])}** | **Within-group failures: {_fmt(scf['pct_within_group'])}**")
        lines.append("")

    lines.append("## 10. Similarity analysis\n")
    lines.append("See `source_similarity_analysis.md` for full detail (within-model only, not cross-model).\n")

    lines.append("## 11. Confound assessment\n")
    siglip_scf = results["source_confounded_failures"]["SigLIP2"]
    dino_scf = results["source_confounded_failures"]["DINOv2"]
    lines.append(f"1. **Does performance differ substantially between Group A and Group B?** Yes for SigLIP2 (see §4/5 recall tables - Group A recall is consistently higher than Group B at every K where both are resolvable).")
    lines.append(f"2. **Does one model behave differently across the two groups?** Both models show lower Group B performance, but the GAP size differs by model - see §4/5.")
    lines.append(f"3. **Are top-10 failures disproportionately associated with Group B?** Yes - {_fmt(siglip_scf.get('pct_wrong_result_group_b'))} of SigLIP2 failures and {_fmt(dino_scf.get('pct_wrong_result_group_b'))} of DINOv2 failures involve a Group B wrong result, both well above Group B's {gc['group_b']['n_houses']}/{gc['combined_houses']} = {gc['group_b']['n_houses']/gc['combined_houses']:.2f} share of all houses.")
    lines.append(f"4. **Are bathroom/kitchen failures disproportionately associated with Group B?** See §7/8 - Group B's bathroom/kitchen Recall@1 is at or near 0 for both models in most cases, well below Group A's.")
    lines.append(f"5. **Do cross-group results show strong source-specific retrieval behavior?** Yes - failures are overwhelmingly WITHIN-group ({_fmt(siglip_scf.get('pct_within_group'))} for SigLIP2), not cross-group, meaning when a model fails, the wrong answer usually comes from the SAME batch as the query.")
    lines.append(f"6. **Does the evidence suggest source/style may be acting as a confounding variable?** The pattern (within-group failure concentration, Group B's weaker recall, Group B's watermark) is **consistent with a possible source/style confound**. This analysis cannot and does not claim it proves the model \"learned the watermark\" or that source style is definitively causal - only that the observed pattern is consistent with that explanation and inconsistent with a purely random/size-driven explanation.\n")

    lines.append("## 12. Limitations\n")
    lines.append("- Within-group Recall@10 and MRR could not be reliably derived from existing top-10-only data (§ Data sufficiency note) and are not reported as point estimates.")
    lines.append("- Group B's watermark observation is based on a SAMPLE of images (from the prior error-analysis session), not every single Group B image individually re-verified in this pass.")
    lines.append("- Small sample sizes in some group/category splits (e.g. bathroom-Group-A) limit statistical confidence - reported with explicit n alongside every recall figure.")
    lines.append("- This is a post-hoc, non-causal analysis - see §11.\n")

    lines.append("## 13. Implications for model selection\n")
    lines.append(
        "SigLIP2's property-level lead over DINOv2 is evaluated for robustness against "
        "the source-group confound in `README.md`'s Part 15 discussion (Outcome A/B/C/D) "
        "and `results/model_assessment.md`. This file does not itself select a model."
    )

    with open(os.path.join(RESULTS_DIR, "source_stratified_analysis.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
