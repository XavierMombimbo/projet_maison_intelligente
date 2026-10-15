import json
import os
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from homes.backup import decrypt_backup


class Command(BaseCommand):
    help = "Vérifie ou restaure une sauvegarde Sentinelle chiffrée."

    def add_arguments(self, parser):
        parser.add_argument("input")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        source = Path(options["input"]).expanduser().resolve()
        try:
            plaintext = decrypt_backup(source.read_bytes())
            objects = json.loads(plaintext)
        except (OSError, ValueError, InvalidTag, json.JSONDecodeError) as exc:
            raise CommandError("Sauvegarde absente, altérée ou clé incorrecte.") from exc
        if not isinstance(objects, list):
            raise CommandError("Contenu de sauvegarde invalide.")
        if not options["apply"]:
            self.stdout.write(self.style.SUCCESS(f"Sauvegarde valide : {len(objects)} objets"))
            return

        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".json", delete=False
            ) as temporary:
                temporary.write(plaintext)
                temporary_path = temporary.name
            os.chmod(temporary_path, 0o600)
            with transaction.atomic():
                call_command("loaddata", temporary_path, verbosity=0)
        finally:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass
        self.stdout.write(self.style.SUCCESS(f"Restauration appliquée : {len(objects)} objets"))
