import json

from django.core.management.base import BaseCommand, CommandError

from homes.operations import collect_operations


class Command(BaseCommand):
    help = "Diagnostique les dependances et retards sans envoyer d'alerte ni modifier les donnees."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json")
        parser.add_argument("--max-queue-age", type=int, default=60)
        parser.add_argument("--camera-timeout", type=int, default=120)

    def handle(self, *args, **options):
        for name in ("max_queue_age", "camera_timeout"):
            if not 1 <= options[name] <= 86400:
                raise CommandError(f"--{name.replace('_', '-')} doit etre compris entre 1 et 86400 secondes.")
        report = collect_operations(max_queue_age=options["max_queue_age"], camera_timeout=options["camera_timeout"])
        if options["as_json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=True))
        else:
            self.stdout.write(f"Diagnostic : {report['status']}")
            for name, check in report["checks"].items():
                counts = " ".join(f"{key}={value}" for key, value in check.items() if isinstance(value, int))
                self.stdout.write(f"[{check['status']}] {name} : {check['message']} {counts}".rstrip())
        if report["status"] != "ok":
            raise CommandError("Diagnostic degrade ; consulter le rapport (aucune donnee modifiee).")
