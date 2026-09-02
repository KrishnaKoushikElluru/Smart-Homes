from diffusers import StableDiffusionPipeline
import torch
from PIL import Image

# 🔁 Load the model from Hugging Face (downloads only once)
pipe = StableDiffusionPipeline.from_pretrained(
    "runwayml/stable-diffusion-v1-5",
    torch_dtype=torch.float16  # Use float32 if you get errors
)

# 🔄 Use GPU if available, else fallback to CPU
device = "cuda" if torch.cuda.is_available() else "cpu"
pipe = pipe.to(device)

# ✏️ Prompt (you can change this anytime!)
prompt = "a luxury smart home with solar panels and infinity pool"

# 🖼️ Generate the image!
image = pipe(prompt).images[0]

# 💾 Save the image
image.save("smart_home_result.png")
print("✅ Image saved as smart_home_result.png")
