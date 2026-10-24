"""
Phase 6 image-similarity benchmark - main runner.

Run with (from the repo root, using an interpreter that has torch +
transformers installed - see requirements.txt in this folder):

    python evaluation/image_similarity/benchmark.py

STANDALONE ONLY: this script is never imported by app.py, any routes/
or services/ module, or the root test suite. Running it downloads the
SigLIP2 and DINOv2 checkpoints from the Hugging Face Hub on first use
(network access + several hundred MB of disk) - this must only ever
happen when a human runs this file directly.

WHAT THIS RUNS, AND WHY IT IS NOT A REAL-ESTATE RETRIEVAL BENCHMARK:
inspection (see dataset.py's module docstring and
docs/PHASE_6_IMAGE_SIMILARITY_BENCHMARK.md) found that every image
currently in static/images/properties/ is a personal test photo or a
stock wallpaper, not a real property photo - there is no genuine,
honestly-labeled real-estate image set to evaluate Top-K room-category
retrieval against. Per the task's own instruction ("if insufficient,
report the limitation instead of inventing a dataset"), this script
does NOT fabricate real-estate labels. Instead it:

  1. Loads both models and records load time / embedding dimension /
     approximate memory - real, useful numbers regardless of dataset.
  2. Embeds the small set of distinct real files that DO exist
     (dataset.build_pipeline_smoke_manifest()) and runs a pipeline
     SANITY CHECK (not an accuracy benchmark): do the two distinct
     photos of the same physical dorm room end up more similar to each
     other than to unrelated content, for each model?
  3. Reports per-image embedding latency and total runtime.

If a genuine, manually-labeled real-estate manifest is supplied via
--manifest, it also runs the full Top-1/3/5/10 category-retrieval
metrics from metrics.py against that manifest instead.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluation.image_similarity import dataset
from evaluation.image_similarity import models
from evaluation.image_similarity.metrics import (
    rank_candidates,
    top_k_category_accuracy,
    same_property_leakage_rate,
    evaluate_grouped_retrieval,
    exclude_records,
    compute_margins,
)

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
K_VALUES = [1, 3, 5, 10]
PILOT_TOP_K = 10
N_HARD_QUERIES = 5



def embed_manifest(loaded_model, manifest):
    embeddings = {}
    latencies = []

    for record in manifest:
        vector, seconds = models.embed_image(loaded_model, record["path"])
        embeddings[record["id"]] = vector
        latencies.append(seconds)

    return embeddings, latencies


def run_model(load_fn, manifest, run_retrieval_metrics):
    memory_before = models.current_process_memory_mb()

    loaded_model = load_fn()

    embeddings, latencies = embed_manifest(loaded_model, manifest)

    memory_after = models.current_process_memory_mb()

    report = {
        "model_name": loaded_model.name,
        "checkpoint": loaded_model.checkpoint,
        "embedding_dim": loaded_model.embedding_dim,
        "load_seconds": loaded_model.load_seconds,
        "n_images_embedded": len(embeddings),
        "embedding_latency_seconds": {
            "mean": sum(latencies) / len(latencies) if latencies else None,
            "min": min(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "approx_memory_mb": {
            "before_load": memory_before,
            "after_embedding": memory_after,
            "delta": (
                (memory_after - memory_before)
                if memory_before is not None and memory_after is not None
                else None
            ),
        },
    }

    if run_retrieval_metrics:
        records = list(manifest)
        report["top_k_category_accuracy"] = top_k_category_accuracy(records, embeddings, K_VALUES)
        report["same_property_top1_leakage_rate"] = same_property_leakage_rate(records, embeddings, k=1)
    else:
        # Pipeline sanity check instead of a real accuracy metric - see
        # this file's module docstring for why. For every query, just
        # report its single nearest neighbor and similarity score so a
        # human can read the qualitative examples directly.
        report["nearest_neighbor_examples"] = []
        for record in manifest:
            ranked = rank_candidates(record["id"], embeddings)
            if not ranked:
                continue
            nearest_id, nearest_score = ranked[0]
            nearest_record = next(r for r in manifest if r["id"] == nearest_id)
            report["nearest_neighbor_examples"].append({
                "query_id": record["id"],
                "query_true_content": record["label"],
                "nearest_id": nearest_id,
                "nearest_true_content": nearest_record["label"],
                "cosine_similarity": nearest_score,
                "same_true_content": record["label"] == nearest_record["label"],
            })

    return report


def print_dataset_summary(summary):
    print("Pilot dataset")
    print(f"Houses: {summary['n_houses_with_images']}")
    print(f"Images: {summary['n_images']}")
    for house_id in sorted(summary["images_per_house"], key=lambda h: (len(h), h)):
        print(f"{house_id}: {summary['images_per_house'][house_id]} images")
    print("Categories:")
    if summary["categories"]:
        for category, count in summary["categories"].items():
            print(f"{category}: {count}")
    else:
        print("Category-level evaluation unavailable; property-level grouping used.")
    if summary["n_houses_empty"]:
        print(f"({summary['n_houses_empty']} additional house directories exist but currently have no images)")
    if summary["n_unreadable"]:
        print(f"({summary['n_unreadable']} file(s) could not be read as valid images and were excluded)")


def build_qualitative_examples(manifest, embeddings, top_k=PILOT_TOP_K):
    """Full top-K retrieval results for EVERY query image - the
    complete data written to results/retrieval_examples.json. See
    select_representative_examples() for the smaller, human-readable
    subset used in the report/summary."""

    records_by_id = {record["id"]: record for record in manifest}
    examples = []

    for record in manifest:
        query_id = record["id"]
        ranked = rank_candidates(query_id, embeddings)[:top_k]

        top_results = []
        for candidate_id, similarity in ranked:
            candidate = records_by_id[candidate_id]
            top_results.append({
                "image_id": candidate_id,
                "house_id": candidate["house_id"],
                "category": candidate["category"],
                "similarity": similarity,
                "correct_property": candidate["house_id"] == record["house_id"],
            })

        examples.append({
            "query_id": query_id,
            "query_house_id": record["house_id"],
            "query_category": record["category"],
            "top_results": top_results,
        })

    return examples


def select_representative_examples(examples, n=8):
    """Deterministic, non-cherry-picked selection spanning three
    buckets - "found at rank 1" (successful same-house retrieval),
    "found lower in top-K" (difficult retrieval), and "not found at
    all in top-K" (visually-similar-but-wrong-house failures) - so the
    report always shows a mix, never only successes. Bucket order is
    by query_id (not similarity score or any cherry-picked criterion)."""

    def first_correct_rank(example):
        for rank, result in enumerate(example["top_results"], start=1):
            if result["correct_property"]:
                return rank
        return None

    buckets = {"rank_1": [], "rank_2_to_k": [], "not_in_top_k": []}

    for example in examples:
        rank = first_correct_rank(example)
        if rank == 1:
            buckets["rank_1"].append(example)
        elif rank is not None:
            buckets["rank_2_to_k"].append(example)
        else:
            buckets["not_in_top_k"].append(example)

    for bucket in buckets.values():
        bucket.sort(key=lambda example: example["query_id"])

    per_bucket = max(1, n // len(buckets))
    selected = []
    for bucket in buckets.values():
        selected.extend(bucket[:per_bucket])

    if len(selected) < n:
        leftover = [
            example for bucket in buckets.values()
            for example in bucket[per_bucket:]
        ]
        leftover.sort(key=lambda example: example["query_id"])
        selected.extend(leftover[: n - len(selected)])

    return selected[:n]


def run_pilot_model(load_fn, manifest, records):
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    memory_before = models.current_process_memory_mb()

    loaded_model = load_fn()

    embeddings = {}
    latencies = []
    for record in manifest:
        vector, seconds = models.embed_image(loaded_model, record["path"])
        embeddings[record["id"]] = vector
        latencies.append(seconds)
    total_embedding_seconds = sum(latencies)

    memory_after = models.current_process_memory_mb()

    retrieval_start = time.perf_counter()
    property_level = evaluate_grouped_retrieval(records, embeddings, K_VALUES, group_key="house_id")
    # Category-level evaluation excludes records whose category is the
    # "needs_review" placeholder (ambiguous/compound original filename,
    # e.g. "Parking or sit_out.jpeg") - grouping by a placeholder that
    # doesn't represent a real, reliably-determined room type would be
    # meaningless, per Step 9's "ONLY for categories with reliable
    # metadata". These records ARE still included in property_level
    # above (their house identity is not in question).
    category_records = [r for r in records if r["category"] != dataset.AMBIGUOUS_CATEGORY_TOKEN]
    category_embeddings = {
        r["id"]: embeddings[r["id"]] for r in category_records
    }
    category_level = evaluate_grouped_retrieval(category_records, category_embeddings, K_VALUES, group_key="category")
    retrieval_seconds = time.perf_counter() - retrieval_start

    qualitative_examples = build_qualitative_examples(manifest, embeddings)

    return {
        "model_name": loaded_model.name,
        "checkpoint": loaded_model.checkpoint,
        "device": device,
        "embedding_dim": loaded_model.embedding_dim,
        "load_seconds": loaded_model.load_seconds,
        "n_images_processed": len(embeddings),
        "total_embedding_seconds": total_embedding_seconds,
        "avg_embedding_seconds_per_image": (total_embedding_seconds / len(latencies)) if latencies else None,
        "retrieval_computation_seconds": retrieval_seconds,
        "approx_memory_mb": {
            "before_load": memory_before,
            "after_embedding": memory_after,
            "delta": (
                (memory_after - memory_before)
                if memory_before is not None and memory_after is not None
                else None
            ),
        },
        "property_level": property_level,
        "category_level": category_level,
        "qualitative_examples_full": qualitative_examples,
        "qualitative_examples_representative": select_representative_examples(qualitative_examples),
    }


def format_pilot_summary_md(dataset_summary, dataset_issues, model_reports):
    lines = []
    lines.append("# Phase 6 Pilot — Image Similarity Benchmark Summary\n")
    lines.append(
        "**Pilot dataset: {} houses, {} images.** This is a development/pilot "
        "benchmark, not the final SmartHomes image-similarity evaluation — see "
        "`docs/PHASE_6_IMAGE_SIMILARITY_BENCHMARK.md` and this folder's "
        "`README.md` for the full writeup.\n".format(
            dataset_summary["n_houses_with_images"], dataset_summary["n_images"]
        )
    )

    lines.append("## Dataset\n")
    lines.append(f"- Houses with images: {dataset_summary['n_houses_with_images']}")
    lines.append(f"- Total images: {dataset_summary['n_images']}")
    lines.append(f"- Empty/placeholder house directories: {dataset_summary['n_houses_empty']}")
    lines.append(f"- Unreadable files excluded: {dataset_summary['n_unreadable']}")
    lines.append("")
    lines.append("| House | Images |")
    lines.append("|---|---|")
    for house_id in sorted(dataset_summary["images_per_house"], key=lambda h: (len(h), h)):
        lines.append(f"| {house_id} | {dataset_summary['images_per_house'][house_id]} |")
    lines.append("")
    lines.append("| Category | Images |")
    lines.append("|---|---|")
    for category, count in dataset_summary["categories"].items():
        lines.append(f"| {category} | {count} |")
    lines.append("")

    if dataset_issues:
        lines.append("### Dataset issues/observations\n")
        for issue in dataset_issues:
            lines.append(f"- **[{issue.severity}]** {issue.message}")
        lines.append("")

    lines.append("## Comparison (pilot observation — 8 houses / 39 images, not a production claim)\n")
    lines.append(
        "| Metric | " + " | ".join(r["model_name"] for r in model_reports) + " |"
    )
    lines.append("|---|" + "|".join(["---"] * len(model_reports)) + "|")

    def row(label, fn):
        lines.append(f"| {label} | " + " | ".join(fn(r) for r in model_reports) + " |")

    row("Images processed", lambda r: str(r["n_images_processed"]))
    row("Houses", lambda r: str(dataset_summary["n_houses_with_images"]))
    row("Embedding dimension", lambda r: str(r["embedding_dim"]))
    row("Avg embedding latency/image (s)", lambda r: f"{r['avg_embedding_seconds_per_image']:.3f}")
    row("Recall@1 (property)", lambda r: _fmt(r["property_level"]["recall_at_k"].get(1)))
    row("Recall@3 (property)", lambda r: _fmt(r["property_level"]["recall_at_k"].get(3)))
    row("Recall@5 (property)", lambda r: _fmt(r["property_level"]["recall_at_k"].get(5)))
    row("Recall@10 (property)", lambda r: _fmt(r["property_level"]["recall_at_k"].get(10)))
    row("MRR (property)", lambda r: _fmt(r["property_level"]["mrr"]))
    row("Mean positive similarity", lambda r: _fmt(r["property_level"]["mean_positive_similarity"]))
    row("Mean top-negative similarity", lambda r: _fmt(r["property_level"]["mean_top_negative_similarity"]))
    row("Device", lambda r: r["device"])
    row("Model load time (s)", lambda r: f"{r['load_seconds']:.2f}")

    lines.append("")
    lines.append(
        "**Pilot observation only** — with 8 houses / 39 images, any difference "
        "above is not a statistically strong basis for a production model choice. "
        "See the full report for caveats.\n"
    )

    lines.append("## Representative qualitative examples\n")
    for report in model_reports:
        lines.append(f"### {report['model_name']}\n")
        for example in report["qualitative_examples_representative"]:
            lines.append(f"**Query:** `{example['query_id']}` (house {example['query_house_id']}, category {example['query_category']})\n")
            lines.append("| Rank | Image | House | Category | Similarity | Correct Property? |")
            lines.append("|---|---|---|---|---|---|")
            for rank, result in enumerate(example["top_results"], start=1):
                correct = "YES" if result["correct_property"] else "no"
                lines.append(
                    f"| {rank} | {result['image_id']} | {result['house_id']} | "
                    f"{result['category']} | {result['similarity']:.4f} | {correct} |"
                )
            lines.append("")

    return "\n".join(lines)


def _fmt(value):
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def format_dataset_summary_md(dataset_summary, dataset_issues):
    """Step 6's standalone dataset summary: houses, images, per-house
    counts, category totals, and min/max/mean/median images-per-house -
    written every time --pilot runs, independent of model results."""

    import statistics

    counts = list(dataset_summary["images_per_house"].values())

    lines = []
    lines.append("# Dataset Summary\n")
    lines.append(f"Total houses: {dataset_summary['n_houses_with_images']}")
    lines.append(f"Total images: {dataset_summary['n_images']}")
    lines.append("")

    for house_id in sorted(dataset_summary["images_per_house"], key=lambda h: (len(h), h)):
        lines.append(f"{house_id}: {dataset_summary['images_per_house'][house_id]} images")
    lines.append("")

    lines.append("Category totals:")
    for category, count in dataset_summary["categories"].items():
        lines.append(f"{category}: {count}")
    lines.append("")

    if counts:
        lines.append(f"Minimum images/house: {min(counts)}")
        lines.append(f"Maximum images/house: {max(counts)}")
        lines.append(f"Mean images/house: {statistics.mean(counts):.2f}")
        lines.append(f"Median images/house: {statistics.median(counts)}")
    lines.append("")

    lines.append(f"Formats: {dataset_summary.get('formats', {})}")
    lines.append(f"Unreadable files excluded: {dataset_summary['n_unreadable']}")
    lines.append(f"Duplicate groups (byte-identical, SHA-256): {len(dataset_summary.get('duplicate_groups', []))}")
    lines.append("")

    if dataset_issues:
        lines.append("## Issues / observations\n")
        for issue in dataset_issues:
            lines.append(f"- {issue}")

    return "\n".join(lines)


def run_pilot():
    overall_start = time.perf_counter()

    manifest, dataset_summary, dataset_issues = dataset.scan_pilot_dataset()
    records = list(manifest)

    print_dataset_summary(dataset_summary)
    if not dataset_summary["categories"]:
        print("Category-level evaluation unavailable; property-level grouping used.")

    for issue in dataset_issues:
        print(f"  {issue}")

    if dataset_summary["n_images"] == 0:
        print("\nNo images found - nothing to benchmark. Stopping.")
        return

    model_reports = []
    for label, load_fn in (("SigLIP2", models.load_siglip2), ("DINOv2", models.load_dinov2)):
        print(f"\n=== {label} (pilot) ===")
        report = run_pilot_model(load_fn, manifest, records)
        model_reports.append(report)
        print(json.dumps(
            {k: v for k, v in report.items() if k not in ("qualitative_examples_full",)},
            indent=2, default=str,
        ))

    total_runtime_seconds = time.perf_counter() - overall_start

    results = {
        "dataset_summary": dataset_summary,
        "dataset_issues": [str(issue) for issue in dataset_issues],
        "models": [
            {k: v for k, v in report.items() if k != "qualitative_examples_full"}
            for report in model_reports
        ],
        "total_runtime_seconds": total_runtime_seconds,
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)

    with open(os.path.join(RESULTS_DIR, "dataset_summary.md"), "w", encoding="utf-8") as f:
        f.write(format_dataset_summary_md(dataset_summary, dataset_issues))

    with open(os.path.join(RESULTS_DIR, "pilot_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    with open(os.path.join(RESULTS_DIR, "retrieval_examples.json"), "w", encoding="utf-8") as f:
        json.dump(
            {report["model_name"]: report["qualitative_examples_full"] for report in model_reports},
            f, indent=2, default=str,
        )

    summary_md = format_pilot_summary_md(dataset_summary, dataset_issues, model_reports)
    with open(os.path.join(RESULTS_DIR, "pilot_summary.md"), "w", encoding="utf-8") as f:
        f.write(summary_md)

    print(f"\nTotal pilot runtime: {total_runtime_seconds:.1f}s")
    print(f"Results written to {RESULTS_DIR}/pilot_results.json, retrieval_examples.json, pilot_summary.md")


def verify_detected_duplicates(records, summary):
    """Part A / Step 11: explicit, INDEPENDENT SHA-256 re-verification
    of every duplicate group scan_pilot_dataset() reported - re-hashes
    each file directly here rather than only trusting the scan's own
    stored hash, so a mismatch between what the scan found and what is
    actually on disk right now would be caught, not silently assumed.

    Derived dynamically from summary["duplicate_groups"] rather than a
    hardcoded pair, so this keeps working correctly as the dataset
    changes (renames, new houses, new duplicates) without needing
    manual updates each time. Returns a dict with every group's
    verification detail plus the union of all duplicate image_ids
    (the "exclusion set" used for the sensitivity RUN B below)."""

    records_by_id = {record["id"]: record for record in records}

    groups_report = []
    all_duplicate_ids = set()

    for group in summary["duplicate_groups"]:
        image_ids = sorted(group["image_ids"])
        all_duplicate_ids.update(image_ids)

        files = []
        hashes = set()
        for image_id in image_ids:
            record = records_by_id.get(image_id)
            if record is None:
                files.append({"image_id": image_id, "found": False})
                continue
            recomputed_hash = dataset.sha256_of_file(record["path"])
            files.append({
                "image_id": image_id,
                "found": True,
                "path": record["path"],
                "size_bytes": os.path.getsize(record["path"]),
                "sha256": recomputed_hash,
            })
            hashes.add(recomputed_hash)

        groups_report.append({
            "image_ids": image_ids,
            "files": files,
            "identical": (len(hashes) == 1) if all(f.get("found") for f in files) else None,
        })

    return {
        "n_duplicate_groups": len(groups_report),
        "groups": groups_report,
        "all_duplicate_image_ids": sorted(all_duplicate_ids),
    }


def select_hard_queries(margin_result, duplicate_image_ids, n=N_HARD_QUERIES):
    """Part C: deterministic (never randomly/manually cherry-picked)
    selection of the N strongest and N hardest queries by margin. Ties
    are broken by query_id (stable, reproducible ordering). Each
    selected query is flagged if it - or its best positive - is one of
    the dataset's detected duplicate images (`duplicate_image_ids`,
    from verify_detected_duplicates()), per the task's explicit
    instruction to mark duplicate-related queries."""

    duplicate_image_ids = set(duplicate_image_ids)

    def is_duplicate_related(query):
        return bool(
            {query["query_id"], query["best_positive_id"]} & duplicate_image_ids
        )

    per_query = sorted(margin_result["per_query"], key=lambda q: (q["margin"], q["query_id"]))

    hardest = per_query[:n]
    strongest = list(reversed(per_query[-n:])) if len(per_query) >= n else list(reversed(per_query))

    def annotate(query_list):
        return [
            {**query, "duplicate_related": is_duplicate_related(query)}
            for query in query_list
        ]

    return {"strongest": annotate(strongest), "hardest": annotate(hardest)}


def run_duplicate_and_margin_analysis():
    """Parts A, B, C: duplicate-sensitivity (RUN A = all images, RUN B
    = the known duplicate pair excluded from evaluation only - the
    source dataset on disk is never touched), margin analysis (best-
    positive vs best-negative per query), and hard/strong-query
    identification. Embeds every image with each model exactly ONCE
    and reuses those embeddings for all three parts, rather than
    reloading models or re-embedding redundantly."""

    manifest, dataset_summary, dataset_issues = dataset.scan_pilot_dataset()
    records = list(manifest)

    duplicate_verification = verify_detected_duplicates(records, dataset_summary)
    duplicate_image_ids = set(duplicate_verification["all_duplicate_image_ids"])
    print("=== Part A: duplicate verification ===")
    print(json.dumps(duplicate_verification, indent=2, default=str))

    if not duplicate_image_ids:
        print("\nNo byte-identical duplicates detected - RUN B (sensitivity) is identical to RUN A, skipped.")

    model_reports = {}

    for label, load_fn in (("SigLIP2", models.load_siglip2), ("DINOv2", models.load_dinov2)):
        print(f"\n=== {label}: embedding all {len(records)} images ===")
        loaded_model = load_fn()
        embeddings = {}
        for record in manifest:
            vector, _seconds = models.embed_image(loaded_model, record["path"])
            embeddings[record["id"]] = vector

        run_a = evaluate_grouped_retrieval(records, embeddings, K_VALUES, group_key="house_id")

        if duplicate_image_ids:
            records_excl = exclude_records(records, duplicate_image_ids)
            embeddings_excl = {
                image_id: vector for image_id, vector in embeddings.items()
                if image_id not in duplicate_image_ids
            }
            run_b = evaluate_grouped_retrieval(records_excl, embeddings_excl, K_VALUES, group_key="house_id")
        else:
            run_b = None

        margin_result = compute_margins(records, embeddings, group_key="house_id")
        hard_queries = select_hard_queries(margin_result, duplicate_image_ids)

        model_reports[label] = {
            "embedding_dim": loaded_model.embedding_dim,
            "run_a_all_images": run_a,
            "run_b_excl_duplicate": run_b,
            "margin_analysis": margin_result,
            "hard_queries": hard_queries,
        }

        print(f"\n--- {label}: RUN A (all {run_a['n_queries']} images) vs RUN B (duplicate excluded) ---")
        for k in K_VALUES:
            a_val = run_a["recall_at_k"][k]
            b_val = run_b["recall_at_k"][k] if run_b else None
            print(f"Recall@{k}: A={a_val:.3f}  B={(b_val if b_val is not None else float('nan')):.3f}")
        print(f"MRR: A={run_a['mrr']:.3f}  B={(run_b['mrr'] if run_b else float('nan')):.3f}")

        print(f"\n--- {label}: margin summary ---")
        print(json.dumps({k: v for k, v in margin_result.items() if k != "per_query"}, indent=2, default=str))

    sensitivity_table = []
    for k in K_VALUES:
        row = {"metric": f"Recall@{k}"}
        for label in ("SigLIP2", "DINOv2"):
            run_a = model_reports[label]["run_a_all_images"]
            run_b = model_reports[label]["run_b_excl_duplicate"]
            a_val = run_a["recall_at_k"][k]
            b_val = run_b["recall_at_k"][k] if run_b else None
            row[f"{label} All"] = a_val
            row[f"{label} Excl. Duplicate"] = b_val
            row[f"{label} Abs. Diff"] = (
                abs(a_val - b_val) if (a_val is not None and b_val is not None) else None
            )
        sensitivity_table.append(row)
    mrr_row = {"metric": "MRR"}
    for label in ("SigLIP2", "DINOv2"):
        run_a = model_reports[label]["run_a_all_images"]
        run_b = model_reports[label]["run_b_excl_duplicate"]
        a_val = run_a["mrr"]
        b_val = run_b["mrr"] if run_b else None
        mrr_row[f"{label} All"] = a_val
        mrr_row[f"{label} Excl. Duplicate"] = b_val
        mrr_row[f"{label} Abs. Diff"] = (
            abs(a_val - b_val) if (a_val is not None and b_val is not None) else None
        )
    sensitivity_table.append(mrr_row)

    results = {
        "dataset_summary": dataset_summary,
        "duplicate_verification": duplicate_verification,
        "sensitivity_table": sensitivity_table,
        "models": model_reports,
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    json_path = os.path.join(RESULTS_DIR, "pilot_margin_analysis.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    md_path = os.path.join(RESULTS_DIR, "pilot_margin_analysis.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(format_margin_analysis_md(duplicate_verification, sensitivity_table, model_reports))

    print(f"\nResults written to {json_path} and {md_path}")


def format_margin_analysis_md(duplicate_verification, sensitivity_table, model_reports):
    lines = []
    lines.append("# Pilot Duplicate Sensitivity & Margin Analysis\n")

    lines.append("## Part A — Duplicate verification\n")
    n_groups = duplicate_verification["n_duplicate_groups"]
    lines.append(f"**{n_groups} byte-identical duplicate group(s) detected** (independently re-verified via SHA-256, not just trusting the dataset scan's stored hash).\n")
    for group in duplicate_verification["groups"]:
        lines.append(f"- Group: `{'`, `'.join(group['image_ids'])}`")
        for file_info in group["files"]:
            if not file_info.get("found"):
                lines.append(f"  - `{file_info['image_id']}`: **NOT FOUND in current dataset**")
                continue
            lines.append(
                f"  - `{file_info['image_id']}` — {file_info['size_bytes']} bytes — "
                f"SHA-256 `{file_info['sha256']}`"
            )
        lines.append(f"  - **Identical (SHA-256 match): {group['identical']}**")
    lines.append("")

    lines.append("## Part A — Duplicate sensitivity (Recall@K, MRR)\n")
    columns = list(sensitivity_table[0].keys())
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("|" + "|".join(["---"] * len(columns)) + "|")
    for row in sensitivity_table:
        lines.append("| " + " | ".join(_fmt_cell(row[c]) for c in columns) + " |")
    lines.append("")

    lines.append("## Part B — Margin analysis\n")
    lines.append(
        "For every query: `best_positive_similarity` (closest same-house image), "
        "`best_negative_similarity` (closest different-house image), "
        "`margin = best_positive - best_negative`. Not comparable in absolute "
        "terms across models (different embedding-space calibration) — only "
        "within-model ranking/separation behavior is meaningful.\n"
    )
    lines.append("| Metric | SigLIP2 | DINOv2 |")
    lines.append("|---|---|---|")
    for key, label in [
        ("n_queries", "Number of queries"),
        ("n_valid_queries", "Valid queries (>=1 positive & >=1 negative)"),
        ("total_positive_candidate_pairs", "Total positive candidates"),
        ("total_negative_candidate_pairs", "Total negative candidates"),
        ("mean_best_positive_similarity", "Mean best-positive similarity"),
        ("mean_best_negative_similarity", "Mean best-negative similarity"),
        ("mean_margin", "Mean margin"),
        ("median_margin", "Median margin"),
        ("pct_margin_gt_0", "% margin > 0"),
        ("pct_margin_ge_0_05", "% margin >= 0.05"),
        ("pct_margin_ge_0_10", "% margin >= 0.10"),
    ]:
        siglip_val = model_reports["SigLIP2"]["margin_analysis"][key]
        dino_val = model_reports["DINOv2"]["margin_analysis"][key]
        lines.append(f"| {label} | {_fmt_cell(siglip_val)} | {_fmt_cell(dino_val)} |")
    lines.append("")

    lines.append("## Part C — Hard / strong queries by margin\n")
    for label in ("SigLIP2", "DINOv2"):
        lines.append(f"### {label}\n")
        lines.append("**5 strongest (highest margin):**\n")
        lines.append("| Query | House | Best Positive | Pos. Sim | Best Negative | Neg. Sim | Margin | Duplicate-related? |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for q in model_reports[label]["hard_queries"]["strongest"]:
            lines.append(_hard_query_row(q))
        lines.append("")
        lines.append("**5 hardest (lowest margin):**\n")
        lines.append("| Query | House | Best Positive | Pos. Sim | Best Negative | Neg. Sim | Margin | Duplicate-related? |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for q in model_reports[label]["hard_queries"]["hardest"]:
            lines.append(_hard_query_row(q))
        lines.append("")

    return "\n".join(lines)


def _hard_query_row(q):
    return (
        f"| {q['query_id']} | {q['group']} | {q['best_positive_id']} | "
        f"{q['best_positive_similarity']:.4f} | {q['best_negative_id']} | "
        f"{q['best_negative_similarity']:.4f} | {q['margin']:.4f} | "
        f"{'YES' if q['duplicate_related'] else 'no'} |"
    )


def _fmt_cell(value):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=str,
        default=None,
        help="Path to a genuine, manually-labeled JSON manifest (see dataset.load_manifest). "
             "If omitted, uses dataset.build_pipeline_smoke_manifest() - a pipeline sanity check "
             "over the few real, distinct, non-property-photo files currently on disk.",
    )
    parser.add_argument(
        "--pilot",
        action="store_true",
        help="Run the Phase 6 Step 1 pilot benchmark over properties/House_<N>/*.jpeg "
             "(property-level + category-level retrieval evaluation, qualitative examples). "
             "Mutually exclusive with --manifest.",
    )
    parser.add_argument(
        "--margin-analysis",
        action="store_true",
        help="Run the duplicate-sensitivity (Part A) and best-positive/best-negative "
             "margin analysis (Parts B/C) over properties/House_<N>/*.jpeg. Writes "
             "results/pilot_margin_analysis.json and .md. Mutually exclusive with "
             "--manifest/--pilot.",
    )
    args = parser.parse_args()

    if args.margin_analysis:
        run_duplicate_and_margin_analysis()
        return

    if args.pilot:
        run_pilot()
        return

    overall_start = time.perf_counter()

    if args.manifest:
        manifest = dataset.load_manifest(args.manifest)
        run_retrieval_metrics = True
        print(f"Loaded manifest with {len(manifest)} labeled images from {args.manifest}")
    else:
        manifest = dataset.build_pipeline_smoke_manifest()
        run_retrieval_metrics = False
        print(
            f"No --manifest supplied: running the {len(manifest)}-image PIPELINE SANITY CHECK "
            "only (see this file's module docstring - this is NOT a real-estate benchmark)."
        )

    results = {"manifest_size": len(manifest), "used_real_estate_manifest": run_retrieval_metrics}

    print("\n=== SigLIP2 ===")
    results["siglip2"] = run_model(models.load_siglip2, manifest, run_retrieval_metrics)
    print(json.dumps(results["siglip2"], indent=2, default=str))

    print("\n=== DINOv2 ===")
    results["dinov2"] = run_model(models.load_dinov2, manifest, run_retrieval_metrics)
    print(json.dumps(results["dinov2"], indent=2, default=str))

    results["total_runtime_seconds"] = time.perf_counter() - overall_start

    os.makedirs(RESULTS_DIR, exist_ok=True)
    output_path = os.path.join(RESULTS_DIR, "benchmark_results.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\nTotal runtime: {results['total_runtime_seconds']:.1f}s")
    print(f"Results written to {output_path}")


if __name__ == "__main__":
    main()
