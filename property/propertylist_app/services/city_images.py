from PIL import Image
from django.core.exceptions import ValidationError
from django.templatetags.static import static

from propertylist_app.services.image import compress_listing_upload
from propertylist_app.validators.images import validate_listing_photos


CITY_IMAGE_MAX_MB = 5
CITY_IMAGE_MIN_WIDTH = 640
CITY_IMAGE_MIN_HEIGHT = 360
CITY_IMAGE_MIN_ASPECT_RATIO = 1.20
CITY_IMAGE_MAX_ASPECT_RATIO = 2.50
CITY_IMAGE_FALLBACK_STATIC_PATH = "propertylist_app/city-card-fallback.svg"


def prepare_city_image(uploaded_file):
    """Validate and optimise an admin-uploaded city-card image.

    City images share RentCrib's existing image-content safety checks, then add
    a city-card-specific minimum size and landscape-friendly aspect ratio. The
    output is passed through the existing WebP optimisation pipeline whenever
    that reduces the file size.
    """

    if uploaded_file is None:
        return None

    validate_listing_photos(
        [uploaded_file],
        max_count=1,
        max_mb=CITY_IMAGE_MAX_MB,
    )

    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as image:
            width, height = image.size

        if width < CITY_IMAGE_MIN_WIDTH or height < CITY_IMAGE_MIN_HEIGHT:
            raise ValidationError(
                "City image is too small. Minimum dimensions are "
                f"{CITY_IMAGE_MIN_WIDTH}x{CITY_IMAGE_MIN_HEIGHT}px."
            )

        ratio = width / float(height)
        if not CITY_IMAGE_MIN_ASPECT_RATIO <= ratio <= CITY_IMAGE_MAX_ASPECT_RATIO:
            raise ValidationError(
                "City image must be landscape-oriented with an aspect ratio "
                f"between {CITY_IMAGE_MIN_ASPECT_RATIO:.2f} and "
                f"{CITY_IMAGE_MAX_ASPECT_RATIO:.2f}."
            )
    finally:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass

    return compress_listing_upload(uploaded_file)


def city_has_uploaded_image(city):
    return bool(getattr(city, "image", None))


def city_image_url(city, *, request=None):
    """Return a usable city-card image URL, falling back to RentCrib static art."""

    image = getattr(city, "image", None)
    if image:
        try:
            url = image.url
        except (AttributeError, ValueError):
            url = ""
    else:
        url = ""

    if not url:
        url = static(CITY_IMAGE_FALLBACK_STATIC_PATH)

    if request is not None and not url.startswith(("http://", "https://")):
        return request.build_absolute_uri(url)

    return url
