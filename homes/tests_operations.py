import tempfile
import uuid
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from notifications.models import CameraPushPreference
from .crypto import decrypt_capture, encrypt_capture
from .models import (
    Camera,
    CaptureChiffree,
    Evenement,
    EvenementBoiteEnvoi,
    Maison,
    NonceRequeteCamera,
    StatutBoiteEnvoi,
    TypeEvenement,
)


class OperationsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ops", "ops@example.test", "Secret!2026")
        self.house = Maison.objects.create(nom="Maison sauvegardée", proprietaire=self.user)
        self.camera = Camera.objects.create(nom="Caméra sauvegardée", maison=self.house)

    def create_event_with_capture(self):
        event = Evenement.objects.create(
            client_event_id=uuid.uuid4(),
            camera=self.camera,
            maison=self.house,
            type=TypeEvenement.PERSONNE_DETECTEE,
            confiance_ia=0.9,
        )
        plaintext = b"capture-restorable"
        ciphertext, nonce = encrypt_capture(plaintext, event.pk)
        CaptureChiffree.objects.create(
            evenement=event,
            contenu_chiffre=ciphertext,
            nonce=nonce,
            type_mime="image/jpeg",
            taille=len(plaintext),
        )
        return event, plaintext

    @override_settings(
        CAPTURE_RETENTION_DAYS=30,
        EVENT_RETENTION_DAYS=90,
        CAMERA_NONCE_RETENTION_HOURS=24,
        OUTBOX_RETENTION_DAYS=7,
        AUDIT_RETENTION_DAYS=365,
    )
    def test_purge_supports_dry_run_then_deletes_expired_data(self):
        event, _ = self.create_event_with_capture()
        nonce = NonceRequeteCamera.objects.create(
            nonce=uuid.uuid4(), camera=self.camera, horodatage_client=timezone.now()
        )
        old = timezone.now() - timedelta(days=40)
        CaptureChiffree.objects.filter(evenement=event).update(date_creation=old)
        NonceRequeteCamera.objects.filter(pk=nonce.pk).update(date_creation=old)

        preview = StringIO()
        call_command("purge_expired_data", "--dry-run", stdout=preview)
        self.assertTrue(CaptureChiffree.objects.filter(evenement=event).exists())
        self.assertTrue(NonceRequeteCamera.objects.filter(pk=nonce.pk).exists())
        self.assertIn("captures=1", preview.getvalue())
        self.assertIn("nonces=1", preview.getvalue())

        call_command("purge_expired_data", stdout=StringIO())
        self.assertFalse(CaptureChiffree.objects.filter(evenement=event).exists())
        self.assertFalse(NonceRequeteCamera.objects.filter(pk=nonce.pk).exists())

    def test_pending_outbox_prevents_expired_event_deletion(self):
        event, _ = self.create_event_with_capture()
        EvenementBoiteEnvoi.objects.create(
            evenement=event, statut=StatutBoiteEnvoi.EN_ATTENTE
        )
        Evenement.objects.filter(pk=event.pk).update(
            horodatage=timezone.now() - timedelta(days=100)
        )

        call_command("purge_expired_data", stdout=StringIO())

        self.assertTrue(Evenement.objects.filter(pk=event.pk).exists())

    def test_encrypted_backup_restores_and_decrypts_capture(self):
        event, plaintext = self.create_event_with_capture()
        CameraPushPreference.objects.create(
            user=self.user, camera=self.camera, enabled=False
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sentinelle.backup"
            call_command("backup_sentinelle", str(path), stdout=StringIO())
            encrypted = path.read_bytes()
            self.assertNotIn(b"Maison sauvegard", encrypted)
            call_command("restore_sentinelle", str(path), stdout=StringIO())

            CaptureChiffree.objects.filter(evenement=event).delete()
            CameraPushPreference.objects.filter(user=self.user, camera=self.camera).delete()
            call_command("restore_sentinelle", str(path), "--apply", stdout=StringIO())

        capture = CaptureChiffree.objects.get(evenement_id=event.pk)
        restored = decrypt_capture(
            bytes(capture.contenu_chiffre), bytes(capture.nonce), event.pk
        )
        self.assertEqual(restored, plaintext)
        self.assertFalse(
            CameraPushPreference.objects.get(user=self.user, camera=self.camera).enabled
        )
