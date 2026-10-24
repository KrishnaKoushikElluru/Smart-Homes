"""
Offline utility: scans the existing 84-image dataset
(properties/House_<NNN>/*.jpg|jpeg), encodes every image with SigLIP2,
L2-normalizes each embedding, and saves the resulting embedding index
via EmbeddingCache. Never modifies, renames, or augments any source
image.

Run with (from the repo root):
    python services/image_similarity/index_builder.py

This is a STANDALONE script - not imported by app.py/routes/, and
never runs automatically. Downloads the SigLIP2 checkpoint from the
Hugging Face Hub on first use if not already cached locally.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from services.image_similarity.embedding_cache import EmbeddingCache
from services.image_similarity.siglip2_encoder import SiglipEncoder

DEFAULT_DATASET_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "properties"))
DEFAULT_CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")


def scan_dataset(root):
    """Yields (property_id, image_id, image_path) for every image file
    under root/House_<NNN>/*. property_id = the house folder name
    (e.g. "House_007"); image_id = "<property_id>/<filename>" - the
    same identifier convention already used by
    evaluation/image_similarity/dataset.py, for consistency across
    this project's two similarity-related modules."""

    for house_dir in sorted(os.listdir(root)):
        full_house_dir = os.path.join(root, house_dir)
        if not os.path.isdir(full_house_dir):
            continue
        for filename in sorted(os.listdir(full_house_dir)):
            path = os.path.join(full_house_dir, filename)
            if not os.path.isfile(path):
                continue
            yield house_dir, f"{house_dir}/{filename}", path


def build_index(dataset_root=None, encoder=None):
    """Returns (cache, report). Does not write anything to disk itself
    - see main() for saving the cache/report files."""

    dataset_root = dataset_root or DEFAULT_DATASET_ROOT
    encoder = encoder or SiglipEncoder()

    cache = EmbeddingCache()
    failures = []
    n_images_scanned = 0
    houses = set()

    overall_start = time.perf_counter()

    for property_id, image_id, image_path in scan_dataset(dataset_root):
        houses.add(property_id)
        n_images_scanned += 1
        try:
            embedding = encoder.encode_image(image_path)
        except Exception as exc:  # noqa: BLE001 - report every failure, never abort the whole build
            failures.append({"image_id": image_id, "path": image_path, "error": str(exc)})
            continue
        cache.add(property_id, image_id, image_path, encoder.model_id, embedding)

    total_seconds = time.perf_counter() - overall_start

    report = {
        "model": encoder.model_id,
        "device": encoder.device,
        "model_load_seconds": encoder.load_seconds,
        "n_houses": len(houses),
        "n_images_scanned": n_images_scanned,
        "n_images_indexed": len(cache),
        "n_failures": len(failures),
        "failures": failures,
        "embedding_dim": encoder.embedding_dim,
        "total_seconds": total_seconds,
        "avg_seconds_per_image": (total_seconds / n_images_scanned) if n_images_scanned else None,
    }

    return cache, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", default=None, help="Defaults to the repo's properties/ directory.")
    parser.add_argument("--cache-dir", default=None, help="Defaults to services/image_similarity/cache/.")
    args = parser.parse_args()

    cache, report = build_index(args.dataset_root)

    cache_dir = args.cache_dir or DEFAULT_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)

    npz_path = os.path.join(cache_dir, "siglip2_index.npz")
    meta_path = os.path.join(cache_dir, "siglip2_index_meta.json")
    cache.save(npz_path, meta_path)

    report_path = os.path.join(cache_dir, "index_build_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print(json.dumps(report, indent=2, default=str))
    print(f"\nIndex saved to {npz_path} and {meta_path}")
    print(f"Report saved to {report_path}")


if __name__ == "__main__":
    main()
