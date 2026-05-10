from PIL import Image

from django.core.exceptions import ValidationError

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_IMAGE_PIXELS = 20_000_000
MAX_WIDTH = 8000
MAX_HEIGHT = 8000


def _validate_image_content(file_obj):
    """
    Validate actual image content safely using Pillow.

    Protection includes:
    - corrupted image rejection
    - decompression-bomb protection
    - oversized dimension rejection
    """

    try:
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)

        # global Pillow safeguard
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

        with Image.open(file_obj) as img:
            width, height = img.size

            if width > MAX_WIDTH or height > MAX_HEIGHT:
                raise ValidationError(
                    f"Image dimensions too large "
                    f"(max {MAX_WIDTH}x{MAX_HEIGHT})."
                )

            total_pixels = width * height
            if total_pixels > MAX_IMAGE_PIXELS:
                raise ValidationError(
                    "Image contains too many pixels."
                )

            img.verify()

    except ValidationError:
        raise

    except Exception:
        raise ValidationError(
            "Invalid, corrupted, or unsafe image file."
        )

    finally:
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)


def validate_avatar_image(file_obj):
    ctype = getattr(file_obj, "content_type", "") or ""

    if ctype not in ALLOWED_IMAGE_TYPES:
        raise ValidationError(f"Unsupported image type: {ctype}")

    size = getattr(file_obj, "size", 0) or 0
    if size <= 0 or size > MAX_BYTES:
        raise ValidationError("Image file too large (max 5MB).")

    _validate_image_content(file_obj)

    return file_obj

def validate_listing_photos(files, *, max_count=10, max_mb=10):
    if not files:
        return
    if not isinstance(files, (list, tuple)):
        files = [files]
    if len(files) > max_count:
        raise ValidationError(f"Too many photos. Max {max_count} allowed.")
    max_bytes = max_mb * 1024 * 1024
    for f in files:
        ctype = getattr(f, "content_type", "") or ""
        if ctype not in ALLOWED_IMAGE_TYPES:
            raise ValidationError(f"Unsupported image type: {ctype}")
        size = getattr(f, "size", 0) or 0
        if size <= 0 or size > max_bytes:
            raise ValidationError(f"Photo too large (max {max_mb}MB).")
    return files

def assert_no_duplicate_files(files):
    if not files:
        return
    if not isinstance(files, (list, tuple)):
        files = [files]
    seen = set()
    dups = []
    for f in files:
        key = (getattr(f, "name", "").lower(), getattr(f, "size", 0))
        if key in seen:
            dups.append(getattr(f, "name", "unnamed file"))
        seen.add(key)
    if dups:
        raise ValidationError(f"Duplicate file(s): {', '.join(dups)}")
    return files
