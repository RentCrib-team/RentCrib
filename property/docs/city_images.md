# RentCrib city images

City-card images are managed by the backend `City.image` field. Frontend and mobile clients must not hardcode city-photo URLs.

## Public contract

Use `image_url` from `/api/v1/cities/` and `/api/v1/home/` for the card image.

- If a city has an uploaded image, `image_url` points to that managed media asset.
- If no image has been uploaded yet, `image_url` points to RentCrib's bundled fallback artwork.
- `has_image` tells clients/admin whether the city has a real uploaded image or is still using the fallback.
- `image_alt` is the accessibility text.
- The older `image` field remains in the response for compatibility, but new UI should use `image_url`.

## Upload policy

Only Super Admin and Operations Admin can manage city images through the existing city-management API.

Recommended source types:

- RentCrib-owned photography.
- Images created specifically for RentCrib with commercial-use rights.
- Properly licensed stock photography that permits RentCrib's commercial use.
- Public-domain/CC0 material where the source terms have been checked.

Do not hotlink arbitrary images from search engines or third-party websites. Upload the approved asset into RentCrib-managed storage instead.

## Image requirements

- Maximum upload size: 5 MB.
- Minimum dimensions: 640 x 360 px.
- Landscape aspect ratio: 1.20 to 2.50.
- Existing RentCrib image-content validation runs before save.
- Valid uploads are passed through the existing image optimisation/WebP pipeline when beneficial.
- Recommended working size: 1600 x 900 px.

## Storage

The `ImageField` uses Django's default media storage:

- When `USE_S3=true`, this is the configured S3-compatible backend (including Cloudflare R2).
- Otherwise it uses the normal local/Render media storage configuration.

Replacing or clearing a city image removes the superseded storage object after the database update commits, preventing orphaned files.

## Admin workflow

`GET /api/v1/admin/locations/cities/?has_image=false` returns cities still using the fallback. This gives the admin dashboard a clean queue for image completion.

`python manage.py city_image_coverage` provides the same coverage check for operations/QA.

## Controlled bulk population workflow

The initial 76-city rollout uses `propertylist_app/data/city_image_manifest.csv` as the source-control audit manifest. Southampton is intentionally the first row because it is the launch city.

Each populated manifest row must include:

- `slug`: canonical RentCrib city slug.
- `filename`: file relative to the approved assets root.
- `image_alt`: accessibility text.
- `source_type`: one of `rentcrib_owned`, `commissioned`, `licensed_stock`, `public_domain`, `cc0`, `cc_by`, `cc_by_sa`.
- `source_name`: photographer/provider/internal source label.
- `source_url`: required for third-party sources.
- `license_name`: required for third-party sources.
- `license_url`: required for public-domain/Creative Commons sources.
- `credit`: required for CC BY / CC BY-SA sources.
- `rights_confirmed`: must be `yes`, `true`, or `1` before import.

Blank `filename` rows are treated as pending work rather than failures, so the 76-city manifest can be completed incrementally.

The importer is dry-run by default:

```bash
python manage.py import_city_images
```

To validate only Southampton first:

```bash
python manage.py import_city_images --slug southampton
```

After the dry-run is clean, persist Southampton to configured media storage:

```bash
python manage.py import_city_images --slug southampton --apply
```

Then expand to all approved rows:

```bash
python manage.py import_city_images --apply
```

Existing city images are skipped by default. Replacing an already-managed image requires the explicit `--replace` flag.

The importer never downloads `source_url`. That URL is provenance evidence only. The approved binary must already exist under the configured assets root, which prevents arbitrary remote image fetching and hotlinking.

The default staging directory is `property/city_image_assets/`, but operations can provide a private directory instead:

```bash
python manage.py import_city_images \
  --assets-root /secure/approved-city-images \
  --manifest /secure/city_image_manifest.csv \
  --apply
```

After each batch, run:

```bash
python manage.py city_image_coverage
```

to verify which cities still use the fallback.
