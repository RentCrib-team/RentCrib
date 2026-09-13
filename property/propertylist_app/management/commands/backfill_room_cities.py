from django.core.management.base import BaseCommand

from propertylist_app.services.city_assignment import backfill_room_cities


class Command(BaseCommand):
    help = (
        "Safely map legacy rooms with no canonical city. Defaults to dry-run; "
        "pass --apply to persist unambiguous matches."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist safe room-to-city matches.",
        )

    def handle(self, *args, **options):
        apply_changes = bool(options.get("apply"))
        result = backfill_room_cities(apply=apply_changes)

        mode = "APPLY" if apply_changes else "DRY RUN"
        self.stdout.write(self.style.MIGRATE_HEADING(f"Room city backfill: {mode}"))
        self.stdout.write(f"Scanned: {result['scanned']}")
        self.stdout.write(f"Matched: {result['matched']}")
        self.stdout.write(f"Updated: {result['updated']}")
        self.stdout.write(f"Unmatched: {result['unmatched']}")

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING(
                    "No database rows were changed. Re-run with --apply after review."
                )
            )
