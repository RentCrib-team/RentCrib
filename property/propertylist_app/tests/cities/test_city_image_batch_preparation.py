import csv
from io import BytesIO

from django.core.management import call_command
from PIL import Image

from propertylist_app.management.commands import prepare_city_image_batch


class FakeResponse:
    def __init__(self, *, payload=None, content=b"", status_code=200):
        self._payload = payload
        self.content = content
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _jpeg_bytes():
    handle = BytesIO()
    Image.new("RGB", (1800, 1200), "white").save(handle, "JPEG")
    return handle.getvalue()


def _write_manifest(path):
    fieldnames = [
        "slug",
        "filename",
        "image_alt",
        "source_type",
        "source_name",
        "source_url",
        "license_name",
        "license_url",
        "credit",
        "rights_confirmed",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({"slug": "southampton", "image_alt": "Southampton"})
        writer.writerow({"slug": "london", "image_alt": "London"})


def test_city_image_batch_preparation_and_finalize_are_local_and_importer_compatible(
    tmp_path,
    monkeypatch,
):
    manifest = tmp_path / "manifest.csv"
    output_dir = tmp_path / "batch"
    _write_manifest(manifest)
    monkeypatch.setenv("PEXELS_API_KEY", "test-key")

    image_bytes = _jpeg_bytes()

    def fake_get(url, **kwargs):
        if url == prepare_city_image_batch.PEXELS_SEARCH_URL:
            assert kwargs["headers"] == {"Authorization": "test-key"}
            assert kwargs["params"]["query"] == "London United Kingdom city skyline"
            assert kwargs["params"]["per_page"] == 2
            return FakeResponse(
                payload={
                    "photos": [
                        {
                            "id": 101,
                            "photographer": "Photographer One",
                            "url": "https://www.pexels.com/photo/london-one/",
                            "src": {"large2x": "https://images.example/one.jpg"},
                        },
                        {
                            "id": 102,
                            "photographer": "Photographer Two",
                            "url": "https://www.pexels.com/photo/london-two/",
                            "src": {"large2x": "https://images.example/two.jpg"},
                        },
                    ]
                }
            )
        if url in {
            "https://images.example/one.jpg",
            "https://images.example/two.jpg",
        }:
            return FakeResponse(content=image_bytes)
        raise AssertionError(f"unexpected request: {url}")

    monkeypatch.setattr(prepare_city_image_batch.requests, "get", fake_get)

    call_command(
        "prepare_city_image_batch",
        "--manifest",
        str(manifest),
        "--output-dir",
        str(output_dir),
        "--skip-slug",
        "southampton",
        "--per-city",
        "2",
    )

    first = output_dir / "candidates" / "london" / "1.jpg"
    second = output_dir / "candidates" / "london" / "2.jpg"
    assert first.is_file()
    assert second.is_file()
    with Image.open(first) as prepared:
        assert prepared.size == (1600, 900)

    with (output_dir / "candidates.csv").open(
        "r",
        encoding="utf-8",
        newline="",
    ) as handle:
        candidates = list(csv.DictReader(handle))
    assert [row["source_url"] for row in candidates] == [
        "https://www.pexels.com/photo/london-one/",
        "https://www.pexels.com/photo/london-two/",
    ]

    review = (output_dir / "review.html").read_text(encoding="utf-8")
    assert "London" in review
    assert "Export selections CSV" in review
    assert "city_image_selections.csv" in review
    assert "Southampton" not in review

    selections = tmp_path / "selections.csv"
    selections.write_text(
        "slug,candidate_number\nlondon,2\n",
        encoding="utf-8",
    )

    def no_network(*args, **kwargs):
        raise AssertionError("finalize mode must not make network requests")

    monkeypatch.setattr(prepare_city_image_batch.requests, "get", no_network)
    call_command(
        "prepare_city_image_batch",
        "--manifest",
        str(manifest),
        "--output-dir",
        str(output_dir),
        "--finalize",
        str(selections),
    )

    approved_manifest = output_dir / "approved" / "city_image_manifest.csv"
    approved_asset = output_dir / "approved" / "assets" / "london.jpg"
    assert approved_asset.is_file()

    with approved_manifest.open("r", encoding="utf-8", newline="") as handle:
        rows = {row["slug"]: row for row in csv.DictReader(handle)}

    assert rows["southampton"]["filename"] == ""
    assert rows["london"]["filename"] == "london.jpg"
    assert rows["london"]["source_type"] == "licensed_stock"
    assert rows["london"]["source_name"] == "Photographer Two / Pexels"
    assert rows["london"]["source_url"] == "https://www.pexels.com/photo/london-two/"
    assert rows["london"]["license_name"] == "Pexels License"
    assert rows["london"]["license_url"] == "https://www.pexels.com/license/"
    assert rows["london"]["credit"] == "Photo by Photographer Two on Pexels"
    assert rows["london"]["rights_confirmed"] == "yes"
