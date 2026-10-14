import argparse
import getpass
import os
from pathlib import Path
from uuid import UUID

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
    enroll = commands.add_parser("face-enroll", help="Enrôler volontairement un profil ArcFace depuis la webcam")
    enroll.add_argument("--profile-id", required=True, type=UUID)
    enroll.add_argument("--model-root", required=True, type=Path)
    enroll.add_argument("--index", type=int, default=0, help="Index local de la webcam")
    enroll.add_argument("--academic-use-acknowledged", action="store_true",
                        help="Confirme l’usage académique non commercial des poids InsightFace")
    check = commands.add_parser("face-check", help="Comparer localement un visage volontaire à ArcFace")
    check.add_argument("--model-root", required=True, type=Path)
    check.add_argument("--index", type=int, default=0, help="Index local de la webcam")
    check.add_argument("--threshold", type=float, default=0.45, help="Seuil cosinus ArcFace (0 à 1)")
    check.add_argument("--academic-use-acknowledged", action="store_true",
                       help="Confirme l’usage académique non commercial des poids InsightFace")
    for command in (pair, run, webcam, enroll, check):
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
        if args.command == "face-enroll":
            if not 0 <= args.index <= 10:
                raise ValueError("Index webcam invalide.")
            if not args.academic_use_acknowledged:
                raise ValueError("Confirmez l’usage académique non commercial d’ArcFace.")
            from .facial import ARCFACE_TEMPLATE_FORMAT, ArcFaceEmbedder, FaceRecognitionError
            from .model_policy import ModelApprovalError, require_arcface_academic_approval
            from .webcam import WebcamError, WebcamReader

            os.environ.setdefault("INSIGHTFACE_HOME", str(args.model_root))
            reader = WebcamReader(args.index)
            try:
                require_arcface_academic_approval(args.model_root)
                reader.open()
                template = ArcFaceEmbedder.from_model_root(args.model_root).embedding_from_bgr(reader.read())
            except (FaceRecognitionError, ModelApprovalError, WebcamError) as exc:
                print(f"Erreur : {exc}")
                return 1
            finally:
                reader.close()
            credentials = load_credentials(path=args.credentials_file)
            client = GatewayAPIClient(credentials.server_url)
            token = client.token(credentials)
            client.enroll_biometric_profile(
                token, str(args.profile_id), template=template,
                template_format=ARCFACE_TEMPLATE_FORMAT,
            )
            print("Profil facial enrôlé localement ; aucune image n’a été conservée.")
            return 0
        if args.command == "face-check":
            if not 0 <= args.index <= 10:
                raise ValueError("Index webcam invalide.")
            if not args.academic_use_acknowledged:
                raise ValueError("Confirmez l’usage académique non commercial d’ArcFace.")
            from .biometrics import BiometricCacheError, BiometricCacheStore, synchronize_biometric_profiles
            from .facial import ArcFaceEmbedder, FaceRecognitionError, compare_embedding
            from .model_policy import ModelApprovalError, require_arcface_academic_approval
            from .webcam import WebcamError, WebcamReader

            os.environ.setdefault("INSIGHTFACE_HOME", str(args.model_root))
            reader = WebcamReader(args.index)
            try:
                require_arcface_academic_approval(args.model_root)
                credentials = load_credentials(path=args.credentials_file)
                client = GatewayAPIClient(credentials.server_url)
                token = client.token(credentials)
                cache = BiometricCacheStore(args.model_root / "cache" / "gateway.biometrics")
                synchronize_biometric_profiles(client, token, store=cache)
                profiles = cache.profiles_for_comparison()
                reader.open()
                query = ArcFaceEmbedder.from_model_root(args.model_root).embedding_from_bgr(reader.read())
                result = compare_embedding(query, profiles, threshold=args.threshold)
            except (BiometricCacheError, FaceRecognitionError, ModelApprovalError, WebcamError) as exc:
                print(f"Erreur : {exc}")
                return 1
            finally:
                reader.close()
            label = {"matched": "reconnu", "unknown": "inconnu", "unavailable": "indisponible"}[result.state]
            print(f"Résultat facial local : {label}.")
            return 0
        return run_gateway(load_credentials(path=args.credentials_file), once=args.once)
    except (CredentialStoreError, GatewayAPIError, RTSPError, ValueError) as exc:
        print(f"Erreur : {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

