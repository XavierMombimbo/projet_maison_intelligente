import io
import os
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from homes.backup import encrypt_backup


class Command(BaseCommand):
    help = "Crée une sauvegarde JSON chiffrée des données Sentinelle."

    def add_arguments(self, parser):
        parser.add_argument("output")
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        destination = Path(options["output"]).expanduser().resolve()
        if destination.exists() and not options["force"]:
            raise CommandError("Le fichier existe déjà ; utilisez --force pour le remplacer.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        serialized = io.StringIO()
        with transaction.atomic():
            call_command(
                "dumpdata",
                "accounts",
                "homes",
                "notifications",
                stdout=serialized,
                indent=2,
            )
        payload = encrypt_backup(serialized.getvalue().encode("utf-8"))
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(payload)
        os.chmod(temporary, 0o600)
        temporary.replace(destination)
        self.stdout.write(self.style.SUCCESS(f"Sauvegarde chiffrée créée : {destination}"))
