from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("propertylist_app", "0100_seed_official_uk_cities")]
    operations = [migrations.AddField(model_name="city", name="image_is_approved", field=models.BooleanField(default=False))]
