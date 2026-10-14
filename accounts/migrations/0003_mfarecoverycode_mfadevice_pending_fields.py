from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_mfadevice")]

    operations = [
        migrations.AddField(
            model_name="mfadevice",
            name="pending_encrypted_secret",
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="mfadevice",
            name="pending_nonce",
            field=models.BinaryField(blank=True, max_length=12, null=True),
        ),
        migrations.CreateModel(
            name="MFARecoveryCode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("digest", models.CharField(max_length=64, unique=True)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="mfa_recovery_codes", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("created_at",)},
        ),
    ]
