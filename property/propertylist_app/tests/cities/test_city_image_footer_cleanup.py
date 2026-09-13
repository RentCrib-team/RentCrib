from io import BytesIO

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile

from propertylist_app.services.city_images import remove_embedded_city_image_footer


def _upload(*, footer):
    image = Image.new("RGB", (1600, 900), "white")
    if footer:
        for y in range(866, 900):
            for x in range(1600):
                image.putpixel((x, y), (0, 0, 0))
    handle = BytesIO()
    image.save(handle, "JPEG")
    return SimpleUploadedFile("city.jpg", handle.getvalue(), content_type="image/jpeg")


def test_legacy_black_city_image_footer_is_removed_without_changing_card_size():
    cleaned = remove_embedded_city_image_footer(_upload(footer=True))

    assert cleaned is not None
    with Image.open(cleaned) as image:
        assert image.size == (1600, 900)
        assert image.convert("RGB").getpixel((1, 899)) != (0, 0, 0)


def test_city_image_without_legacy_black_footer_is_not_changed():
    assert remove_embedded_city_image_footer(_upload(footer=False)) is None
