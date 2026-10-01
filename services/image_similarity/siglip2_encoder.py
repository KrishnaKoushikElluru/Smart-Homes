"""
Lazy-loaded, process-cached SigLIP2 image encoder - image -> embedding
only (no text prompts, no zero-shot classification; this is purely
the vision tower used for image-image similarity).

ISOLATION: this is the ONLY file under services/ that imports torch/
transformers. Nothing in app.py or any routes/ module imports this
module (app.py only imports specific named service modules by name -
it never does a broad `import services` or auto-discovers
submodules), so the model is NEVER loaded at Flask startup or on any
existing request path. Loading only happens the first time
encode_image()/encode_images() is actually called.

Model: google/siglip2-base-patch16-224, loaded via AutoModel - NOT the
newer Siglip2Model class. This checkpoint's own config.json declares
"model_type": "siglip" (its fixed-resolution variant keeps the
original SigLIP Conv2d patch-embedding architecture; only the NaFlex
variants use the newer Siglip2Model class with a Linear patch
embedding). Forcing Siglip2Model onto this checkpoint fails with a
weight-shape mismatch - verified directly during an earlier phase of
this same project's SigLIP2 vs DINOv2 benchmark work
(evaluation/image_similarity/models.py carries the same note).
AutoModel correctly resolves to SiglipModel here, which still exposes
get_image_features() for image embeddings.
"""

import io
import threading
import time

MODEL_ID = "google/siglip2-base-patch16-224"


class InvalidImageError(ValueError):
    """Raised when an input cannot be decoded/converted to a usable
    RGB image - corrupted or unrecognized image data is never
    silently swallowed."""


class SiglipEncoder:
    """One instance = one lazily-loaded model+processor, cached for
    the lifetime of the instance. Safe to keep as a process-lifetime
    singleton (see get_default_encoder() below).

    Thread-safety: a lock guards the one-time load, so concurrent
    first calls from multiple Flask worker threads cannot race to
    load the model twice. Encode calls run under the same lock too -
    Hugging Face model objects are not guaranteed thread-safe for
    concurrent forward passes, and this project has no request volume
    yet that would justify a more elaborate (e.g. per-thread model
    copy, or a request queue) design; a single lock around inference
    is the smallest correct thing that works for the current
    architecture, not unnecessary infrastructure.
    """

    def __init__(self, model_id=MODEL_ID, device=None):
        self.model_id = model_id
        self._requested_device = device
        self._model = None
        self._processor = None
        self._device = None
        self._lock = threading.Lock()
        self.embedding_dim = None
        self.load_seconds = None

    @property
    def device(self):
        """Observable for debugging/tests - None until the model has
        actually been loaded (first encode call), then "cuda" or
        "cpu"."""
        return self._device

    @property
    def is_loaded(self):
        return self._model is not None

    def _ensure_loaded(self):
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:  # re-check inside the lock
                return
            import torch
            from transformers import AutoModel, AutoProcessor

            device = self._requested_device or ("cuda" if torch.cuda.is_available() else "cpu")

            start = time.perf_counter()
            processor = AutoProcessor.from_pretrained(self.model_id)
            model = AutoModel.from_pretrained(self.model_id)
            model.to(device)
            model.eval()
            self.load_seconds = time.perf_counter() - start

            self._processor = processor
            self._model = model
            self._device = device

    def _load_pil_image(self, image):
        """Accepts a PIL.Image, a file path (str/Path), or raw bytes.
        Always converts to RGB - explicitly handles grayscale ("L"),
        RGBA, and palette images via Pillow's own convert(), which is
        the correct way to normalize any of these into the 3-channel
        input the processor expects. Raises InvalidImageError (never a
        bare/opaque exception) for anything that can't be decoded.

        This method touches no model state, so it is directly testable
        without loading SigLIP2 or importing torch."""

        from PIL import Image, UnidentifiedImageError

        try:
            if isinstance(image, Image.Image):
                pil_image = image
            elif isinstance(image, (bytes, bytearray)):
                pil_image = Image.open(io.BytesIO(image))
                pil_image.load()
            else:
                pil_image = Image.open(image)
                pil_image.load()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise InvalidImageError(f"could not decode image: {exc}") from exc

        try:
            return pil_image.convert("RGB")
        except Exception as exc:  # noqa: BLE001 - a conversion failure is still an invalid-image case
            raise InvalidImageError(f"could not convert image to RGB: {exc}") from exc

    def encode_image(self, image):
        """image -> preprocessing -> SigLIP2 vision encoder -> raw
        image embedding -> float32 -> L2 normalization. Returns the
        NORMALIZED embedding as a plain Python list[float] (not a
        torch tensor / numpy array), so downstream code
        (embedding_cache.py, similarity.py) never needs a torch import
        of its own."""

        self._ensure_loaded()

        import torch
        from services.image_similarity.similarity import l2_normalize

        pil_image = self._load_pil_image(image)

        with self._lock:
            inputs = self._processor(images=pil_image, return_tensors="pt")
            inputs = {key: value.to(self._device) for key, value in inputs.items()}

            with torch.no_grad():
                features = self._model.get_image_features(**inputs)

            # On this checkpoint/transformers version, get_image_features()
            # returns a BaseModelOutputWithPooling (dict-like), not a bare
            # [batch, dim] tensor - features[0] would silently index into
            # that object's first field (last_hidden_state, the per-patch
            # token features, shape [batch, num_patches, dim]) instead of
            # the pooled image embedding, producing a doubly-nested list
            # that fails downstream L2 normalization ("can't multiply
            # sequence by non-int of type 'list'"). The actual pooled
            # image embedding is `.pooler_output` (shape [batch, dim]).
            # Some transformers versions return the pooled tensor directly
            # from get_image_features() instead - handled by falling back
            # to `features` itself when there's no .pooler_output.
            image_embeds = getattr(features, "pooler_output", features)

            vector = image_embeds[0].to("cpu").to(torch.float32).tolist()

        self.embedding_dim = len(vector)
        return l2_normalize(vector)

    def encode_images(self, images):
        """Encodes a list of images one at a time, returning a list of
        normalized embeddings in the same order as `images`.

        NOT batched into a single forward pass: this project's current
        dataset is 84 images (Step 16 of this phase: brute-force
        comparison is fine at this scale), and batching would need
        padding/attention-mask handling this project doesn't need yet
        - premature complexity for the current dataset size.

        An invalid image anywhere in the list raises immediately
        (InvalidImageError) and aborts the whole call - callers that
        need per-image error isolation (e.g. the offline index
        builder, which must report failed images individually rather
        than abort the whole run) should call encode_image() inside
        their own try/except per image instead of using this method.
        """

        return [self.encode_image(image) for image in images]


_default_encoder_lock = threading.Lock()
_default_encoder = None


def get_default_encoder():
    """Process-wide lazily-created singleton - the "load once, reuse
    for every subsequent call" behavior this service is required to
    have. Safe to call from multiple threads (double-checked locking);
    the returned SiglipEncoder is itself safe for concurrent
    encode_image() calls (see SiglipEncoder's own docstring)."""

    global _default_encoder
    if _default_encoder is not None:
        return _default_encoder
    with _default_encoder_lock:
        if _default_encoder is None:
            _default_encoder = SiglipEncoder()
        return _default_encoder
