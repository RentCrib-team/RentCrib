import base64
import io
import json
import os
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from PIL import Image, ImageFilter, ImageOps
from pillow_heif import register_heif_opener

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage


register_heif_opener()
BREAKPOINTS = (640, 1280)  # small, medium


MODERATION_JPEG_MAX_DIMENSION = 4096
MODERATION_JPEG_QUALITY = 90

LISTING_UPLOAD_MAX_DIMENSION = 2048
LISTING_UPLOAD_WEBP_QUALITY = 82


def compress_listing_upload(uploaded_file):
    """
    Compress a validated room-listing image before it is passed into
    the existing storage and moderation workflow.

    Safety behaviour:
    - Keeps the original upload if compression fails.
    - Keeps the original upload if compression does not reduce file size.
    - Does not change the existing upload validation rules.
    """

    try:
        uploaded_file.seek(0)

        original_size = getattr(uploaded_file, "size", 0) or 0
        original_name = getattr(
            uploaded_file,
            "name",
            "listing-photo",
        )

        with Image.open(uploaded_file) as source:
            # Correct rotation from phone-camera EXIF information.
            image = ImageOps.exif_transpose(source)
            image.load()

            # Reduce very large phone-camera images.
            if max(image.size) > LISTING_UPLOAD_MAX_DIMENSION:
                image.thumbnail(
                    (
                        LISTING_UPLOAD_MAX_DIMENSION,
                        LISTING_UPLOAD_MAX_DIMENSION,
                    ),
                    Image.Resampling.LANCZOS,
                )

            # WebP output needs a normal RGB image.
            if image.mode in ("RGBA", "LA"):
                background = Image.new(
                    "RGB",
                    image.size,
                    "white",
                )

                alpha = image.getchannel("A")
                background.paste(
                    image,
                    mask=alpha,
                )

                image = background

            elif image.mode != "RGB":
                image = image.convert("RGB")

            output = io.BytesIO()

            image.save(
                output,
                format="WEBP",
                quality=LISTING_UPLOAD_WEBP_QUALITY,
                method=6,
            )

            output.seek(0)
            compressed_bytes = output.read()
            compressed_size = len(compressed_bytes)

            # If compression did not actually make the image smaller,
            # keep the already-validated original file.
            if (
                original_size > 0
                and compressed_size >= original_size
            ):
                uploaded_file.seek(0)
                return uploaded_file

            stem = Path(original_name).stem or "listing-photo"

            compressed_file = ContentFile(
                compressed_bytes,
                name=f"{stem}.webp",
            )

            compressed_file.content_type = "image/webp"
            compressed_file.seek(0)

            return compressed_file

    except Exception:
        # Compression must never break a previously valid upload.
        try:
            uploaded_file.seek(0)
        except Exception:
            pass

        return uploaded_file


def _normalise_image_for_moderation(uploaded_file):
    """
    Decode an uploaded image and create a safe JPEG copy for AI moderation.

    The original uploaded file is not modified or replaced. Vision and
    Gemini receive the normalised JPEG bytes so they do not need to
    support the original format, including AVIF, HEIC, or HEIF.

    Returns:
        ContentFile containing JPEG bytes with content_type=image/jpeg.
    """
    try:
        uploaded_file.seek(0)

        with Image.open(uploaded_file) as source:
            # Correct phone-camera rotation using EXIF orientation.
            image = ImageOps.exif_transpose(source)

            # Ensure all source image data is decoded before the original
            # uploaded stream is reset or closed.
            image.load()

            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            elif image.mode == "L":
                image = image.convert("RGB")

            width, height = image.size

            if max(width, height) > MODERATION_JPEG_MAX_DIMENSION:
                image.thumbnail(
                    (
                        MODERATION_JPEG_MAX_DIMENSION,
                        MODERATION_JPEG_MAX_DIMENSION,
                    ),
                    Image.Resampling.LANCZOS,
                )

            output = io.BytesIO()

            image.save(
                output,
                format="JPEG",
                quality=MODERATION_JPEG_QUALITY,
                optimize=True,
            )

            output.seek(0)

            normalised_file = ContentFile(
                output.read(),
                name="moderation-image.jpg",
            )

            normalised_file.content_type = "image/jpeg"
            normalised_file.seek(0)

            return normalised_file

    finally:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass





