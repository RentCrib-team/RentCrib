from propertylist_app.services import city_image_user_selected_pexels as selected
from propertylist_app.services.city_image_autofill import CITY_MATCH_ALIASES, PEXELS_SEARCH_URL


EXPECTED_PUBLIC_CITY_PHOTO_IDS = {
    "southampton": "19916599",
    "london": "30680312",
    "birmingham": "33175822",
    "manchester": "34760018",
    "liverpool": "12953548",
    "leeds": "16666012",
    "bristol": "24880409",
    "sheffield": "12698033",
    "newcastle-upon-tyne": "34175710",
    "cambridge": "32783000",
    "oxford": "18283322",
    "bath": "32038429",
    "york": "35701057",
    "nottingham": "37228472",
    "leicester": "30890693",
    "coventry": "35751281",
    "exeter": "18218243",
    "lancaster": "36093695",
    "brighton-hove": "9161809",
    "wrexham": "35714326",
}


class FakeImage:
    def __init__(self, name):
        self.name = name

    def __bool__(self):
        return bool(self.name)


class FakeCity:
    def __init__(self, *, pk, name, slug):
        self.pk = pk
        self.name = name
        self.slug = slug
        self.image = FakeImage(f"city_images/{slug}.jpg")
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


def test_public_city_vetted_photo_map_is_exactly_twenty_and_unique():
    assert selected.USER_SELECTED_PEXELS_PHOTO_IDS == EXPECTED_PUBLIC_CITY_PHOTO_IDS
    assert len(selected.USER_SELECTED_PEXELS_PHOTO_IDS) == 20
    assert len(set(selected.USER_SELECTED_PEXELS_PHOTO_IDS.values())) == 20


def test_user_selected_service_uses_exact_southampton_and_brighton_photos_and_global_uniqueness(monkeypatch):
    southampton = FakeCity(pk=1, name="Southampton", slug="southampton")
    brighton = FakeCity(pk=2, name="Brighton & Hove", slug="brighton-hove")
    london = FakeCity(pk=3, name="London", slug="london")
    FakeCityModel.objects = FakeManager([southampton, brighton, london])

    monkeypatch.setattr(
        selected,
        "_city_image_records",
        lambda cities: [
            {"city": southampton, "photo_id": "old-southampton", "content_sha256": "hash-s", "is_night": True},
            {"city": brighton, "photo_id": "old-brighton", "content_sha256": "hash-b", "is_night": False},
            {"city": london, "photo_id": "used-london", "content_sha256": "hash-l", "is_night": False},
        ],
    )

    photos = {
        "19916599": {
            "id": 19916599,
            "alt": "A sleek modern office building illuminated at night in Southampton city center",
            "url": "https://www.pexels.com/photo/carnival-house-in-southampton-in-england-19916599/",
            "src": {"large": "https://images.pexels.com/southampton.jpg"},
        },
        "9161809": {
            "id": 9161809,
            "alt": "Brighton Marina with numerous boats docked on a sunny day",
            "url": "https://www.pexels.com/photo/boats-on-the-dock-9161809/",
            "src": {"large": "https://images.pexels.com/brighton.jpg"},
        },
    }

    def fake_get(url, **kwargs):
        photo_id = url.rsplit("/", 1)[-1]
        return FakeResponse(photos[photo_id])

    calls = []

    def fake_replace(city_id, **kwargs):
        injected = kwargs["http_get"](PEXELS_SEARCH_URL).json()["photos"][0]
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
            "provider_photo_id": str(injected["id"]),
            "content_sha256": f"new-{city_id}",
        }

    assert "brighton-hove" not in CITY_MATCH_ALIASES

    result = selected.apply_user_selected_pexels_city_images(
        slugs=["southampton", "brighton-hove"],
        city_model=FakeCityModel,
        catalogue=_catalogue(southampton, brighton, london),
        replace_image=fake_replace,
        http_get=fake_get,
        api_key="test-key",
    )

    assert result["status"] == "ok"
    assert result["failed"] == []
    assert result["skipped"] == []
    assert [item["provider_photo_id"] for item in result["replaced"]] == ["19916599", "9161809"]
    assert calls[0] == {
        "city_id": 1,
        "photo_id": "19916599",
        "preferred_time": "night",
        "used_photo_ids": {"old-southampton", "old-brighton", "used-london"},
        "used_hashes": {"hash-s", "hash-b", "hash-l"},
    }
    assert calls[1]["city_id"] == 2
    assert calls[1]["photo_id"] == "9161809"
    assert "19916599" in calls[1]["used_photo_ids"]
    assert "new-1" in calls[1]["used_hashes"]
    assert "brighton-hove" not in CITY_MATCH_ALIASES


def test_user_selected_service_rejects_wrong_live_metadata_without_replacing(monkeypatch):
    southampton = FakeCity(pk=1, name="Southampton", slug="southampton")
    FakeCityModel.objects = FakeManager([southampton])
    monkeypatch.setattr(
        selected,
        "_city_image_records",
        lambda cities: [
            {"city": southampton, "photo_id": "old", "content_sha256": "hash", "is_night": False}
        ],
    )

    def fake_get(url, **kwargs):
        return FakeResponse(
            {
                "id": 19916599,
                "alt": "London pub at night",
                "url": "https://www.pexels.com/photo/london-pub-19916599/",
                "src": {"large": "https://images.pexels.com/london.jpg"},
            }
        )

    called = False

    def fake_replace(*args, **kwargs):
        nonlocal called
        called = True
        return {"status": "imported"}

    result = selected.apply_user_selected_pexels_city_images(
        slugs=["southampton"],
        city_model=FakeCityModel,
        catalogue=_catalogue(southampton),
        replace_image=fake_replace,
        http_get=fake_get,
        api_key="test-key",
    )

    assert result["status"] == "partial"
    assert result["replaced"] == []
    assert called is False
    assert result["failed"] == [
        {
            "city_id": 1,
            "city": "Southampton",
            "error": "Selected Pexels photo metadata does not match the target city",
        }
    ]
