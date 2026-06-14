import base64
import io
import json
import os
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from PIL import Image
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

BREAKPOINTS = (640, 1280)  # small, medium


def _passes_basic_image_checks(uploaded_file) -> bool:
    """
    Local non-AI vetting.
    True  -> image structure looks acceptable
    False -> hold for admin review
    """
    try:
        uploaded_file.seek(0)
        img = Image.open(uploaded_file)
        img.verify()

        uploaded_file.seek(0)
        img2 = Image.open(uploaded_file)
        w, h = img2.size

        if w < 150 or h < 150:
            return False

        ratio = w / float(h) if h else 9999
        if ratio < 0.25 or ratio > 4.0:
            return False

        return True
    except Exception:
        return False
    finally:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass


def _google_vision_safesearch_allows(uploaded_file) -> bool:
    """
    Uses Google Cloud Vision SafeSearch.

    True  -> safe enough to auto-approve
    False -> keep pending for manual/admin review
    """
    api_key = os.getenv("GOOGLE_VISION_API_KEY", "").strip()

    # Local/test/dev fallback: if no key is configured, do not break uploads.
    if not api_key:
        return True

    try:
        uploaded_file.seek(0)
        image_content = base64.b64encode(uploaded_file.read()).decode("utf-8")

        payload = {
            "requests": [
                {
                    "image": {"content": image_content},
                    "features": [
                        {"type": "SAFE_SEARCH_DETECTION"},
                        {"type": "LABEL_DETECTION", "maxResults": 10},
                    ],
                }
            ]
        }

        url = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"

        req = urlrequest.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urlrequest.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))

        response_data = (data.get("responses") or [{}])[0]

        if response_data.get("error"):
            return False

        safe = response_data.get("safeSearchAnnotation") or {}

        blocked_values = {"LIKELY", "VERY_LIKELY"}

        if safe.get("adult") in blocked_values:
            return False

        if safe.get("violence") in blocked_values:
            return False

        if safe.get("racy") in blocked_values:
            return False

        # These are weaker signals, so only block at the strongest level.
        if safe.get("medical") == "VERY_LIKELY":
            return False

        if safe.get("spoof") == "VERY_LIKELY":
            return False

        return True

    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, Exception):
        # Production-safe behaviour: if AI verification fails, do not auto-approve.
        return False
    finally:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass


def should_auto_approve_upload(uploaded_file) -> bool:
    """
    Combined moderation decision.

    True  -> approve instantly
    False -> hold for admin review as pending
    """
    if not _passes_basic_image_checks(uploaded_file):
        return False

    if not _google_vision_safesearch_allows(uploaded_file):
        return False

    return True


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