def _moderation_result(
    approved: bool,
    reason: str,
    notes: str,
) -> dict:
    """
    Build one consistent moderation response.

    approved=True means the image may be automatically approved.
    approved=False means it remains pending for manual review.
    """
    return {
        "approved": approved,
        "reason": reason,
        "notes": notes[:2000],
    }


def _passes_basic_image_checks(uploaded_file) -> dict:
    """
    Perform local non-AI image validation.

    This checks that the file is a valid image and that its dimensions
    and aspect ratio are suitable for a property listing.
    """
    try:
        uploaded_file.seek(0)

        image = Image.open(uploaded_file)
        image.verify()

        uploaded_file.seek(0)

        verified_image = Image.open(uploaded_file)
        width, height = verified_image.size

        if width < 150 or height < 150:
            return _moderation_result(
                approved=False,
                reason="validation_failed",
                notes=(
                    "Image dimensions are too small. "
                    f"Received {width}x{height}; minimum is 150x150."
                ),
            )

        ratio = width / float(height) if height else 9999

        if ratio < 0.25 or ratio > 4.0:
            return _moderation_result(
                approved=False,
                reason="validation_failed",
                notes=(
                    "Image aspect ratio is outside the permitted range. "
                    f"Calculated ratio: {ratio:.2f}."
                ),
            )

        return _moderation_result(
            approved=True,
            reason="auto_approved",
            notes=(
                "Basic image validation passed. "
                f"Dimensions: {width}x{height}."
            ),
        )

    except Exception as exc:
        return _moderation_result(
            approved=False,
            reason="validation_failed",
            notes=(
                "The uploaded file could not be validated as an image. "
                f"{exc.__class__.__name__}: {exc}"
            ),
        )

    finally:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass


def _google_vision_safesearch_allows(uploaded_file) -> dict:
    """
    Use Google Cloud Vision SafeSearch to identify potentially unsafe content.

    Images that fail this check remain pending for manual review rather
    than being automatically rejected.
    """
    api_key = os.getenv("GOOGLE_VISION_API_KEY", "").strip()

    if not api_key:
        return _moderation_result(
            approved=True,
            reason="auto_approved",
            notes=(
                "Google Vision check skipped because "
                "GOOGLE_VISION_API_KEY is not configured."
            ),
        )

    try:
        uploaded_file.seek(0)

        image_content = base64.b64encode(
            uploaded_file.read()
        ).decode("utf-8")

        payload = {
            "requests": [
                {
                    "image": {
                        "content": image_content,
                    },
                    "features": [
                        {
                            "type": "SAFE_SEARCH_DETECTION",
                        },
                        {
                            "type": "LABEL_DETECTION",
                            "maxResults": 10,
                        },
                    ],
                }
            ]
        }

        url = (
            "https://vision.googleapis.com/v1/images:annotate"
            f"?key={api_key}"
        )

        request = urlrequest.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urlrequest.urlopen(request, timeout=8) as response:
            data = json.loads(
                response.read().decode("utf-8")
            )

        response_data = (data.get("responses") or [{}])[0]

        provider_error = response_data.get("error")

        if provider_error:
            provider_message = (
                provider_error.get("message")
                if isinstance(provider_error, dict)
                else str(provider_error)
            )

            return _moderation_result(
                approved=False,
                reason="service_unavailable",
                notes=(
                    "Google Vision returned an API error: "
                    f"{provider_message}"
                ),
            )

        safe_search = (
            response_data.get("safeSearchAnnotation") or {}
        )

        blocked_values = {
            "LIKELY",
            "VERY_LIKELY",
        }

        flagged_categories = []

        if safe_search.get("adult") in blocked_values:
            flagged_categories.append(
                f"adult={safe_search.get('adult')}"
            )

        if safe_search.get("violence") in blocked_values:
            flagged_categories.append(
                f"violence={safe_search.get('violence')}"
            )

        if safe_search.get("racy") in blocked_values:
            flagged_categories.append(
                f"racy={safe_search.get('racy')}"
            )

        if safe_search.get("medical") == "VERY_LIKELY":
            flagged_categories.append(
                "medical=VERY_LIKELY"
            )

        if safe_search.get("spoof") == "VERY_LIKELY":
            flagged_categories.append(
                "spoof=VERY_LIKELY"
            )

        if flagged_categories:
            return _moderation_result(
                approved=False,
                reason="unsafe_content",
                notes=(
                    "Google Vision flagged the image for manual review: "
                    + ", ".join(flagged_categories)
                    + "."
                ),
            )

        return _moderation_result(
            approved=True,
            reason="auto_approved",
            notes="Google Vision SafeSearch check passed.",
        )

    except TimeoutError as exc:
        return _moderation_result(
            approved=False,
            reason="timeout",
            notes=(
                "Google Vision timed out after 8 seconds. "
                f"{exc.__class__.__name__}: {exc}"
            ),
        )

    except HTTPError as exc:
        return _moderation_result(
            approved=False,
            reason="service_unavailable",
            notes=(
                "Google Vision returned an HTTP error. "
                f"Status: {exc.code}; reason: {exc.reason}."
            ),
        )

    except URLError as exc:
        url_reason = getattr(exc, "reason", exc)

        if isinstance(url_reason, TimeoutError):
            return _moderation_result(
                approved=False,
                reason="timeout",
                notes=(
                    "Google Vision timed out after 8 seconds. "
                    f"{url_reason}"
                ),
            )

        return _moderation_result(
            approved=False,
            reason="service_unavailable",
            notes=(
                "Google Vision could not be reached. "
                f"{url_reason}"
            ),
        )

    except json.JSONDecodeError as exc:
        return _moderation_result(
            approved=False,
            reason="service_unavailable",
            notes=(
                "Google Vision returned invalid JSON. "
                f"{exc}"
            ),
        )

    except Exception as exc:
        return _moderation_result(
            approved=False,
            reason="service_unavailable",
            notes=(
                "Unexpected Google Vision moderation error. "
                f"{exc.__class__.__name__}: {exc}"
            ),
        )

    finally:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass


