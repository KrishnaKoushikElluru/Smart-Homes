"""
Cosine-similarity FALLBACK for nearby-facility category matching.

ONLY invoked by nearby_facility_extractor.py when its exact regex
patterns (_FACILITY_NOUNS) find a proximity-wrapped phrase ("near a
___", "close to a ___") whose noun matches NONE of the 17 known
facility nouns. The regex path always runs first and always wins when
it matches - this module exists purely to recover genuine near-misses
from paraphrasing ("near an educational institution" instead of "near
a school"), never to replace or compete with the exact path. See
nearby_facility_extractor.py's _extract_semantic_fallback() for the
calling convention.

Self-hosted, local inference - reuses this project's existing
torch/transformers dependency (already required for
services/image_similarity/siglip2_encoder.py's SigLIP2 model), so this
adds no new top-level package. No generative model, no external API
call: this computes two short sentence embeddings and a dot product,
the same cosine-similarity shape as the image-similarity pipeline
(Section 4.3, Equation 1 of the project's own report), just for text.

Lazy-loaded exactly like get_default_encoder() in siglip2_encoder.py -
the model is only pulled into memory the first time a real query
actually needs the fallback, never at app startup and never for a
query the exact path already resolved.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Calibrated against this module's own test queries (see
# test_facility_semantic_matcher.py): a genuine paraphrase of a known
# category ("educational institution" -> school, "grocery store" ->
# supermarket) scores roughly 0.45-0.75 against that category's own
# description; an unrelated word (a color, "cheap", a BHK count) scores
# well under 0.35. Set on the conservative side deliberately - per this
# project's existing "never fabricate" rule (see
# nearby_facility_extractor.py's docstring on radius_m), a weak/
# ambiguous match is left unset here exactly like any other
# unsupported phrasing elsewhere in this NLP layer, rather than guessed.
_MIN_SCORE = 0.42

# Short canonical descriptions, not just the bare category word - gives
# the embedding model more semantic surface to match a paraphrase
# against than a single token would. Keys MUST stay a subset of
# nearby_facility_extractor.NEARBY_FACILITY_CATEGORIES (checked by this
# module's own tests).
_CATEGORY_DESCRIPTIONS = {
    "gym": "gym, fitness center, workout facility",
    "hospital": "hospital, medical center, clinic",
    "school": "school, educational institution for children",
    "college": "college, university, higher education institution",
    "supermarket": "supermarket, grocery store, grocery shop",
    "pharmacy": "pharmacy, chemist, medical store, drugstore",
    "restaurant": "restaurant, eatery, dining place",
    "bank": "bank, banking branch",
    "atm": "atm, cash machine",
    "metro_station": "metro station, subway station, underground train station",
    "railway_station": "railway station, train station",
    "bus_stop": "bus stop, bus stand, bus station",
    "shopping_mall": "shopping mall, shopping center",
    "park": "park, public garden, green space",
    "police_station": "police station",
    "fire_station": "fire station",
    "petrol_station": "petrol pump, gas station, fuel station",
}

_lock = threading.Lock()
_state = {"tokenizer": None, "model": None, "categories": None, "category_embeddings": None}


def _load():
    if _state["model"] is not None:
        return

    with _lock:
        if _state["model"] is not None:  # re-check inside the lock
            return

        import torch
        from transformers import AutoModel, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
        model = AutoModel.from_pretrained(_MODEL_NAME)
        model.eval()

        categories = list(_CATEGORY_DESCRIPTIONS.keys())
        descriptions = [_CATEGORY_DESCRIPTIONS[c] for c in categories]

        with torch.no_grad():
            category_embeddings = _embed(tokenizer, model, descriptions)

        _state["tokenizer"] = tokenizer
        _state["model"] = model
        _state["categories"] = categories
        _state["category_embeddings"] = category_embeddings


def _mean_pool(token_embeddings, attention_mask):
    mask = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    summed = (token_embeddings * mask).sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1e-9)
    return summed / counts


def _embed(tokenizer, model, texts):
    import torch.nn.functional as F

    encoded = tokenizer(texts, padding=True, truncation=True, max_length=32, return_tensors="pt")
    output = model(**encoded)
    pooled = _mean_pool(output.last_hidden_state, encoded["attention_mask"])
    return F.normalize(pooled, p=2, dim=1)


def match_facility_phrase(phrase: str) -> Optional[str]:
    """Returns the best-matching NEARBY_FACILITY_CATEGORIES key for
    `phrase` if its cosine similarity against that category's canonical
    description clears _MIN_SCORE, else None.

    `phrase` is expected to have ALREADY failed every exact pattern in
    nearby_facility_extractor._FACILITY_NOUNS - this is the fallback,
    never the first attempt. Never raises: a model-load or inference
    failure degrades to "no fallback match" (None), exactly like a
    genuinely unrecognized phrase would, rather than breaking the
    query."""

    phrase = (phrase or "").strip()
    if not phrase:
        return None

    try:
        _load()
    except Exception:
        logger.exception("Facility semantic fallback: model load failed, skipping fallback for %r", phrase)
        return None

    import torch

    tokenizer = _state["tokenizer"]
    model = _state["model"]
    categories = _state["categories"]
    category_embeddings = _state["category_embeddings"]

    try:
        with torch.no_grad():
            phrase_embedding = _embed(tokenizer, model, [phrase])
            scores = (phrase_embedding @ category_embeddings.T).squeeze(0)
    except Exception:
        logger.exception("Facility semantic fallback: scoring failed for %r", phrase)
        return None

    best_index = int(torch.argmax(scores).item())
    best_score = float(scores[best_index].item())

    if best_score < _MIN_SCORE:
        return None

    return categories[best_index]
