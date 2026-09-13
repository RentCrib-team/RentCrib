from django.core.management.base import BaseCommand

from propertylist_app.services.uk_city_catalogue import seed_official_uk_cities


class Command(BaseCommand):
    help = (
        "Idempotently ensure the official UK city catalogue exists without "
        "overwriting admin-managed city settings or images."
    )

    def handle(self, *args, **options):
        result = seed_official_uk_cities()

        self.stdout.write(self.style.SUCCESS("UK city catalogue seed complete."))
        self.stdout.write(f"Expected official cities: {result['expected']}")
        self.stdout.write(f"Created: {result['created']}")
        self.stdout.write(f"Already present: {result['existing']}")
        self.stdout.write(f"Canonical seed slugs present: {result['total']}")
