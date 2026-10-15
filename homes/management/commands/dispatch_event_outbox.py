import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, close_old_connections

from homes.outbox import dispatch_pending_outbox
from homes.worker_health import record_worker_heartbeat


class Command(BaseCommand):
    help = "Livre les alertes en attente dans la boîte d’envoi durable."

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
            backend = settings.CHANNEL_LAYERS.get("default", {}).get("BACKEND", "")
            if backend not in (
                "channels_redis.core.RedisChannelLayer",
                "channels_redis.pubsub.RedisPubSubChannelLayer",
            ):
                raise CommandError(
                    "Le mode continu exige un transport Redis partage avec le serveur web. "
                    "Configurer REDIS_URL avant de demarrer les deux services."
                )
            self.stdout.write(f"Livraison continue active : intervalle={interval}s. Ctrl+C pour arreter.")
        try:
            while True:
                close_old_connections()
                try:
                    sent, failed = dispatch_pending_outbox(limit=limit)
                except OperationalError:
                    if not watch:
                        raise
                    self.stderr.write("Base indisponible ; nouvelle tentative au prochain cycle.")
                else:
                    if watch:
                        record_worker_heartbeat("event_outbox", interval)
                    if not watch or sent or failed:
                        self.stdout.write(f"envoyés={sent} échecs={failed}")
                    if failed and not watch:
                        raise CommandError("Certaines alertes restent en attente.")
                finally:
                    close_old_connections()
                if not watch:
                    return
                time.sleep(interval)
        except KeyboardInterrupt:
            if not watch:
                raise
            self.stdout.write("Livraison continue arretee.")
