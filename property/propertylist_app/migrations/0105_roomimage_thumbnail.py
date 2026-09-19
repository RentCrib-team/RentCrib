from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("propertylist_app", "0104_review_decimal_weighted_ratings")]

    operations = [
        migrations.AddField(
            model_name="roomimage",
            name="thumbnail",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="room_images/thumbnails/",
            ),
        ),
    ]
