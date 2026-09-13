from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from propertylist_app.services.city_image_import import (
    CityImageImportError,
    import_city_images,
)


DEFAULT_MANIFEST = Path(settings.BASE_DIR) / "propertylist_app" / "data" / "city_image_manifest.csv"
DEFAULT_ASSETS_ROOT = Path(settings.BASE_DIR) / "city_image_assets"


class Command(BaseCommand):
    help = (
        "Validate or import approved city-card images from the controlled city "
        "image manifest. Defaults to dry-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--manifest",
            default=str(DEFAULT_MANIFEST),
            help="CSV manifest containing city image provenance and approval metadata.",
        )
        parser.add_argument(
            "--assets-root",
            default=str(DEFAULT_ASSETS_ROOT),
            help="Directory containing the approved image files referenced by the manifest.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist validated images to the configured Django media storage.",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Replace existing city images. Without this flag, existing images are skipped.",
        )
        parser.add_argument(
            "--slug",
            action="append",
            dest="slugs",
            default=[],
            help="Import only a specific city slug. Repeat for multiple cities.",
        )

    def handle(self, *args, **options):
        try:
            result = import_city_images(
                manifest_path=options["manifest"],
                assets_root=options["assets_root"],
                apply=bool(options["apply"]),
                replace=bool(options["replace"]),
                only_slugs=options.get("slugs") or [],
            )
        except CityImageImportError as exc:
            raise CommandError(str(exc)) from exc

        mode = "APPLY" if options["apply"] else "DRY RUN"
        self.stdout.write(self.style.MIGRATE_HEADING(f"City image import: {mode}"))
        self.stdout.write(f"Rows considered: {result['rows']}")
        self.stdout.write(f"Pending/no file: {result['pending']}")
        self.stdout.write(f"Existing/skipped: {result['existing']}")
        self.stdout.write(f"Validated: {result['validated']}")
        self.stdout.write(f"Imported: {result['imported']}")
        self.stdout.write(f"Errors: {len(result['errors'])}")

        if result["errors"]:
            for error in result["errors"]:
                self.stderr.write(
                    f"row {error['row']} [{error['slug'] or 'no-slug'}]: {error['error']}"
                )
            raise CommandError("City image import failed validation. No failed row was imported.")

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "Dry-run only. No city images were written. Re-run with --apply after review."
                )
            )
