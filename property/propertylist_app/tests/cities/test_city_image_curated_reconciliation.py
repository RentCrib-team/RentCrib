from propertylist_app.services import city_image_curated_reconciliation as curated
from propertylist_app.services.city_image_autofill import PEXELS_SEARCH_URL


class FakeImage:
    def __init__(self, name):
        self.name = name

    def __bool__(self):
        return bool(self.name)


class FakeCity:
    def __init__(self, *, pk, name, slug, image_name="city_images/current.jpg"):
        self.pk = pk
        self.name = name
        self.slug = slug
        self.image = FakeImage(image_name)
        self.image_is_approved = True
        self.is_active = True


class FakeQuerySet(list):
    def filter(self, **kwargs):
        result = self
        for key, value in kwargs.items():
            if key in {"is_active", "image_is_approved"}:
                result = FakeQuerySet([item for item in result if getattr(item, key) == value])
        return result

    def exclude(self, **kwargs):
        result = self
        for key, value in kwargs.items():
            if key == "image":
                result = FakeQuerySet([item for item in result if item.image.name != value])
            elif key == "image__isnull" and value is True:
                result = FakeQuerySet([item for item in result if item.image is not None])
        return result

    def order_by(self, *args):
        return self


class FakeManager:
    def __init__(self, cities):
        self._cities = FakeQuerySet(cities)

    def filter(self, **kwargs):
        return self._cities.filter(**kwargs)


class FakeCityModel:
    objects = None


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _catalogue(*cities):
    return tuple(
        {
            "name": city.name,
            "display_name": city.name,
            "slug": city.slug,
            "nation": "England",
        }
        for city in cities
    )


def test_curated_reconciliation_injects_exact_verified_photo_and_preserves_global_uniqueness(monkeypatch):
    nottingham = FakeCity(pk=1, name="Nottingham", slug="nottingham")
    london = FakeCity(pk=2, name="London", slug="london")
    FakeCityModel.objects = FakeManager([nottingham, london])

    monkeypatch.setattr(
        curated,
        "_city_image_records",
        lambda cities: [
            {
                "city": nottingham,
                "photo_id": "old-nottingham",
                "content_sha256": "hash-nottingham",
                "is_night": False,
            },
            {
                "city": london,
                "photo_id": "used-by-london",
                "content_sha256": "hash-london",
                "is_night": True,
            },
        ],
    )

    def fake_get(url, **kwargs):
        assert url.endswith("/29383712")
        return FakeResponse(
            {
                "id": 29383712,
                "alt": "Aerial View of Nottingham Cityscape and River Trent",
                "url": "https://www.pexels.com/photo/aerial-view-of-nottingham-cityscape-and-river-trent-29383712/",
                "src": {"large": "https://images.pexels.com/nottingham.jpg"},
            }
        )

    calls = []

    def fake_replace(city_id, **kwargs):
        search_response = kwargs["http_get"](PEXELS_SEARCH_URL)
        injected = search_response.json()["photos"][0]
        calls.append(
            {
                "city_id": city_id,
                "photo_id": str(injected["id"]),
                "preferred_time": kwargs["preferred_time"],
                "used_photo_ids": set(kwargs["used_photo_ids"]),
                "used_hashes": set(kwargs["used_hashes"]),
            }
        )
        return {
            "status": "imported",
            "provider_photo_id": "29383712",
            "content_sha256": "new-nottingham-hash",
        }

    progress = []
    result = curated.reconcile_curated_city_images(
        slugs=["nottingham"],
        city_model=FakeCityModel,
        catalogue=_catalogue(nottingham, london),
        replace_image=fake_replace,
        http_get=fake_get,
        api_key="test-key",
        progress=progress.append,
    )

    assert result["status"] == "ok"
    assert result["failed"] == []
    assert result["skipped"] == []
    assert result["replaced"] == [
        {
            "city_id": 1,
            "city": "Nottingham",
            "provider_photo_id": "29383712",
            "time_preference": "day",
        }
    ]
    assert calls == [
        {
            "city_id": 1,
            "photo_id": "29383712",
            "preferred_time": "day",
            "used_photo_ids": {"old-nottingham", "used-by-london"},
            "used_hashes": {"hash-nottingham", "hash-london"},
        }
    ]
    assert progress == [
        "Reconciling 1 curated city images",
        "[1/1] Nottingham: replaced with curated Pexels photo 29383712",
    ]


def test_curated_reconciliation_refuses_exact_photo_when_live_metadata_does_not_match_city(monkeypatch):
    nottingham = FakeCity(pk=1, name="Nottingham", slug="nottingham")
    FakeCityModel.objects = FakeManager([nottingham])

    monkeypatch.setattr(
        curated,
        "_city_image_records",
        lambda cities: [
            {
                "city": nottingham,
                "photo_id": "old-nottingham",
                "content_sha256": "hash-nottingham",
                "is_night": False,
            }
        ],
    )

    def fake_get(url, **kwargs):
        return FakeResponse(
            {
                "id": 29383712,
                "alt": "Aerial view of Liverpool skyline",
                "url": "https://www.pexels.com/photo/liverpool-skyline-29383712/",
                "src": {"large": "https://images.pexels.com/liverpool.jpg"},
            }
        )

    replacement_called = False

    def fake_replace(city_id, **kwargs):
        nonlocal replacement_called
        replacement_called = True
        return {"status": "imported"}

    result = curated.reconcile_curated_city_images(
        slugs=["nottingham"],
        city_model=FakeCityModel,
        catalogue=_catalogue(nottingham),
        replace_image=fake_replace,
        http_get=fake_get,
        api_key="test-key",
    )

    assert result["status"] == "partial"
    assert result["replaced"] == []
    assert replacement_called is False
    assert result["failed"] == [
        {
            "city_id": 1,
            "city": "Nottingham",
            "error": "Curated Pexels photo metadata does not match the target city",
        }
    ]


def test_curated_reconciliation_does_not_touch_unmapped_city(monkeypatch):
    london = FakeCity(pk=2, name="London", slug="london")
    FakeCityModel.objects = FakeManager([london])
    monkeypatch.setattr(curated, "_city_image_records", lambda cities: [])

    result = curated.reconcile_curated_city_images(
        slugs=["london"],
        city_model=FakeCityModel,
        catalogue=_catalogue(london),
        replace_image=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not replace")),
        http_get=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not fetch")),
        api_key="test-key",
    )

    assert result["status"] == "ok"
    assert result["replaced"] == []
    assert result["failed"] == []
    assert result["skipped"] == [
        {"city_id": 2, "city": "London", "reason": "no curated photo"}
    ]
