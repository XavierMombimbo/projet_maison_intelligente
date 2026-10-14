"""Hidden Windows task entry point, with a separate configuration and receipt."""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from .credentials import CredentialStoreError, load_credentials
from .client import GatewayAPIError
from .event_queue import EncryptedEventQueue
from .schedule import EncryptedScheduleCache
from .webcam import WebcamConfigurationError, WebcamError, watch_webcam


class StartupError(ValueError):
    pass


def read_configuration(path):
    try:
        config = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise StartupError('Configuration de demarrage illisible.') from exc
    required = {'credentials_file', 'cache_root', 'env_file', 'status_file', 'mode', 'index', 'recipe'}
    if not isinstance(config, dict) or not required <= config.keys():
        raise StartupError('Configuration de demarrage incomplete.')
    if config['mode'] not in ('webcam', 'rtsp') or type(config['recipe']) is not bool:
        raise StartupError('Mode de demarrage invalide.')
    if type(config['index']) is not int or not 0 <= config['index'] <= 10:
        raise StartupError('Index webcam invalide.')
    for name in ('credentials_file', 'cache_root', 'status_file'):
        if not isinstance(config[name], str) or not Path(config[name]).is_absolute():
            raise StartupError('Les chemins de demarrage doivent etre absolus.')
    if config['env_file'] and not Path(config['env_file']).is_absolute():
        raise StartupError('Chemin environnement invalide.')
    if config['mode'] == 'webcam' and not config['recipe'] and not config.get('release_receipt'):
        raise StartupError('Preuve de publication absente.')
    return config


def verify_release(path, root):
    try:
        receipt = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        revision = receipt['revision']
        import re
        if not re.fullmatch(r'[0-9a-f]{40}', revision) or not receipt['anonymous_archive_verified']:
            raise StartupError('Publication non verifiee.')
        files = receipt['files']
        if not isinstance(files, dict) or not files:
            raise StartupError('Manifeste de source vide.')
        root = Path(root).resolve()
        for name, digest in files.items():
            target = (root / name).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                raise StartupError('Fichier publie absent ou chemin invalide.')
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise StartupError('Le code local ne correspond plus a la version publiee.')
        if not {'gateway/webcam.py', 'gateway/startup.py', 'config/settings.py', 'config/model_registry.json'} <= files.keys():
            raise StartupError('Manifeste de source incomplet.')
        return revision
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise StartupError('Preuve de publication invalide ou code local modifie.') from exc


def write_status(config, state):
    destination = Path(config['status_file'])
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.tmp')
    temporary.write_text(json.dumps({'state': state, 'pid': os.getpid(), 'updated_at': time.time()}), encoding='utf-8')
    os.replace(temporary, destination)


def launch(config, *, sleep=time.sleep):
    os.environ['SENTINELLE_ENV_FILE'] = config['env_file']
    if config['recipe']:
        root = Path(__file__).resolve().parents[1]
        os.environ.update({'DJANGO_DEBUG': '1', 'FCM_ENABLED': '0', 'REDIS_URL': '',
                           'DATABASE_URL': 'sqlite:///' + (root / 'db.sqlite3').as_posix()})
    if config['mode'] == 'webcam' and not config['recipe']:
        revision = verify_release(config['release_receipt'], Path(__file__).resolve().parents[1])
        os.environ['SENTINELLE_SOURCE_REVISION'] = revision
    credentials = load_credentials(path=Path(config['credentials_file']))
    cache = Path(config['cache_root'])
    while not cache.anchor or not Path(cache.anchor).exists():
        write_status(config, 'waiting_for_cache_drive')
        sleep(30)
    cache.mkdir(parents=True, exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(cache / 'temp')
    Path(os.environ['TEMP']).mkdir(exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
    # The diagnostic log contains only messages controlled by the gateway.
    with (cache / ('gateway-' + stamp + '.log')).open('a', encoding='utf-8', buffering=1) as log:
        def output(message):
            log.write(message + '\n')
            print(message, flush=True)
        write_status(config, 'running')
        if config['mode'] != 'webcam':
            from .runner import run_gateway
            result = run_gateway(credentials, once=config['recipe'])
        else:
            def run_webcam_once():
                return watch_webcam(
                    credentials, index=config['index'], once=config['recipe'],
                    allow_development_model=config['recipe'], output=output,
                    queue_factory=lambda camera_id: EncryptedEventQueue(camera_id, path=cache / 'events'),
                    schedule_cache_factory=lambda camera_id, key: EncryptedScheduleCache(camera_id, key, path=cache / 'schedules' / f'{camera_id}.schedule'),
                )
            for attempt in range(6):
                try:
                    result = run_webcam_once()
                    break
                except GatewayAPIError:
                    if not config['recipe'] or attempt == 5:
                        raise
                    write_status(config, 'waiting_for_server')
                    output('Serveur local indisponible ; nouvel essai programme.')
                    sleep(10)
        write_status(config, 'completed_recipe' if config['recipe'] else 'stopped')
        return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args(argv)
    config = None
    try:
        config = read_configuration(args.config)
        return launch(config)
    except (StartupError, WebcamConfigurationError, CredentialStoreError):
        if config:
            write_status(config, 'configuration_refused')
        print('Demarrage refuse : verifier configuration, appairage et publication.', flush=True)
        return 2
    except (GatewayAPIError, WebcamError, OSError):
        if config:
            write_status(config, 'unavailable')
        print('Passerelle indisponible ; consulter le statut local.', flush=True)
        return 1
    except KeyboardInterrupt:
        if config:
            write_status(config, 'stopped')
        return 0
    except Exception:
        if config:
            write_status(config, 'unexpected_failure')
        print('Erreur interne de passerelle ; intervention requise.', flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
