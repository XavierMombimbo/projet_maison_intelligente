import time

from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, close_old_connections

from notifications.services import dispatch_due_push_deliveries
from homes.worker_health import record_worker_heartbeat


class Command(BaseCommand):
    help = "Livre les notifications push en attente et applique les reprises bornées."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--interval", type=int, default=5)

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1 or limit > 10_000:
            raise CommandError("--limit doit être compris entre 1 et 10000.")
        interval = options["interval"]
        if not 1 <= interval <= 3600:
            raise CommandError("--interval doit etre compris entre 1 et 3600 secondes.")
        watch = options["watch"]
        if watch:
            self.stdout.write(f"Livraison continue active : intervalle={interval}s. Ctrl+C pour arreter.")
        try:
            while True:
                close_old_connections()
                try:
                    accepted, not_accepted = dispatch_due_push_deliveries(limit=limit)
                except OperationalError:
                    if not watch:
                        raise
                    self.stderr.write("Base indisponible ; nouvelle tentative au prochain cycle.")
                else:
                    if watch:
                        record_worker_heartbeat("push", interval)
                    if not watch or accepted or not_accepted:
                        self.stdout.write(
                            self.style.SUCCESS(f"acceptées={accepted} non_acceptées={not_accepted}")
                        )
                finally:
                    close_old_connections()
                if not watch:
                    return
                time.sleep(interval)
        except KeyboardInterrupt:
            if not watch:
                raise
            self.stdout.write("Livraison continue arretee.")

