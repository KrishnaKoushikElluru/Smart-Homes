"""
Safe media upload handling for property listings.

Responsibilities:
  - Extension whitelisting
  - Practical content validation (Pillow image verification, PDF header check)
  - Size limits per file
  - Collision-safe, non-guessable filenames (uuid4, original name discarded)
  - Never exposing filesystem paths to the client
"""

import os
import uuid

from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename


class MediaValidationError(Exception):
    pass


IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
VIDEO_EXTENSIONS = {"mp4", "webm", "mov"}
DOCUMENT_EXTENSIONS = {"pdf"}
FLOOR_PLAN_EXTENSIONS = IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_VIDEO_BYTES = 15 * 1024 * 1024
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024

MAX_IMAGES = 20
MAX_VIDEOS = 5

IMAGE_DIRECTORY = "images/properties"
VIDEO_DIRECTORY = "videos/properties"
DOCUMENT_DIRECTORY = "documents/properties"

IMAGE_CATEGORIES = [
    ("exterior", "Exterior"),
    ("living_room", "Living Room"),
    ("bedroom", "Bedroom"),
    ("kitchen", "Kitchen"),
    ("bathroom", "Bathroom"),
    ("balcony", "Balcony"),
    ("garden", "Garden"),
    ("parking", "Parking"),
    ("floor_plan", "Floor Plan"),
    ("other", "Other"),
]

IMAGE_CATEGORY_VALUES = {value for value, _ in IMAGE_CATEGORIES}


# ============================================================
# HELPERS
# ============================================================

def _extension(filename):

    if not filename or "." not in filename:
        return ""

    return filename.rsplit(".", 1)[-1].lower()


def _unique_filename(extension):

    return f"{uuid.uuid4().hex}.{extension}"


def _file_size(file_storage):

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)

    return size


def _require_extension(filename, allowed_extensions, label):

    extension = _extension(secure_filename(filename or ""))

    if extension not in allowed_extensions:

        raise MediaValidationError(
            f"{label}: unsupported file type '{extension or 'unknown'}'."
        )

    return extension


def _require_size(file_storage, max_bytes, label):

    size = _file_size(file_storage)

    if size == 0:
        raise MediaValidationError(f"{label}: file is empty.")

    if size > max_bytes:
        raise MediaValidationError(
            f"{label}: exceeds the maximum allowed size of "
            f"{max_bytes // (1024 * 1024)}MB."
        )


def _require_valid_image(file_storage, label):

    try:

        file_storage.stream.seek(0)

        with Image.open(file_storage.stream) as image:
            image.verify()

    except (UnidentifiedImageError, OSError, ValueError):

        raise MediaValidationError(f"{label}: not a valid image file.")

    finally:

        file_storage.stream.seek(0)


def _require_valid_pdf(file_storage, label):

    file_storage.stream.seek(0)
    header = file_storage.stream.read(5)
    file_storage.stream.seek(0)

    if header != b"%PDF-":
        raise MediaValidationError(f"{label}: not a valid PDF file.")


# ============================================================
# IMAGES (multiple, with category + cover selection)
# ============================================================

def validate_images(files):
    """Validate every image before anything is written to disk."""

    if not files:
        raise MediaValidationError(
            "At least one property image is required."
        )

    if len(files) > MAX_IMAGES:
        raise MediaValidationError(
            f"You can upload a maximum of {MAX_IMAGES} images."
        )

    for file_storage in files:

        extension = _require_extension(
            file_storage.filename,
            IMAGE_EXTENSIONS,
            "Image",
        )

        _require_size(file_storage, MAX_IMAGE_BYTES, "Image")
        _require_valid_image(file_storage, "Image")


def save_images(files, categories, cover_index, static_root):
    """
    Save already-validated images. Call `validate_images` first.

    Returns (image_filenames, image_meta).
    """

    directory = os.path.join(static_root, IMAGE_DIRECTORY)
    os.makedirs(directory, exist_ok=True)

    saved_filenames = []
    meta = []

    for index, file_storage in enumerate(files):

        extension = _extension(secure_filename(file_storage.filename or ""))
        safe_name = _unique_filename(extension)

        file_storage.stream.seek(0)
        file_storage.save(os.path.join(directory, safe_name))

        category = categories[index] if index < len(categories) else "other"

        if category not in IMAGE_CATEGORY_VALUES:
            category = "other"

        saved_filenames.append(safe_name)

        meta.append({
            "filename": safe_name,
            "category": category,
            "is_cover": index == cover_index,
        })

    if saved_filenames and not any(item["is_cover"] for item in meta):
        meta[0]["is_cover"] = True

    return saved_filenames, meta


# ============================================================
# VIDEOS (multiple)
# ============================================================

def validate_videos(files):

    if len(files) > MAX_VIDEOS:
        raise MediaValidationError(
            f"You can upload a maximum of {MAX_VIDEOS} videos."
        )

    for file_storage in files:

        _require_extension(file_storage.filename, VIDEO_EXTENSIONS, "Video")
        _require_size(file_storage, MAX_VIDEO_BYTES, "Video")


def save_videos(files, static_root):

    directory = os.path.join(static_root, VIDEO_DIRECTORY)
    os.makedirs(directory, exist_ok=True)

    saved_filenames = []

    for file_storage in files:

        extension = _extension(secure_filename(file_storage.filename or ""))
        safe_name = _unique_filename(extension)

        file_storage.stream.seek(0)
        file_storage.save(os.path.join(directory, safe_name))

        saved_filenames.append(safe_name)

    return saved_filenames


# ============================================================
# SINGLE DOCUMENT (floor plan / brochure)
# ============================================================

def validate_single_document(file_storage, allowed_extensions, max_bytes, label):

    if file_storage is None or not file_storage.filename:
        return

    extension = _require_extension(file_storage.filename, allowed_extensions, label)
    _require_size(file_storage, max_bytes, label)

    if extension in IMAGE_EXTENSIONS:
        _require_valid_image(file_storage, label)

    elif extension == "pdf":
        _require_valid_pdf(file_storage, label)


def save_single_document(file_storage, static_root):

    if file_storage is None or not file_storage.filename:
        return None

    extension = _extension(secure_filename(file_storage.filename))
    safe_name = _unique_filename(extension)

    directory = os.path.join(static_root, DOCUMENT_DIRECTORY)
    os.makedirs(directory, exist_ok=True)

    file_storage.stream.seek(0)
    file_storage.save(os.path.join(directory, safe_name))

    return safe_name
