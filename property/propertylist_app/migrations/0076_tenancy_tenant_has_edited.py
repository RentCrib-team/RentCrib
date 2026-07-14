# Generated manually for tenant one-time edit enforcement

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("propertylist_app", "0075_messagethread_deleted_at_alter_review_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenancy",
            name="tenant_has_edited",
            field=models.BooleanField(default=False),
        ),
    ]