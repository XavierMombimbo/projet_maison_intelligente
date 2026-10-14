import json
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from homes.operations import collect_operations


COUNT_FIELDS = (
    "expected", "reported", "running", "degraded", "stale",
    "pending", "due", "overdue", "oldest_due_seconds",
    "event_outbox_age_seconds", "push_age_seconds",
)


def safe_snapshot(report, checked_at):
    checks = {}
    for name, check in report.get("checks", {}).items():
        checks[name] = {"status": check.get("status", "unknown")}
        checks[name].update({key: check[key] for key in COUNT_FIELDS if isinstance(check.get(key), int)})
    return {"type": "sample", "at": checked_at.isoformat(),
            "status": report.get("status", "unknown"), "checks": checks}


class Command(BaseCommand):
    help = "Journalise les diagnostics agreges pendant un pilote, sans contenu prive."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)
        parser.add_argument("--interval", type=int, default=60)
        parser.add_argument("--duration-seconds", type=int, default=86400)

    def handle(self, *args, **options):
        interval = options["interval"]
        duration = options["duration_seconds"]
        if not 1 <= interval <= 3600 or not interval <= duration <= 604800:
            raise CommandError("Intervalle ou duree invalide (1-3600 s, duree >= intervalle et <= 7 jours).")

        path = Path(options["output"]).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        last_sample = None
        samples = degraded = 0
        largest_gap = 0
        try:
            log = path.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise CommandError("Le journal existe deja ; choisir un nouveau chemin.") from exc

        deadline = time.monotonic() + duration
        with log:
            while True:
                checked_at = timezone.now()
                try:
                    close_old_connections()
                    snapshot = safe_snapshot(collect_operations(), checked_at)
                except Exception:
                    snapshot = {"type": "sample", "at": checked_at.isoformat(),
                                "status": "error", "checks": {}}
                finally:
                    close_old_connections()
                if last_sample is not None:
                    largest_gap = max(largest_gap, (checked_at - last_sample).total_seconds())
                last_sample = checked_at
                samples += 1
                degraded += snapshot["status"] != "ok"
                log.write(json.dumps(snapshot, ensure_ascii=True) + "\n")
                log.flush()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(interval, remaining))

            summary = {"type": "summary", "at": timezone.now().isoformat(),
                       "samples": samples, "degraded": degraded,
                       "largest_gap_seconds": round(largest_gap, 1),
                       "complete": True}
            log.write(json.dumps(summary, ensure_ascii=True) + "\n")
            log.flush()

        self.stdout.write(f"Pilote termine : {samples} mesures, {degraded} degradees, journal {path}")
        if degraded or largest_gap > 3 * interval:
            raise CommandError("Pilote degrade ; consulter le journal agrege.")