def _extract_json_object(text: str) -> dict:
    """
    Gemini may return clean JSON or JSON wrapped in markdown.

    Extract the first complete JSON object found in the response.
    """
    if not text:
        return {}

    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = (
            cleaned
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start == -1 or end == -1 or end <= start:
        return {}

    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return {}


def _gemini_property_photo_allows(uploaded_file) -> dict:
    """
    Use Gemini to determine whether the image is suitable for a property
    listing.

    Images that fail or receive a low-confidence result remain pending
    for manual review.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not api_key:
        return _moderation_result(
            approved=True,
            reason="auto_approved",
            notes=(
                "Gemini property-photo check skipped because "
                "GEMINI_API_KEY is not configured."
            ),
        )

    try:
        uploaded_file.seek(0)

        image_content = base64.b64encode(
            uploaded_file.read()
        ).decode("utf-8")

        mime_type = "image/jpeg"

        prompt = """
You are moderating images for a UK room/property rental marketplace.

Decide whether this image is suitable as a property listing photo.

Accept if it clearly shows:
- bedroom
- kitchen
- bathroom
- living room
- dining room
- hallway
- garden
- exterior of a property/building
- balcony
- utility room
- shared household space

Reject if it mainly shows:
- selfie or person portrait
- car or vehicle
- meme
- screenshot
- document
- logo/advert
- animal only
- food only
- unrelated object
- random outdoor scene not clearly linked to a property

Classify the image using the required response schema.

Keep category brief, confidence between 0 and 100, and reason to one
short sentence.

""".strip()

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt,
                        },
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": image_content,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
                "responseJsonSchema": {
                    "type": "object",
                    "properties": {
                        "is_property_photo": {
                            "type": "boolean",
                            "description": (
                                "Whether the image clearly shows a residential "
                                "property or part of one."
                            ),
                        },
                        "category": {
                            "type": "string",
                            "description": (
                                "Short image category such as bedroom, kitchen, "
                                "bathroom, exterior, person, vehicle, document, "
                                "or unrelated outdoor scene."
                            ),
                        },
                        "confidence": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 100,
                            "description": (
                                "Confidence score from 0 to 100."
                            ),
                        },
                        "reason": {
                            "type": "string",
                            "description": (
                                "One short sentence explaining the decision."
                            ),
                        },
                    },
                    "required": [
                        "is_property_photo",
                        "category",
                        "confidence",
                        "reason",
                    ],
                    "additionalProperties": False,
                },
            },
        }

        model = os.getenv(
            "GEMINI_IMAGE_MODEL",
            "gemini-3.5-flash",
        ).strip()

        url = (
            "https://generativelanguage.googleapis.com/"
            "v1beta/models/"
            f"{model}:generateContent"
        )

        request = urlrequest.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )

        with urlrequest.urlopen(request, timeout=12) as response:
            data = json.loads(
                response.read().decode("utf-8")
            )

        candidates = data.get("candidates") or []

        if not candidates:
            return _moderation_result(
                approved=False,
                reason="service_unavailable",
                notes=(
                    "Gemini returned no moderation candidates."
                ),
            )
            
            
            
        candidate = candidates[0]
        finish_reason = str(
            candidate.get("finishReason") or "UNKNOWN"
        ).strip()    

        parts = (
            candidate
            .get("content", {})
            .get("parts", [])
        )

        text = ""

        for part in parts:
            if "text" in part:
                text += part.get("text") or ""

        
        result = _extract_json_object(text)

        if not result:
            return _moderation_result(
                approved=False,
                reason="service_unavailable",
                notes=(
                    "Gemini returned an incomplete or invalid structured "
                    "moderation response. "
                    f"Finish reason: {finish_reason}; "
                    f"response length: {len(text)} characters."
                ),
            )

        is_property_photo = bool(
            result.get("is_property_photo")
        )

        confidence = int(
            result.get("confidence") or 0
        )

        category = str(
            result.get("category") or "unknown"
        )

        provider_reason = str(
            result.get("reason") or ""
        ).strip()

        if not is_property_photo:
            return _moderation_result(
                approved=False,
                reason="not_property_photo",
                notes=(
                    "Gemini did not recognise the upload as a "
                    "property photo. "
                    f"Category: {category}; "
                    f"confidence: {confidence}; "
                    f"reason: {provider_reason or 'not provided'}."
                ),
            )

        if confidence < 65:
            return _moderation_result(
                approved=False,
                reason="low_confidence",
                notes=(
                    "Gemini recognised a possible property photo "
                    "but confidence was below the automatic approval "
                    "threshold. "
                    f"Category: {category}; "
                    f"confidence: {confidence}; "
                    f"reason: {provider_reason or 'not provided'}."
                ),
            )

        return _moderation_result(
            approved=True,
            reason="auto_approved",
            notes=(
                "Gemini property-photo check passed. "
                f"Category: {category}; "
                f"confidence: {confidence}; "
                f"reason: {provider_reason or 'not provided'}."
            ),
        )

    except TimeoutError as exc:
        return _moderation_result(
            approved=False,
            reason="timeout",
            notes=(
                "Gemini timed out after 12 seconds. "
                f"{exc.__class__.__name__}: {exc}"
            ),
        )

    except HTTPError as exc:
        return _moderation_result(
            approved=False,
            reason="service_unavailable",
            notes=(
                "Gemini returned an HTTP error. "
                f"Status: {exc.code}; reason: {exc.reason}."
            ),
        )

    except URLError as exc:
        url_reason = getattr(exc, "reason", exc)

        if isinstance(url_reason, TimeoutError):
            return _moderation_result(
                approved=False,
                reason="timeout",
                notes=(
                    "Gemini timed out after 12 seconds. "
                    f"{url_reason}"
                ),
            )

        return _moderation_result(
            approved=False,
            reason="service_unavailable",
            notes=(
                "Gemini could not be reached. "
                f"{url_reason}"
            ),
        )

    except (ValueError, json.JSONDecodeError) as exc:
        return _moderation_result(
            approved=False,
            reason="service_unavailable",
            notes=(
                "Gemini returned an invalid moderation result. "
                f"{exc.__class__.__name__}: {exc}"
            ),
        )

    except Exception as exc:
        return _moderation_result(
            approved=False,
            reason="service_unavailable",
            notes=(
                "Unexpected Gemini moderation error. "
                f"{exc.__class__.__name__}: {exc}"
            ),
        )

    finally:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass


def should_auto_approve_upload(uploaded_file) -> dict:
    """
    Run the complete image moderation workflow.

    The uploaded file first passes local validation. A normalised JPEG
    copy is then sent to Google Vision and Gemini, regardless of whether
    the original was JPEG, PNG, WEBP or AVIF.

    Returns:
        {
            "approved": bool,
            "reason": str,
            "notes": str,
        }

    A failed moderation check does not reject the upload automatically.
    The image remains pending for manual admin review.
    """
    basic_result = _passes_basic_image_checks(
        uploaded_file
    )

    if not basic_result["approved"]:
        return basic_result

    try:
        moderation_file = _normalise_image_for_moderation(
            uploaded_file
        )
    except Exception as exc:
        return _moderation_result(
            approved=False,
            reason="validation_failed",
            notes=(
                "The uploaded image could not be normalised for "
                "moderation. "
                f"{exc.__class__.__name__}: {exc}"
            ),
        )

    vision_result = _google_vision_safesearch_allows(
        moderation_file
    )

    if not vision_result["approved"]:
        return vision_result

    try:
        moderation_file.seek(0)
    except Exception:
        pass

    gemini_result = _gemini_property_photo_allows(
        moderation_file
    )

    if not gemini_result["approved"]:
        return gemini_result

    notes = " ".join(
        [
            basic_result["notes"],
            vision_result["notes"],
            gemini_result["notes"],
        ]
    )

    return _moderation_result(
        approved=True,
        reason="auto_approved",
        notes=notes,
    )

def _ensure_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "P"):
        return img.convert("RGB")
    return img


def _make_thumb(img: Image.Image, max_width: int) -> Image.Image:
    img = _ensure_rgb(img.copy())
    w, h = img.size
    if w <= max_width:
        return img
    new_h = int(h * (max_width / float(w)))
    img.thumbnail((max_width, new_h), Image.Resampling.LANCZOS)
    return img


def _save_webp(img: Image.Image, base_path: str, suffix: str, quality: int = 82) -> str:
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality, method=6)
    buf.seek(0)
    name = f"{base_path}{suffix}.webp"
    default_storage.save(name, ContentFile(buf.read()))
    return name


def generate_thumbnails_and_return_paths(original_file, base_dir: str, stem: str) -> dict:
    """Saves two WEBP thumbnails inside MEDIA_ROOT to avoid SuspiciousFileOperation."""
    original_file.seek(0)
    img = Image.open(original_file)
    out = {}

    media_base = Path(settings.MEDIA_ROOT) / "test_thumbs"
    media_base.mkdir(parents=True, exist_ok=True)
    base_path = str(media_base / stem)

    for size, suffix in [(640, "_sm"), (1280, "_md")]:
        thumb = img.copy()
        thumb.thumbnail((size, size))
        buf = io.BytesIO()
        thumb.save(buf, format="WEBP", quality=85)
        buf.seek(0)

        rel_name = str(Path("test_thumbs") / f"{stem}{suffix}.webp")
        default_storage.save(rel_name, ContentFile(buf.read()))
        out[suffix.strip("_")] = rel_name

    return out


def generate_blurred_preview(original_file, stem: str) -> str:
    """
    Creates a blurred WEBP preview for pending moderation images.
    """

    original_file.seek(0)

    img = Image.open(original_file)

    img = _ensure_rgb(img)

    img = img.filter(
        ImageFilter.GaussianBlur(radius=12)
    )

    buffer = io.BytesIO()

    img.save(
        buffer,
        format="WEBP",
        quality=80,
    )

    buffer.seek(0)

    path = f"room_images/previews/{stem}_blur.webp"

    default_storage.save(
        path,
        ContentFile(buffer.read())
    )

    return path