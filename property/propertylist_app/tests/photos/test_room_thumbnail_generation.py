from io import BytesIO

from PIL import Image

from propertylist_app.services.image import build_listing_thumbnail


def test_listing_thumbnail_is_small_webp():
    source = BytesIO()
    Image.new("RGB", (2400, 1600), "navy").save(source, format="JPEG")
    source.name = "large-room.jpg"
    source.seek(0)

    thumbnail = build_listing_thumbnail(source)

    assert thumbnail.name.endswith("-card.webp")
    with Image.open(thumbnail) as image:
        assert image.format == "WEBP"
        assert max(image.size) <= 640
