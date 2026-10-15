from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from homes.models import (
    CaptureChiffree,
    Evenement,
    EvenementBoiteEnvoi,
    JournalAudit,
    NonceRequeteCamera,
    StatutBoiteEnvoi,
)


class Command(BaseCommand):
    help = "Purge les données arrivées au terme de leur durée de conservation."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        now = timezone.now()
        querysets = {
            "captures": CaptureChiffree.objects.filter(
                date_creation__lt=now - timedelta(days=settings.CAPTURE_RETENTION_DAYS)
            ).exclude(evenement__boite_envoi__statut=StatutBoiteEnvoi.EN_ATTENTE),
            "nonces": NonceRequeteCamera.objects.filter(
                date_creation__lt=now - timedelta(hours=settings.CAMERA_NONCE_RETENTION_HOURS)
            ),
            "outbox": EvenementBoiteEnvoi.objects.filter(
                statut=StatutBoiteEnvoi.ENVOYE,
                date_envoi__lt=now - timedelta(days=settings.OUTBOX_RETENTION_DAYS),
            ),
            "audits": JournalAudit.objects.filter(
                date_creation__lt=now - timedelta(days=settings.AUDIT_RETENTION_DAYS)
            ),
            "evenements": Evenement.objects.filter(
                horodatage__lt=now - timedelta(days=settings.EVENT_RETENTION_DAYS)
            ).exclude(boite_envoi__statut=StatutBoiteEnvoi.EN_ATTENTE),
        }
        counts = {name: queryset.count() for name, queryset in querysets.items()}
        if not options["dry_run"]:
            with transaction.atomic():
                for name in ("captures", "nonces", "outbox", "audits", "evenements"):
                    querysets[name].delete()
        mode = "simulation" if options["dry_run"] else "suppression"
        self.stdout.write(
            f"{mode}: " + " ".join(f"{name}={count}" for name, count in counts.items())
        )
