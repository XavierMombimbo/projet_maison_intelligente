import argparse
import getpass
from pathlib import Path

from .client import GatewayAPIClient, GatewayAPIError
from .credentials import CredentialStoreError, load_credentials, save_credentials
from .rtsp import RTSPError
from .runner import run_gateway


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m gateway")
    commands = parser.add_subparsers(dest="command", required=True)
    pair = commands.add_parser("pair", help="Appairer cette passerelle à une caméra RTSP")
    pair.add_argument("--server", required=True, help="URL HTTPS du serveur Sentinelle")
    pair.add_argument("--code", help="Code d’appairage à six chiffres")
    run = commands.add_parser("run", help="Acquérir le flux RTSP")
    run.add_argument("--once", action="store_true", help="Lire une image H.264 puis quitter")
    webcam = commands.add_parser("webcam", help="Analyser la webcam du PC sans navigateur")
    webcam.add_argument("--index", type=int, default=0, help="Index local de la webcam")
    webcam.add_argument("--once", action="store_true", help="Analyser une image puis quitter sans alerte")
    webcam.add_argument("--allow-development-model", action="store_true",
                        help="Autoriser explicitement le modele YOLO de developpement")
    for command in (pair, run, webcam):
        command.add_argument(
            "--credentials-file", type=Path,
            help="Fichier DPAPI distinct pour une passerelle de recette locale",
        )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "pair":
            code = args.code or getpass.getpass("Code d’appairage : ")
            if len(code) != 6 or not code.isdigit():
                raise ValueError("Le code doit contenir exactement six chiffres.")
            credentials = GatewayAPIClient(args.server).pair(code)
            save_credentials(credentials, path=args.credentials_file)
            print(f"Passerelle appairée à la caméra {credentials.camera_id}.")
            return 0
        if args.command == "webcam":
            if not 0 <= args.index <= 10:
                raise ValueError("Index webcam invalide.")
            from .webcam import WebcamError, watch_webcam
            try:
                return watch_webcam(load_credentials(path=args.credentials_file), index=args.index, once=args.once,
                                    allow_development_model=args.allow_development_model)
            except WebcamError as exc:
                print(f"Erreur : {exc}")
                return 1
        return run_gateway(load_credentials(path=args.credentials_file), once=args.once)
    except (CredentialStoreError, GatewayAPIError, RTSPError, ValueError) as exc:
        print(f"Erreur : {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

