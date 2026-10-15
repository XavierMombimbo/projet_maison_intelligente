import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0005_mobileauthchallenge_mobilesession"),
        ("homes", "0015_camera_surveillance_appliquee"),
    ]

    operations = [
        migrations.CreateModel(
            name="PushInstallation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(default="fcm", max_length=16)),
                ("platform", models.CharField(choices=[("android", "Android"), ("ios", "iOS"), ("web", "Web")], max_length=12)),
                ("permission", models.CharField(choices=[("unknown", "Inconnue"), ("granted", "Accordée"), ("provisional", "Provisoire"), ("denied", "Refusée")], default="unknown", max_length=16)),
                ("token_ciphertext", models.BinaryField(blank=True, null=True)),
                ("token_nonce", models.BinaryField(blank=True, max_length=12, null=True)),
                ("token_digest", models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ("active", models.BooleanField(db_index=True, default=False)),
                ("registered_at", models.DateTimeField(blank=True, null=True)),
                ("last_seen_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("invalidated_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("session", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="push_installation", to="accounts.mobilesession")),
            ],
            options={"ordering": ("-updated_at",)},
        ),
        migrations.CreateModel(
            name="PushDelivery",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("pending", "En attente"), ("retry", "Nouvelle tentative"), ("accepted", "Acceptée par le fournisseur"), ("received", "Reçue par l’application"), ("failed", "Échec définitif"), ("invalid", "Installation invalide"), ("cancelled", "Annulée")], db_index=True, default="pending", max_length=16)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("next_attempt_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("provider_message_id", models.CharField(blank=True, max_length=255)),
                ("last_error", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("provider_accepted_at", models.DateTimeField(blank=True, null=True)),
                ("received_at", models.DateTimeField(blank=True, null=True)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="push_deliveries", to="homes.evenement")),
                ("installation", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="deliveries", to="notifications.pushinstallation")),
                ("recipient", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="push_deliveries", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("created_at",)},
        ),
        migrations.AddConstraint(
            model_name="pushinstallation",
            constraint=models.CheckConstraint(
                condition=models.Q(models.Q(("active", True), ("invalidated_at__isnull", True), ("token_ciphertext__isnull", False), ("token_digest__isnull", False), ("token_nonce__isnull", False)), ("active", False), _connector="OR"),
                name="active_push_installation_has_token",
            ),
        ),
        migrations.AddConstraint(
            model_name="pushdelivery",
            constraint=models.UniqueConstraint(condition=models.Q(("installation__isnull", False)), fields=("event", "installation"), name="unique_push_delivery_per_installation"),
        ),
        migrations.AddIndex(
            model_name="pushdelivery",
            index=models.Index(fields=["status", "next_attempt_at", "created_at"], name="push_due_delivery_idx"),
        ),
    ]

