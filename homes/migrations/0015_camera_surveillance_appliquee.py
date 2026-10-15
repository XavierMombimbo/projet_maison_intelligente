from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("homes", "0014_alter_evenement_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="camera",
            name="surveillance_appliquee",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="camera",
            name="surveillance_appliquee_le",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
