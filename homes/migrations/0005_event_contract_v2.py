import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("homes", "0004_camera_cle_signature_evenement_chiffree_and_more")]

    operations = [
        migrations.AddField(
            model_name="evenement",
            name="horodatage_observation",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="evenement",
            name="nom_modele",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="evenement",
            name="version_contrat",
            field=models.PositiveSmallIntegerField(db_index=True, default=1),
        ),
        migrations.AddField(
            model_name="evenement",
            name="version_modele",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AlterField(
            model_name="evenement",
            name="type",
            field=models.CharField(
                choices=[
                    ("person_detected", "Personne détectée"),
                    ("objects_detected", "Objets détectés"),
                    ("simulation", "Détection simulée"),
                ],
                max_length=24,
            ),
        ),
        migrations.CreateModel(
            name="ObjetDetecte",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("classe", models.CharField(db_index=True, max_length=64)),
                ("confiance", models.FloatField(validators=[django.core.validators.MinValueValidator(0.0), django.core.validators.MaxValueValidator(1.0)])),
                ("boite", models.JSONField()),
                ("identifiant_suivi", models.CharField(blank=True, max_length=64)),
                ("evenement", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="objets", to="homes.evenement")),
            ],
            options={
                "ordering": ("id",),
                "indexes": [models.Index(fields=["classe", "-confiance"], name="object_class_score_idx")],
            },
        ),
    ]
