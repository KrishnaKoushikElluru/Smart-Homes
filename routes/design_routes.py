import base64
import io

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify
)

from flask_login import login_required

from services.image_service import (
    ImageGenerationService
)


design_bp = Blueprint(
    "design",
    __name__
)

image_service = ImageGenerationService()


@design_bp.route("/design")
@login_required
def design():

    return render_template(
        "design.html"
    )


@design_bp.route(
    "/generate_image",
    methods=["POST"]
)
@login_required
def generate_image():

    data = request.get_json()

    if not data or "prompt" not in data:

        return jsonify({
            "error": "No prompt provided."
        }), 400

    prompt = data["prompt"].strip()

    if not prompt:

        return jsonify({
            "error": "Prompt cannot be empty."
        }), 400

    try:

        image = image_service.generate(
            prompt
        )

        buffered = io.BytesIO()

        image.save(
            buffered,
            format="PNG"
        )

        image_base64 = base64.b64encode(
            buffered.getvalue()
        ).decode("utf-8")

        return jsonify({
            "image_url": (
                "data:image/png;base64,"
                + image_base64
            )
        })

    except RuntimeError as error:

        return jsonify({
            "error": str(error)
        }), 503

    except Exception as error:

        print(
            f"Image generation error: {error}"
        )

        return jsonify({
            "error": (
                "Image generation service "
                "is currently unavailable."
            )
        }), 503