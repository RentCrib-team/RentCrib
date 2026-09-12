import csv
import html
import os
import shutil
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageOps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


DEFAULT_MANIFEST = (
    Path(settings.BASE_DIR) / "propertylist_app" / "data" / "city_image_manifest.csv"
)
DEFAULT_OUTPUT_DIR = Path(settings.BASE_DIR) / "city_image_batch"
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
PEXELS_LICENSE_URL = "https://www.pexels.com/license/"
MANIFEST_COLUMNS = [
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
CANDIDATE_COLUMNS = [
    "slug",
    "city_name",
    "candidate_number",
    "filename",
    "query",
    "pexels_id",
    "photographer",
    "source_url",
]
QUERY_OVERRIDES = {
    "bangor-northern-ireland": "Bangor Northern Ireland United Kingdom city",
    "bangor-wales": "Bangor Wales United Kingdom city",
    "newport": "Newport Wales United Kingdom city",
    "st-asaph": "St Asaph Wales United Kingdom city",
    "st-davids": "St Davids Wales United Kingdom city",
    "swansea": "Swansea Wales United Kingdom city",
    "wrexham": "Wrexham Wales United Kingdom city",
    "perth": "Perth Scotland United Kingdom city",
}


def _clean(value):
    return str(value or "").strip()


def _read_csv(path, required_columns):
    path = Path(path)
    if not path.is_file():
        raise CommandError(f"file does not exist: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        missing = [column for column in required_columns if column not in fields]
        if missing:
            raise CommandError(
                "CSV is missing columns: " + ", ".join(sorted(missing))
            )
        return list(reader), fields


def _write_csv(path, rows, fieldnames):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _query_overrides(values):
    overrides = {}
    for raw in values or []:
        if "=" not in raw:
            raise CommandError("--query must use slug=search terms")
        slug, query = raw.split("=", 1)
        slug = _clean(slug).lower()
        query = _clean(query)
        if not slug or not query:
            raise CommandError("--query must use non-empty slug=search terms")
        overrides[slug] = query
    return overrides


def _query_for(row, overrides):
    slug = _clean(row.get("slug")).lower()
    city_name = _clean(row.get("image_alt")) or slug.replace("-", " ").title()
    return (
        overrides.get(slug)
        or QUERY_OVERRIDES.get(slug)
        or f"{city_name} United Kingdom city skyline"
    )


def _download_url(photo):
    sources = photo.get("src") or {}
    return (
        sources.get("large2x")
        or sources.get("large")
        or sources.get("landscape")
        or sources.get("medium")
    )


def _save_candidate(content, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(BytesIO(content)) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            width, height = image.size
            if width < 640 or height < 360:
                raise ValueError(
                    f"source image is too small ({width}x{height}); minimum is 640x360"
                )
            image = ImageOps.fit(
                image,
                (1600, 900),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            image.save(
                path,
                "JPEG",
                quality=88,
                optimize=True,
                progressive=True,
            )
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _load_existing_candidates(path):
    path = Path(path)
    if not path.is_file():
        return []
    rows, _ = _read_csv(path, CANDIDATE_COLUMNS)
    return rows


def _candidate_is_usable(output_dir, row):
    filename = _clean(row.get("filename"))
    return bool(filename and (Path(output_dir) / filename).is_file())


def _review_html(candidate_rows):
    grouped = {}
    for row in candidate_rows:
        grouped.setdefault(row["slug"], []).append(row)

    sections = []
    for slug in sorted(grouped):
        rows = sorted(
            grouped[slug],
            key=lambda item: int(item["candidate_number"]),
        )
        city_name = html.escape(rows[0]["city_name"])
        cards = []
        for index, row in enumerate(rows):
            number = html.escape(str(row["candidate_number"]))
            filename = html.escape(row["filename"], quote=True)
            photographer = html.escape(row["photographer"])
            source_url = html.escape(row["source_url"], quote=True)
            checked = " checked" if index == 0 else ""
            cards.append(
                f"""
                <label class="candidate">
                  <input type="radio" name="{html.escape(slug)}"
                         value="{number}"{checked}>
                  <img src="{filename}" alt="{city_name} candidate {number}">
                  <span>Candidate {number}</span>
                  <small>{photographer}</small>
                  <a href="{source_url}" target="_blank" rel="noreferrer">Source</a>
                </label>
                """
            )

        sections.append(
            f"""
            <section class="city" data-city="{html.escape(slug)}">
              <h2>{city_name}</h2>
              <div class="candidates">{''.join(cards)}</div>
            </section>
            """
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>RentCrib city image review</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; color: #222; }}
.notice {{ max-width: 1000px; line-height: 1.5; }}
.city {{ margin: 30px 0; padding-top: 18px; border-top: 1px solid #ddd; }}
.candidates {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }}
.candidate {{ display: grid; gap: 8px; cursor: pointer; }}
.candidate img {{ width: 100%; aspect-ratio: 16/9; object-fit: cover; border-radius: 8px; }}
.candidate:has(input:checked) img {{ outline: 4px solid #111; outline-offset: 2px; }}
small, a {{ font-size: 12px; }}
button {{ position: sticky; top: 12px; padding: 12px 18px; font-weight: 700; }}
@media (max-width: 800px) {{ .candidates {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<h1>RentCrib city image review</h1>
<div class="notice">
<p>Candidate 1 is preselected for every city. Change only cities where another
candidate is more accurate. Approve only images that clearly represent the
named city and do not introduce problematic identifiable people, logos, or
third-party branding.</p>
<p>Exporting the selections is the human approval step. The finalize command
will record the selected Pexels source and Pexels licence and mark
<code>rights_confirmed=yes</code>.</p>
</div>
<button type="button" onclick="exportSelections()">Export selections CSV</button>
{''.join(sections)}
<script>
function exportSelections() {{
  const lines = ["slug,candidate_number"];
  for (const section of document.querySelectorAll("[data-city]")) {{
    const selected = section.querySelector("input[type=radio]:checked");
    if (selected) lines.push(section.dataset.city + "," + selected.value);
  }}
  const blob = new Blob([lines.join("\\n") + "\\n"], {{type: "text/csv"}});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "city_image_selections.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}}
</script>
</body>
</html>
"""


def _prepare(
    *,
    manifest_path,
    output_dir,
    per_city,
    skip_slugs,
    custom_queries,
    refresh_slugs,
    stdout,
):
    if per_city < 1 or per_city > 5:
        raise CommandError("--per-city must be between 1 and 5")

    api_key = _clean(os.environ.get("PEXELS_API_KEY"))
    if not api_key:
        raise CommandError("PEXELS_API_KEY is not set")

    manifest_rows, _ = _read_csv(manifest_path, MANIFEST_COLUMNS)
    output_dir = Path(output_dir)
    candidates_path = output_dir / "candidates.csv"
    review_path = output_dir / "review.html"
    output_dir.mkdir(parents=True, exist_ok=True)

    existing = _load_existing_candidates(candidates_path)
    refresh_slugs = {slug.lower() for slug in refresh_slugs}
    if refresh_slugs:
        existing = [
            row
            for row in existing
            if _clean(row.get("slug")).lower() not in refresh_slugs
        ]
        for slug in refresh_slugs:
            shutil.rmtree(output_dir / "candidates" / slug, ignore_errors=True)
        _write_csv(candidates_path, existing, CANDIDATE_COLUMNS)

    skip_slugs = {slug.lower() for slug in skip_slugs}
    custom_queries = _query_overrides(custom_queries)
    failures = []

    for manifest_row in manifest_rows:
        slug = _clean(manifest_row.get("slug")).lower()
        if not slug or slug in skip_slugs:
            continue
        if _clean(manifest_row.get("filename")):
            continue

        usable = [
            row
            for row in existing
            if row.get("slug") == slug and _candidate_is_usable(output_dir, row)
        ]
        if len(usable) >= per_city:
            stdout.write(f"SKIP {slug}: {len(usable)} candidates already prepared")
            continue

        existing = [row for row in existing if row.get("slug") != slug]
        shutil.rmtree(output_dir / "candidates" / slug, ignore_errors=True)

        query = _query_for(manifest_row, custom_queries)
        try:
            response = requests.get(
                PEXELS_SEARCH_URL,
                headers={"Authorization": api_key},
                params={
                    "query": query,
                    "orientation": "landscape",
                    "size": "large",
                    "per_page": per_city,
                    "page": 1,
                },
                timeout=30,
            )
            if response.status_code == 401:
                raise CommandError("Pexels API rejected PEXELS_API_KEY")
            response.raise_for_status()
            photos = (response.json() or {}).get("photos") or []
        except CommandError:
            raise
        except Exception as exc:
            failures.append((slug, f"search failed: {exc}"))
            continue

        prepared = []
        for number, photo in enumerate(photos[:per_city], start=1):
            download_url = _download_url(photo)
            if not download_url:
                continue
            relative_name = f"candidates/{slug}/{number}.jpg"
            destination = output_dir / relative_name
            try:
                image_response = requests.get(download_url, timeout=60)
                image_response.raise_for_status()
                _save_candidate(image_response.content, destination)
            except Exception as exc:
                stdout.write(f"WARN {slug} candidate {number}: {exc}")
                continue

            prepared.append(
                {
                    "slug": slug,
                    "city_name": _clean(manifest_row.get("image_alt"))
                    or slug.replace("-", " ").title(),
                    "candidate_number": str(number),
                    "filename": relative_name,
                    "query": query,
                    "pexels_id": str(photo.get("id") or ""),
                    "photographer": _clean(photo.get("photographer"))
                    or "Unknown photographer",
                    "source_url": _clean(photo.get("url"))
                    or "https://www.pexels.com/",
                }
            )

        if not prepared:
            failures.append((slug, "no usable Pexels candidates were downloaded"))
            continue

        existing.extend(prepared)
        _write_csv(candidates_path, existing, CANDIDATE_COLUMNS)
        stdout.write(f"OK {slug}: {len(prepared)} candidates")

    usable_rows = [
        row for row in existing if _candidate_is_usable(output_dir, row)
    ]
    _write_csv(candidates_path, usable_rows, CANDIDATE_COLUMNS)
    review_path.write_text(_review_html(usable_rows), encoding="utf-8")

    stdout.write(f"Candidates: {len(usable_rows)}")
    stdout.write(f"Candidate manifest: {candidates_path}")
    stdout.write(f"Review file: {review_path}")
    stdout.write(f"Failed cities: {len(failures)}")
    for slug, reason in failures:
        stdout.write(f"FAILED {slug}: {reason}")

    if failures:
        raise CommandError(
            f"City image preparation incomplete: {len(failures)} cities failed. "
            "Prepared candidates were preserved for resume."
        )


def _finalize(*, manifest_path, output_dir, selections_path, stdout):
    manifest_rows, manifest_fields = _read_csv(manifest_path, MANIFEST_COLUMNS)
    output_dir = Path(output_dir)
    candidate_rows, _ = _read_csv(
        output_dir / "candidates.csv",
        CANDIDATE_COLUMNS,
    )
    selection_rows, _ = _read_csv(
        selections_path,
        ["slug", "candidate_number"],
    )

    selections = {}
    for row in selection_rows:
        slug = _clean(row.get("slug")).lower()
        number = _clean(row.get("candidate_number"))
        if not slug or not number:
            raise CommandError("selection rows require slug and candidate_number")
        if slug in selections:
            raise CommandError(f"duplicate selection for {slug}")
        selections[slug] = number

    candidates = {
        (row["slug"], str(row["candidate_number"])): row
        for row in candidate_rows
    }
    approved_root = output_dir / "approved"
    approved_assets = approved_root / "assets"
    approved_manifest = approved_root / "city_image_manifest.csv"
    approved_assets.mkdir(parents=True, exist_ok=True)

    updated = []
    selected_count = 0
    for row in manifest_rows:
        result = dict(row)
        slug = _clean(row.get("slug")).lower()
        number = selections.get(slug)
        if not number:
            updated.append(result)
            continue

        candidate = candidates.get((slug, number))
        if candidate is None:
            raise CommandError(
                f"selected candidate {number} does not exist for {slug}"
            )

        source = output_dir / candidate["filename"]
        if not source.is_file():
            raise CommandError(f"candidate file does not exist: {source}")

        final_name = f"{slug}.jpg"
        shutil.copy2(source, approved_assets / final_name)
        photographer = _clean(candidate.get("photographer")) or "Unknown photographer"

        result.update(
            {
                "filename": final_name,
                "image_alt": _clean(result.get("image_alt"))
                or _clean(candidate.get("city_name"))
                or slug.replace("-", " ").title(),
                "source_type": "licensed_stock",
                "source_name": f"{photographer} / Pexels",
                "source_url": _clean(candidate.get("source_url")),
                "license_name": "Pexels License",
                "license_url": PEXELS_LICENSE_URL,
                "credit": f"Photo by {photographer} on Pexels",
                "rights_confirmed": "yes",
            }
        )
        updated.append(result)
        selected_count += 1

    if selected_count != len(selections):
        manifest_slugs = {
            _clean(row.get("slug")).lower() for row in manifest_rows
        }
        missing = sorted(set(selections) - manifest_slugs)
        raise CommandError(
            "selection contains slugs not present in manifest: " + ", ".join(missing)
        )

    _write_csv(approved_manifest, updated, manifest_fields)
    stdout.write(f"Approved selections: {selected_count}")
    stdout.write(f"Approved manifest: {approved_manifest}")
    stdout.write(f"Approved assets: {approved_assets}")


class Command(BaseCommand):
    help = (
        "Prepare reviewable Pexels city-image candidates locally, then finalize "
        "human-approved selections into the existing city-image importer format."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--manifest",
            default=str(DEFAULT_MANIFEST),
            help="City image manifest to populate.",
        )
        parser.add_argument(
            "--output-dir",
            default=str(DEFAULT_OUTPUT_DIR),
            help="Local working directory for candidates, review, and approved output.",
        )
        parser.add_argument(
            "--per-city",
            type=int,
            default=3,
            help="Number of Pexels candidates per city (1-5).",
        )
        parser.add_argument(
            "--skip-slug",
            action="append",
            default=[],
            help="Skip a city slug during candidate preparation. Repeat as needed.",
        )
        parser.add_argument(
            "--refresh-slug",
            action="append",
            default=[],
            help="Discard and re-fetch candidates for a city slug.",
        )
        parser.add_argument(
            "--query",
            action="append",
            default=[],
            help="Override a city search query using slug=search terms.",
        )
        parser.add_argument(
            "--finalize",
            help=(
                "Selections CSV exported by review.html. When supplied, no network "
                "calls are made and an approved importer package is produced."
            ),
        )

    def handle(self, *args, **options):
        if options.get("finalize"):
            _finalize(
                manifest_path=options["manifest"],
                output_dir=options["output_dir"],
                selections_path=options["finalize"],
                stdout=self.stdout,
            )
            return

        _prepare(
            manifest_path=options["manifest"],
            output_dir=options["output_dir"],
            per_city=options["per_city"],
            skip_slugs=options.get("skip_slug") or [],
            custom_queries=options.get("query") or [],
            refresh_slugs=options.get("refresh_slug") or [],
            stdout=self.stdout,
        )
