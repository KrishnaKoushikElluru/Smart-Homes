"""
Regression tests for a runtime bug found when the MongoDB smoke-test
integration was first exercised against the REAL SigLIP2 model:

    Similarity search error: can't multiply sequence by non-int of type 'list'

Root cause (verified by direct inspection of the real model's output -
see the diagnostic trace in this phase's conversation): on the
installed transformers version, `model.get_image_features(**inputs)`
returns a `transformers.modeling_outputs.BaseModelOutputWithPooling`
(a dict-like ModelOutput with fields last_hidden_state, pooler_output,
...), not a bare `[batch, dim]` tensor. The old code did
`features[0]`, which - because ModelOutput supports positional
indexing over its declared field order - silently returned
`last_hidden_state` (shape `[batch, num_patches, dim]`, the per-patch
token features) instead of the pooled image embedding. `.tolist()` on
that 3-D tensor produced a doubly-nested Python list; L2-normalizing
it then computed `component * component` where `component` was itself
a list of floats, raising exactly "can't multiply sequence by non-int
of type 'list'".

Fix (services/image_similarity/siglip2_encoder.py, encode_image()):
extract `features.pooler_output` when present (falling back to
`features` itself for transformers versions that already return the
pooled tensor directly) BEFORE indexing/listing - i.e. the numerical
boundary between torch and this service's plain-list representation
now always sees a flat `[batch, dim]` tensor.

These tests use torch to build FAKE model outputs (small tensors, no
real inference) so they never download or run the actual ~1GB SigLIP2
model - consistent with this project's existing unit-test convention.
"""

import unittest

from PIL import Image

from services.image_similarity.siglip2_encoder import SiglipEncoder
from services.image_similarity.similarity import l2_normalize


class FakeProcessor:
    """Mimics AutoProcessor's callable interface without loading one."""

    def __call__(self, images, return_tensors="pt"):
        import torch
        return {"pixel_values": torch.zeros(1, 3, 4, 4)}


class FakeModelOutputWithPooler:
    """Mimics transformers.modeling_outputs.BaseModelOutputWithPooling
    closely enough for this bug: a dict-like ModelOutput whose fields
    are indexable by position in DECLARATION ORDER
    (last_hidden_state first, pooler_output second - matching the real
    class), so `fake_output[0]` reproduces exactly what the pre-fix
    code's `features[0]` used to (wrongly) extract."""

    def __init__(self, last_hidden_state, pooler_output):
        self.last_hidden_state = last_hidden_state
        self.pooler_output = pooler_output

    def __getitem__(self, index):
        return (self.last_hidden_state, self.pooler_output)[index]


class FakeModelReturningModelOutput:
    """Reproduces the REAL installed transformers version's behavior:
    get_image_features() returns a BaseModelOutputWithPooling."""

    def get_image_features(self, **inputs):
        import torch
        pooled = torch.tensor([[3.0, 4.0, 0.0, 0.0]])  # the correct 4-d "embedding"
        per_patch_tokens = torch.zeros(1, 5, 4)  # last_hidden_state: [batch, num_patches, dim]
        return FakeModelOutputWithPooler(last_hidden_state=per_patch_tokens, pooler_output=pooled)


class FakeModelReturningBareTensor:
    """Reproduces transformers versions where get_image_features()
    already returns the pooled tensor directly (no ModelOutput
    wrapper) - the fix's fallback path must keep this working."""

    def get_image_features(self, **inputs):
        import torch
        return torch.tensor([[3.0, 4.0, 0.0, 0.0]])


def _make_encoder(fake_model):
    """A SiglipEncoder with its model/processor pre-set, bypassing
    _ensure_loaded() entirely - no real model is ever downloaded or
    loaded."""
    encoder = SiglipEncoder()
    encoder._model = fake_model
    encoder._processor = FakeProcessor()
    encoder._device = "cpu"
    return encoder


class EncodeImagePooledOutputExtractionTests(unittest.TestCase):

    def test_pooled_output_is_extracted_when_model_returns_a_model_output(self):
        encoder = _make_encoder(FakeModelReturningModelOutput())
        image = Image.new("RGB", (4, 4), color=(0, 0, 0))

        vector = encoder.encode_image(image)

        self.assertEqual(len(vector), 4)
        self.assertTrue(all(isinstance(component, float) for component in vector))
        # [3, 4, 0, 0] normalized -> [0.6, 0.8, 0, 0]
        self.assertAlmostEqual(vector[0], 0.6, places=5)
        self.assertAlmostEqual(vector[1], 0.8, places=5)
        self.assertAlmostEqual(vector[2], 0.0, places=5)
        self.assertAlmostEqual(vector[3], 0.0, places=5)

    def test_bare_tensor_return_still_works(self):
        """Fallback path: some transformers versions return the pooled
        tensor directly, with no .pooler_output attribute at all."""
        encoder = _make_encoder(FakeModelReturningBareTensor())
        image = Image.new("RGB", (4, 4), color=(0, 0, 0))

        vector = encoder.encode_image(image)

        self.assertEqual(len(vector), 4)
        self.assertAlmostEqual(vector[0], 0.6, places=5)
        self.assertAlmostEqual(vector[1], 0.8, places=5)

    def test_indexing_a_model_output_directly_reproduces_the_original_crash(self):
        """Proves what the PRE-FIX code path actually did wrong:
        `features[0]` on a dict-like ModelOutput grabs last_hidden_state
        (3-D, per-patch tokens), and L2-normalizing that raises the
        exact reported error - "can't multiply sequence by non-int of
        type 'list'" - because a "component" is itself a list."""
        import torch

        fake_output = FakeModelOutputWithPooler(
            last_hidden_state=torch.zeros(1, 5, 4),
            pooler_output=torch.tensor([[3.0, 4.0, 0.0, 0.0]]),
        )

        wrongly_extracted = fake_output[0]  # the old buggy extraction
        nested_vector = wrongly_extracted.to(torch.float32).tolist()

        self.assertIsInstance(nested_vector[0], list)  # confirms the nesting
        with self.assertRaises(TypeError) as ctx:
            l2_normalize(nested_vector)
        self.assertIn("list", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
