from django.db import migrations


INDEX_NAME = "uq_auth_user_email_ci_nonblank"


class Migration(migrations.Migration):

    dependencies = [
        ("propertylist_app", "0091_tenancyextension_proposed_start_date"),
    ]

    operations = [
        migrations.RunSQL(
            sql=f"""
                CREATE UNIQUE INDEX {INDEX_NAME}
                ON auth_user (LOWER(email))
                WHERE email <> '';
            """,
            reverse_sql=f"""
                DROP INDEX IF EXISTS {INDEX_NAME};
            """,
        ),
    ]