import os

from huggingface_hub import InferenceClient


class ImageGenerationService:

    def __init__(self):

        api_key = os.getenv(
            "HF_API_KEY"
        )

        self.client = None

        if api_key:

            self.client = InferenceClient(
                provider="hf-inference",
                api_key=api_key
            )

    def generate(
        self,
        prompt
    ):

        if self.client is None:

            raise RuntimeError(
                "Hugging Face API is not configured."
            )

        return self.client.text_to_image(
            prompt=prompt,
            model="prompthero/openjourney"
        )