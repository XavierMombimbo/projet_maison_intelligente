from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("notifications", "0003_camerapushpreference_quiet_end_and_more")]

    operations = [migrations.AddField(
        model_name="camerapushpreference", name="lock_screen",
        field=models.CharField(max_length=8, default="private", choices=[
            ("private", "Masquer le contenu"),
            ("secret", "Masquer la notification"),
            ("public", "Afficher le message générique"),
        ]),
    )]
