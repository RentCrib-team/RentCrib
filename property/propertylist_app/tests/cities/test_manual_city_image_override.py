import base64
import json
from contextlib import nullcontext
from io import BytesIO

from propertylist_app.services import manual_city_image_override as manual


class MemoryStorage:
    def __init__(self):
        self.files = {}

    def exists(self, name):
        return name in self.files

    def open(self, name, mode="rb"):
        return BytesIO(self.files[name])

    def save(self, name, content):
        payload = content.read()
        self.files[name] = payload
        return name

    def delete(self, name):
        self.files.pop(name, None)


class FakeImage:
    def __init__(self, storage, name):
        self.storage = storage
        self.name = name

    def save(self, name, content, save=False):
        self.name = self.storage.save(f"city_images/{name}", content)

    def __bool__(self):
        return bool(self.name)


class FakeCity:
    def __init__(self, *, pk, name, slug, storage, fail_save=False):
        self.pk = pk
        self.name = name
        self.slug = slug
        self.image = FakeImage(storage, f"city_images/old-{slug}.jpg")
        self.image_is_approved = True
        self.image_alt = "old alt"
        self.fail_save = fail_save
        self.saved_update_fields = None

    def save(self, update_fields=None):
        if self.fail_save:
            raise RuntimeError("database save failed")
        self.saved_update_fields = list(update_fields or [])


class FakeQuerySet:
    def __init__(self, cities):
        self.cities = cities

    def select_for_update(self):
        return self

    def filter(self, **kwargs):
        slug = kwargs.get("slug")
        return FakeQuerySet([city for city in self.cities if city.slug == slug])

    def first(self):
        return self.cities[0] if self.cities else None


class FakeManager(FakeQuerySet):
    pass


class FakeCityModel:
    objects = None


def _write_parts(root, filenames, payload):
    encoded = base64.b64encode(payload).decode("ascii")
    width = max(1, len(encoded) // len(filenames))
    start = 0
    for index, filename in enumerate(filenames):
        end = len(encoded) if index == len(filenames) - 1 else start + width
        (root / filename).write_text(encoded[start:end], encoding="ascii")
        start = end


def test_manual_city_override_applies_only_selected_images_and_records_provenance(tmp_path):
    storage = MemoryStorage()
    southampton = FakeCity(pk=1, name="Southampton", slug="southampton", storage=storage)
    brighton = FakeCity(pk=2, name="Brighton & Hove", slug="brighton-hove", storage=storage)
    london = FakeCity(pk=3, name="London", slug="london", storage=storage)
    FakeCityModel.objects = FakeManager([southampton, brighton, london])

    southampton_bytes = b"southampton-user-selected-image"
    brighton_bytes = b"brighton-user-selected-image"
    _write_parts(
        tmp_path,
        manual.MANUAL_CITY_IMAGE_ASSETS["southampton"]["parts"],
        southampton_bytes,
    )
    _write_parts(
        tmp_path,
        manual.MANUAL_CITY_IMAGE_ASSETS["brighton-hove"]["parts"],
        brighton_bytes,
    )

    result = manual.apply_manual_city_images(
        slugs=["southampton", "brighton-hove"],
        city_model=FakeCityModel,
        asset_root=tmp_path,
        atomic_context=nullcontext,
        now_func=lambda: __import__("datetime").datetime(2026, 9, 14, 10, 0, 0),
    )

    assert result["status"] == "ok"
    assert result["failed"] == []
    assert result["skipped"] == []
    assert [item["slug"] for item in result["replaced"]] == ["brighton-hove", "southampton"]

    assert storage.files[brighton.image.name] == brighton_bytes
    assert storage.files[southampton.image.name] == southampton_bytes
    assert london.image.name == "city_images/old-london.jpg"

    assert southampton.image_is_approved is True
    assert southampton.image_alt == "Southampton city view"
    assert brighton.image_is_approved is True
    assert brighton.image_alt == "Brighton & Hove city view"

    for city in (southampton, brighton):
        provenance_name = f"city_image_provenance/{city.slug}.json"
        provenance = json.loads(storage.files[provenance_name].decode("utf-8"))
        assert provenance["provider"] == "Manual user selection"
        assert provenance["manual_override"] is True
        assert provenance["stored_image"] == city.image.name
        assert provenance["rights_confirmed"] is False


def test_manual_city_override_keeps_old_provenance_when_database_save_fails(tmp_path):
    storage = MemoryStorage()
    city = FakeCity(
        pk=1,
        name="Southampton",
        slug="southampton",
        storage=storage,
        fail_save=True,
    )
    FakeCityModel.objects = FakeManager([city])

    provenance_name = "city_image_provenance/southampton.json"
    old_provenance = b'{"provider":"Pexels","provider_photo_id":"old"}'
    storage.files[provenance_name] = old_provenance

    _write_parts(
        tmp_path,
        manual.MANUAL_CITY_IMAGE_ASSETS["southampton"]["parts"],
        b"replacement-image",
    )

    result = manual.apply_manual_city_images(
        slugs=["southampton"],
        city_model=FakeCityModel,
        asset_root=tmp_path,
        atomic_context=nullcontext,
    )

    assert result["status"] == "partial"
    assert result["replaced"] == []
    assert result["failed"] == [{"slug": "southampton", "error": "database save failed"}]
    assert storage.files[provenance_name] == old_provenance
    assert "city_images/southampton-user-selected.jpg" not in storage.files
