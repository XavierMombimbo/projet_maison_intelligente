from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("homes", "0016_profilbiometrique_accusepurgebiometrique_and_more")]

    operations = [
        migrations.AddField(
            model_name="camera",
            name="version_planning_appliquee",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
