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
