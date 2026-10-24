"""
Phase 6 - post-hoc error analysis over the EXISTING 21-house benchmark
results. Does NOT re-run either model or recompute embeddings - reads
results/retrieval_examples.json (already contains full top-10 rankings
for every one of the 84 queries, both models), results/pilot_results.json,
and results/pilot_margin_analysis.json, and derives everything else
(valid-query accounting, bathroom-specific metrics, per-category and
per-house failure breakdowns, a failure taxonomy) by pure post-
processing of that already-computed data.

Run with:
    python evaluation/image_similarity/error_analysis.py

Writes:
    results/per_house_analysis.md
    results/bathroom_analysis.json / .md
    results/siglip2_failure_analysis.json / .md
    results/failure_taxonomy.md

Isolated, standalone - not imported by app.py/routes/services, not part
of the normal test suite.
"""

import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluation.image_similarity import dataset

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
K_VALUES = [1, 3, 5, 10]


def load_json(name):
    with open(os.path.join(RESULTS_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# GOAL 1 - valid query accounting
# ============================================================

def valid_query_accounting(dataset_summary):
    images_per_house = dataset_summary["images_per_house"]
    total_images = sum(images_per_house.values())
    total_potential_queries = total_images  # every image is queried exactly once

    zero_positive_houses = {h: n for h, n in images_per_house.items() if n <= 1}
    valid_queries = total_images - sum(zero_positive_houses.values())
    houses_in_valid_queries = len(images_per_house) - len(zero_positive_houses)

    return {
        "total_images": total_images,
        "total_potential_queries": total_potential_queries,
        "valid_property_level_queries": valid_queries,
        "excluded_zero_positive_queries": sum(zero_positive_houses.values()),
        "houses_represented_in_valid_queries": houses_in_valid_queries,
        "zero_positive_houses": zero_positive_houses,
        "total_houses": len(images_per_house),
    }


# ============================================================
# GOAL 3/4 - bathroom-specific analysis
# ============================================================

def bathroom_analysis(retrieval_by_model, dataset_summary):
    report = {}

    for model_name, examples in retrieval_by_model.items():
        bathroom_queries = [e for e in examples if e["query_category"] == "bathroom"]

        images_per_house = dataset_summary["images_per_house"]
        valid_bathroom_queries = [
            e for e in bathroom_queries
            if images_per_house.get(e["query_house_id"], 0) > 1
        ]

        hits_at_k = {k: 0 for k in K_VALUES}
        n_in_top10 = 0
        n_outranked_by_other_bathroom = 0
        per_query_detail = []

        for example in valid_bathroom_queries:
            top_results = example["top_results"]
            first_correct_rank = next(
                (i + 1 for i, r in enumerate(top_results) if r["correct_property"]),
                None,
            )
            for k in K_VALUES:
                if first_correct_rank is not None and first_correct_rank <= k:
                    hits_at_k[k] += 1
            if first_correct_rank is not None:
                n_in_top10 += 1

            # "another house's bathroom outranks every same-house image":
            # the top-ranked result is a DIFFERENT house's bathroom, AND
            # it is ranked ABOVE this query's own first same-house match
            # (or no same-house match exists in top-10 at all).
            top1 = top_results[0]
            top1_is_other_bathroom = (
                not top1["correct_property"] and top1["category"] == "bathroom"
            )
            if top1_is_other_bathroom:
                n_outranked_by_other_bathroom += 1

            per_query_detail.append({
                "query_id": example["query_id"],
                "query_house_id": example["query_house_id"],
                "first_correct_rank": first_correct_rank,
                "top_10": top_results,
            })

        n_valid = len(valid_bathroom_queries)
        report[model_name] = {
            "n_bathroom_queries": len(bathroom_queries),
            "n_valid_bathroom_queries": n_valid,
            "n_excluded_zero_positive": len(bathroom_queries) - n_valid,
            "n_correct_property_in_top10": n_in_top10,
            "n_outranked_by_other_house_bathroom_at_rank1": n_outranked_by_other_bathroom,
            "recall_at_k": {k: (hits_at_k[k] / n_valid if n_valid else None) for k in K_VALUES},
            "queries": per_query_detail,
        }

    return report


# ============================================================
# GOAL 5 - SigLIP2 top-10 failures, grouped by category
# ============================================================

def top10_failures(examples, dataset_summary):
    images_per_house = dataset_summary["images_per_house"]

    failures = []
    category_stats = {}

    for example in examples:
        if images_per_house.get(example["query_house_id"], 0) <= 1:
            continue  # not a valid query - excluded per Goal 1's rule

        category = example["query_category"]
        stats = category_stats.setdefault(category, {"n_valid": 0, "n_failures": 0})
        stats["n_valid"] += 1

        has_correct = any(r["correct_property"] for r in example["top_results"])
        if not has_correct:
            stats["n_failures"] += 1
            failures.append({
                "query_id": example["query_id"],
                "query_house_id": example["query_house_id"],
                "query_category": category,
                "top_10": example["top_results"],
            })

    category_summary = {
        category: {
            "n_valid_queries": s["n_valid"],
            "n_top10_failures": s["n_failures"],
            "failure_rate": s["n_failures"] / s["n_valid"] if s["n_valid"] else None,
        }
        for category, s in sorted(category_stats.items())
    }

    return failures, category_summary


# ============================================================
# GOAL 6 - per-house analysis
# ============================================================

def per_house_analysis(examples, dataset_summary):
    images_per_house = dataset_summary["images_per_house"]

    per_house = {}
    for house_id in images_per_house:
        per_house[house_id] = {
            "n_valid_queries": 0,
            "hits_at_k": {k: 0 for k in K_VALUES},
            "first_correct_ranks": [],  # only for queries WITH a correct hit in top10
            "n_top10_failures": 0,
        }

    for example in examples:
        house_id = example["query_house_id"]
        if images_per_house.get(house_id, 0) <= 1:
            continue

        bucket = per_house[house_id]
        bucket["n_valid_queries"] += 1

        top_results = example["top_results"]
        first_correct_rank = next(
            (i + 1 for i, r in enumerate(top_results) if r["correct_property"]),
            None,
        )
        for k in K_VALUES:
            if first_correct_rank is not None and first_correct_rank <= k:
                bucket["hits_at_k"][k] += 1

        if first_correct_rank is not None:
            bucket["first_correct_ranks"].append(first_correct_rank)
        else:
            bucket["n_top10_failures"] += 1

    result = {}
    for house_id, bucket in per_house.items():
        n = bucket["n_valid_queries"]
        result[house_id] = {
            "n_valid_queries": n,
            "recall_at_k": {k: (bucket["hits_at_k"][k] / n if n else None) for k in K_VALUES},
            "avg_rank_of_first_correct": (
                statistics.mean(bucket["first_correct_ranks"])
                if bucket["first_correct_ranks"] else None
            ),
            "n_top10_failures": bucket["n_top10_failures"],
        }
    return result


# ============================================================
# GOAL 7 - failure taxonomy (evidence-based, category A/B derivable
# programmatically from existing data; C-G require visual inspection
# or dataset-structure context and are left "Unclear" here unless that
# context is unambiguous - see failure_taxonomy.md's manual notes for
# the cases visually inspected separately).
# ============================================================

def classify_failure(failure, dataset_summary):
    """Returns a list of applicable taxonomy codes (never forces
    exactly one) plus a short evidence note. Only assigns a code when
    the existing structured data actually supports it; anything else
    is left for manual/visual review (reported as "Unclear" here)."""

    codes = []
    notes = []

    top1 = failure["top_10"][0]
    query_category = failure["query_category"]
    images_per_house = dataset_summary["images_per_house"]

    # A: same-category wrong-house retrieval
    if top1["category"] == query_category:
        codes.append("A")
        notes.append(f"Top-1 ({top1['image_id']}) is the same category ({query_category}) from house {top1['house_id']}.")

    # B: visually similar different-room retrieval (top-1 is a
    # DIFFERENT category from a different house)
    if top1["category"] != query_category:
        codes.append("B")
        notes.append(f"Top-1 ({top1['image_id']}) is a different category ({top1['category']}) from house {top1['house_id']}.")

    # D: insufficient same-house visual variation - flagged (not
    # asserted) when the query's own house has very few images (2-3),
    # meaning few/no genuinely similar same-house alternatives exist
    # for the model to find in the first place.
    house_image_count = images_per_house.get(failure["query_house_id"], 0)
    if house_image_count <= 3:
        codes.append("D")
        notes.append(f"Query's house ({failure['query_house_id']}) has only {house_image_count} images total - little same-house material to match against.")

    # F: duplicate-related - only if the query or its top-1 result IS
    # one of the two known duplicate images.
    duplicate_ids = {"House_006/bedroom_01.jpeg", "House_006/living_room_01.jpeg"}
    if failure["query_id"] in duplicate_ids or top1["image_id"] in duplicate_ids:
        codes.append("F")
        notes.append("Query or top-1 result is part of the known House_006 byte-identical duplicate pair.")

    # E: potential data-quality/provenance issue - direct visual
    # inspection (see README.md's error-analysis section and
    # needs_review_analysis.md) found a "magicbricks" watermark in
    # EVERY sampled image from House_010 through House_021 (all 12
    # houses, multiple categories each), strongly suggesting these
    # originate from a real-estate LISTING website rather than being
    # personally photographed - unlike House_001-009, which show no
    # such watermark in any sampled image. Flagged (not asserted as
    # definitively causal) whenever BOTH the query and its wrong top-1
    # result are in this watermarked batch, since that is where the
    # visual evidence was actually gathered.
    watermarked_batch_houses = {f"House_{i:03d}" for i in range(10, 22)}
    if failure["query_house_id"] in watermarked_batch_houses and top1["house_id"] in watermarked_batch_houses:
        codes.append("E")
        notes.append(
            "Both query and top-1 result are from the House_010-House_021 batch, where direct visual "
            "inspection found a 'magicbricks' watermark in every sampled image (see needs_review_analysis.md "
            "/ README.md) - these may be sourced from a real-estate listing site rather than personally "
            "photographed, which could make listing-style photos of DIFFERENT actual properties more "
            "visually similar to each other than personal photos would be."
        )

    if not codes:
        codes.append("Unclear")
        notes.append("No structured signal (category match, house size, duplicate) explains this failure - would need visual inspection.")

    return codes, notes


def main():
    dataset_summary_data, _issues = _rescan_dataset_summary()
    retrieval_examples = load_json("retrieval_examples.json")

    # ---- Goal 1 ----
    accounting = valid_query_accounting(dataset_summary_data)
    print("=== Goal 1: valid query accounting ===")
    print(json.dumps(accounting, indent=2))

    # ---- Goal 3/4 ----
    bathroom_report = bathroom_analysis(retrieval_examples, dataset_summary_data)
    with open(os.path.join(RESULTS_DIR, "bathroom_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(bathroom_report, f, indent=2, default=str)
    print("\n=== Goal 3: bathroom analysis (summary) ===")
    for model_name, report in bathroom_report.items():
        print(model_name, {k: v for k, v in report.items() if k != "queries"})

    # ---- Goal 5 ----
    siglip2_failures, siglip2_category_summary = top10_failures(
        retrieval_examples["SigLIP2"], dataset_summary_data
    )
    dinov2_failures, dinov2_category_summary = top10_failures(
        retrieval_examples["DINOv2"], dataset_summary_data
    )
    with open(os.path.join(RESULTS_DIR, "siglip2_failure_analysis.json"), "w", encoding="utf-8") as f:
        json.dump({
            "siglip2_failures": siglip2_failures,
            "siglip2_category_summary": siglip2_category_summary,
            "dinov2_failures": dinov2_failures,
            "dinov2_category_summary": dinov2_category_summary,
        }, f, indent=2, default=str)
    print("\n=== Goal 5: SigLIP2 top-10 failures by category ===")
    print(json.dumps(siglip2_category_summary, indent=2))

    # ---- Goal 6 ----
    siglip2_per_house = per_house_analysis(retrieval_examples["SigLIP2"], dataset_summary_data)
    dinov2_per_house = per_house_analysis(retrieval_examples["DINOv2"], dataset_summary_data)

    # ---- Goal 7 ----
    taxonomy = []
    for failure in siglip2_failures:
        codes, notes = classify_failure(failure, dataset_summary_data)
        taxonomy.append({
            "query_id": failure["query_id"],
            "query_house_id": failure["query_house_id"],
            "query_category": failure["query_category"],
            "codes": codes,
            "notes": notes,
            "top1": failure["top_10"][0],
        })

    # ---- Write markdown reports ----
    write_per_house_md(siglip2_per_house, dinov2_per_house, dataset_summary_data)
    write_bathroom_md(bathroom_report)
    write_siglip2_failure_md(siglip2_failures, siglip2_category_summary, dinov2_category_summary)
    write_failure_taxonomy_md(taxonomy)

    print("\nAll analysis files written to", RESULTS_DIR)


def _rescan_dataset_summary():
    manifest, summary, issues = dataset.scan_pilot_dataset()
    return summary, issues


def write_per_house_md(siglip2_per_house, dinov2_per_house, dataset_summary):
    def sort_key(house_id):
        s = siglip2_per_house[house_id]
        r1 = s["recall_at_k"][1]
        return (-s["n_top10_failures"], (r1 if r1 is not None else 2.0), house_id)

    ordered = sorted(siglip2_per_house.keys(), key=sort_key)

    lines = ["# Per-House Analysis (SigLIP2 primary, DINOv2 for comparison)\n"]
    lines.append(
        "Sorted by: (1) highest SigLIP2 top-10 failure count, (2) lowest SigLIP2 "
        "Recall@1, (3) House ID. Houses with 0 valid queries (House_011 only) are "
        "listed separately at the end - not ranked, since they contribute no "
        "property-level queries at all.\n"
    )

    lines.append("| House | Images | Model | Valid Q | R@1 | R@3 | R@5 | R@10 | Avg rank (when found) | Top-10 failures |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for house_id in ordered:
        n_images = dataset_summary["images_per_house"].get(house_id, 0)
        if siglip2_per_house[house_id]["n_valid_queries"] == 0:
            continue
        for model_name, per_house in (("SigLIP2", siglip2_per_house), ("DINOv2", dinov2_per_house)):
            h = per_house[house_id]
            lines.append(
                f"| {house_id} | {n_images} | {model_name} | {h['n_valid_queries']} | "
                f"{_fmt(h['recall_at_k'][1])} | {_fmt(h['recall_at_k'][3])} | "
                f"{_fmt(h['recall_at_k'][5])} | {_fmt(h['recall_at_k'][10])} | "
                f"{_fmt(h['avg_rank_of_first_correct'])} | {h['n_top10_failures']} |"
            )
    lines.append("")

    zero_query_houses = [h for h, v in siglip2_per_house.items() if v["n_valid_queries"] == 0]
    if zero_query_houses:
        lines.append("## Houses with zero valid queries\n")
        for h in zero_query_houses:
            lines.append(f"- {h}: {dataset_summary['images_per_house'].get(h, 0)} image(s) - no same-house positive candidate exists.")
        lines.append("")

    with open(os.path.join(RESULTS_DIR, "per_house_analysis.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_bathroom_md(bathroom_report):
    lines = ["# Bathroom Retrieval Analysis\n"]
    for model_name, report in bathroom_report.items():
        lines.append(f"## {model_name}\n")
        lines.append(f"- Bathroom queries: {report['n_bathroom_queries']}")
        lines.append(f"- Valid bathroom queries: {report['n_valid_bathroom_queries']}")
        lines.append(f"- Excluded (zero-positive/singleton house): {report['n_excluded_zero_positive']}")
        lines.append(f"- Correct property found somewhere in top-10: {report['n_correct_property_in_top10']}")
        lines.append(f"- Top-1 is another house's bathroom (outranks own house entirely at rank 1): {report['n_outranked_by_other_house_bathroom_at_rank1']}")
        lines.append("")
        lines.append("| Recall@1 | Recall@3 | Recall@5 | Recall@10 |")
        lines.append("|---|---|---|---|")
        r = report["recall_at_k"]
        lines.append(f"| {_fmt(r[1])} | {_fmt(r[3])} | {_fmt(r[5])} | {_fmt(r[10])} |")
        lines.append("")
        lines.append("### Per-query top-10\n")
        for q in report["queries"]:
            lines.append(f"**Query:** `{q['query_id']}` (house {q['query_house_id']}) - first correct-property rank: {q['first_correct_rank']}\n")
            lines.append("| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |")
            lines.append("|---|---|---|---|---|---|---|")
            for i, r_ in enumerate(q["top_10"], start=1):
                lines.append(
                    f"| {i} | {r_['image_id']} | {r_['house_id']} | {r_['category']} | "
                    f"{r_['similarity']:.4f} | {'YES' if r_['correct_property'] else 'NO'} | "
                    f"{'YES' if r_['category'] == 'bathroom' else 'NO'} |"
                )
            lines.append("")

    with open(os.path.join(RESULTS_DIR, "bathroom_analysis.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_siglip2_failure_md(failures, siglip2_category_summary, dinov2_category_summary):
    lines = ["# SigLIP2 Top-10 Failure Analysis\n"]
    lines.append(f"Total SigLIP2 top-10 failures (valid queries only): {len(failures)}\n")

    lines.append("## Failure rate by category (SigLIP2)\n")
    lines.append("| Category | Valid queries | Top-10 failures | Failure rate |")
    lines.append("|---|---|---|---|")
    for category, s in siglip2_category_summary.items():
        lines.append(f"| {category} | {s['n_valid_queries']} | {s['n_top10_failures']} | {_fmt(s['failure_rate'])} |")
    lines.append("")

    lines.append("## Failure rate by category (DINOv2, for comparison)\n")
    lines.append("| Category | Valid queries | Top-10 failures | Failure rate |")
    lines.append("|---|---|---|---|")
    for category, s in dinov2_category_summary.items():
        lines.append(f"| {category} | {s['n_valid_queries']} | {s['n_top10_failures']} | {_fmt(s['failure_rate'])} |")
    lines.append("")

    lines.append("## Every SigLIP2 failure, full top-10\n")
    for failure in failures:
        lines.append(f"**Query:** `{failure['query_id']}` (house {failure['query_house_id']}, category {failure['query_category']})\n")
        lines.append("| Rank | Retrieved house | Retrieved category | Similarity | Same house? | Same category? |")
        lines.append("|---|---|---|---|---|---|")
        for i, r in enumerate(failure["top_10"], start=1):
            lines.append(
                f"| {i} | {r['house_id']} | {r['category']} | {r['similarity']:.4f} | "
                f"{'YES' if r['correct_property'] else 'NO'} | "
                f"{'YES' if r['category'] == failure['query_category'] else 'NO'} |"
            )
        lines.append("")

    with open(os.path.join(RESULTS_DIR, "siglip2_failure_analysis.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_failure_taxonomy_md(taxonomy):
    lines = ["# SigLIP2 Top-10 Failure Taxonomy\n"]
    lines.append(
        "Codes: A=same-category wrong-house, B=visually-similar different-room, "
        "C=strong visual ambiguity (visual inspection only), D=insufficient "
        "same-house visual variation, E=potential data-quality issue (visual "
        "inspection only), F=duplicate-related, G=other, Unclear=insufficient "
        "evidence. Multiple codes may apply; C and E require the separate "
        "manual visual-inspection notes below (not assigned automatically).\n"
    )

    code_counts = {}
    for entry in taxonomy:
        for code in entry["codes"]:
            code_counts[code] = code_counts.get(code, 0) + 1
    lines.append("## Code frequency (automatic pass only - see manual notes for C/E)\n")
    for code, count in sorted(code_counts.items()):
        lines.append(f"- {code}: {count}")
    lines.append("")

    lines.append("## Every failure\n")
    lines.append("| Query | House | Category | Top-1 retrieved | Top-1 house | Top-1 category | Codes | Evidence |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for entry in taxonomy:
        lines.append(
            f"| {entry['query_id']} | {entry['query_house_id']} | {entry['query_category']} | "
            f"{entry['top1']['image_id']} | {entry['top1']['house_id']} | {entry['top1']['category']} | "
            f"{', '.join(entry['codes'])} | {' '.join(entry['notes'])} |"
        )
    lines.append("")

    with open(os.path.join(RESULTS_DIR, "failure_taxonomy.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _fmt(value):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


if __name__ == "__main__":
    main()
