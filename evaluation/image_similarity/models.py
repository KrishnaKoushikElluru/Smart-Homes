"""
Phase 6 image-similarity benchmark - model loading + embedding
extraction for SigLIP2 and DINOv2.

ISOLATION: this module is the ONLY place in the whole repository that
imports torch/transformers or downloads a model checkpoint. It is
never imported by app.py, any routes/ module, any services/ module, or
the root test suite (test_image_similarity_metrics.py tests
metrics.py's pure logic only, with synthetic embeddings, and never
imports this file). Running this module downloads ~400MB-1GB of model
weights from the Hugging Face Hub on first use and requires network
access - by design, that only ever happens when a human explicitly
runs evaluation/image_similarity/benchmark.py, never during
`python -m unittest discover` and never at Flask startup.

Pretrained checkpoints only - no fine-tuning, no training, exactly as
specified. Every embedding is L2-normalized (via metrics.l2_normalize)
before being handed back, matching the task's required pipeline:
    image -> preprocessing -> model -> image embedding -> L2 normalization
"""

import time

from PIL import Image

from evaluation.image_similarity.metrics import l2_normalize

SIGLIP2_CHECKPOINT = "google/siglip2-base-patch16-224"
DINOV2_CHECKPOINT = "facebook/dinov2-base"


class LoadedModel:
    """Bundles a loaded model + its processor + the bookkeeping the
    benchmark report needs (load time, embedding dimension) - kept
    deliberately thin, no caching/singleton behavior, since this is a
    one-shot benchmark script, not a long-lived service."""

    def __init__(self, name, checkpoint, model, processor, kind, load_seconds):
        self.name = name
        self.checkpoint = checkpoint
        self.model = model
        self.processor = processor
        self.kind = kind  # "siglip2" or "dinov2" - selects the right forward-pass shape below
        self.load_seconds = load_seconds
        self.embedding_dim = None  # filled in after the first embed_image() call


def load_siglip2():
    import torch
    from transformers import AutoModel, AutoImageProcessor

    # NOTE: google/siglip2-base-patch16-224's own config.json declares
    # "model_type": "siglip" (not "siglip2") - this is NOT a metadata
    # bug. SigLIP2's fixed-resolution checkpoints (this one) keep the
    # original SigLIP Conv2d patch-embedding architecture; only the
    # NaFlex variants (e.g. siglip2-base-patch16-naflex) use the newer
    # Siglip2Model class with a Linear patch embedding. Forcing
    # Siglip2Model onto THIS checkpoint fails with a weight shape
    # mismatch (torch.Size([768, 3, 16, 16]) vs ([768, 768])) - verified
    # directly during this benchmark's development. AutoModel correctly
    # resolves to SiglipModel here, which is the right class for this
    # checkpoint and still exposes get_image_features().
    start = time.perf_counter()
    processor = AutoImageProcessor.from_pretrained(SIGLIP2_CHECKPOINT)
    model = AutoModel.from_pretrained(SIGLIP2_CHECKPOINT)
    model.eval()
    load_seconds = time.perf_counter() - start

    return LoadedModel("SigLIP2", SIGLIP2_CHECKPOINT, model, processor, "siglip2", load_seconds)


def load_dinov2():
    import torch
    from transformers import Dinov2Model, AutoImageProcessor

    start = time.perf_counter()
    processor = AutoImageProcessor.from_pretrained(DINOV2_CHECKPOINT)
    model = Dinov2Model.from_pretrained(DINOV2_CHECKPOINT)
    model.eval()
    load_seconds = time.perf_counter() - start

    return LoadedModel("DINOv2", DINOV2_CHECKPOINT, model, processor, "dinov2", load_seconds)


def embed_image(loaded_model, image_path):
    """image -> preprocessing -> model -> image embedding -> L2
    normalization. Returns (embedding: list[float], seconds: float).
    Pretrained inference only - torch.no_grad(), no gradient/training
    machinery touched anywhere in this benchmark."""

    import torch

    image = Image.open(image_path).convert("RGB")

    start = time.perf_counter()

    inputs = loaded_model.processor(images=image, return_tensors="pt")

    with torch.no_grad():
        if loaded_model.kind == "siglip2":
            features = loaded_model.model.get_image_features(**inputs)
        elif loaded_model.kind == "dinov2":
            outputs = loaded_model.model(**inputs)
            features = outputs.pooler_output
        else:
            raise ValueError(f"unknown model kind: {loaded_model.kind!r}")

    seconds = time.perf_counter() - start

    vector = features[0].tolist()
    loaded_model.embedding_dim = len(vector)

    return l2_normalize(vector), seconds


def current_process_memory_mb():
    """Approximate resident-memory footprint of the current process,
    in MB. Best-effort: returns None if `psutil` isn't installed rather
    than failing the whole benchmark over an optional diagnostic."""

    try:
        import psutil
        import os
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / (1024 * 1024)
    except ImportError:
        return None
