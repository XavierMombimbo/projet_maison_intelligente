import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


INFRASTRUCTURE = (
    "database", "event_queue", "push_queue", "camera_presence",
    "realtime", "push_configuration", "workers",
)


def summarize_pilot(lines):
    samples = infrastructure_degraded = analysis_degraded = invalid = 0
    first = last = None
    largest_gap = 0.0
    complete = False
    summary_at = None
    planned_duration = None
    for line in lines:
        try:
            item = json.loads(line)
            if item.get("type") == "summary":
                complete = item.get("complete") is True
                if item.get("at"):
                    summary_at = datetime.fromisoformat(item["at"])
                if item.get("planned_duration_seconds") is not None:
                    planned_duration = int(item["planned_duration_seconds"])
                    if planned_duration < 1:
                        raise ValueError("planned duration must be positive")
                continue
            if item.get("type") != "sample":
                invalid += 1
                continue
            at = datetime.fromisoformat(item["at"])
            checks = item["checks"]
            if not isinstance(checks, dict):
                raise ValueError("checks must be an object")
        except (ValueError, TypeError, KeyError, AttributeError):
            invalid += 1
            continue
        if last is not None:
            largest_gap = max(largest_gap, (at - last).total_seconds())
        first = first or at
        last = at
        samples += 1
        infrastructure_degraded += item.get("status") == "error" or any(
            checks.get(name, {}).get("status") != "ok" for name in INFRASTRUCTURE
        )
        analysis_degraded += checks.get("analysis", {}).get("status") != "ok"
    sample_duration = (last - first).total_seconds() if first and last else 0.0
    trailing_gap = (summary_at - last).total_seconds() if summary_at and last else None
    duration_shortfall = (
        max(0.0, planned_duration - sample_duration)
        if planned_duration is not None else None
    )
    return {
        "samples": samples,
        "infrastructure_degraded": infrastructure_degraded,
        "analysis_degraded": analysis_degraded,
        "invalid_lines": invalid,
        "largest_gap_seconds": round(largest_gap, 1),
        "first_at": first.isoformat() if first else None,
        "last_at": last.isoformat() if last else None,
        "summary_at": summary_at.isoformat() if summary_at else None,
        "sample_duration_seconds": round(sample_duration, 1),
        "trailing_gap_seconds": round(trailing_gap, 1) if trailing_gap is not None else None,
        "planned_duration_seconds": planned_duration,
        "duration_shortfall_seconds": round(duration_shortfall, 1) if duration_shortfall is not None else None,
        "complete": complete,
    }


class Command(BaseCommand):
    help = "Resume un journal de pilote sans exposer de donnees privees."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("journal")
        parser.add_argument("--json", action="store_true", dest="as_json")
        parser.add_argument("--require-complete", action="store_true")
        parser.add_argument("--max-gap-seconds", type=int, default=180)

    def handle(self, *args, **options):
        if not 1 <= options["max_gap_seconds"] <= 86400:
            raise CommandError("--max-gap-seconds doit etre compris entre 1 et 86400.")
        try:
            with Path(options["journal"]).open(encoding="utf-8") as journal:
                report = summarize_pilot(journal)
        except OSError as exc:
            raise CommandError("Journal du pilote inaccessible.") from exc
        if options["as_json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=True))
        else:
            self.stdout.write(
                f"Mesures : {report['samples']} ; infrastructure degradee : "
                f"{report['infrastructure_degraded']} ; analyse degradee : "
                f"{report['analysis_degraded']} ; lignes invalides : {report['invalid_lines']} ; "
                f"plus grand trou : {report['largest_gap_seconds']} s ; "
                f"fin sans mesure : {report['trailing_gap_seconds']} s ; "
                f"duree manquante : {report['duration_shortfall_seconds']} s ; "
                f"termine : {'oui' if report['complete'] else 'non'}"
            )
        coverage_incomplete = (
            (report["trailing_gap_seconds"] is not None
             and report["trailing_gap_seconds"] > options["max_gap_seconds"])
            or (report["duration_shortfall_seconds"] is not None
                and report["duration_shortfall_seconds"] > options["max_gap_seconds"])
        )
        if options["require_complete"] and (
            not report["complete"] or not report["samples"] or report["invalid_lines"]
            or report["infrastructure_degraded"] or report["analysis_degraded"]
            or report["largest_gap_seconds"] > options["max_gap_seconds"]
            or coverage_incomplete
        ):
            raise CommandError("Pilote incomplet ou degrade ; consulter le resume.")
