"""Create an isolated production database and secret set; never mutate the source."""

import argparse
import base64
import hashlib
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import dotenv_values, set_key


ROOT = Path(__file__).resolve().parent.parent
DEV_SECRET = "development-only-change-me-this-is-never-for-production-2026"
ENCRYPTED_FIELDS = (
    ("accounts_mfadevice", "user_id", "encrypted_secret", "nonce", "MFA_ENCRYPTION_KEY", "mfa:"),
    ("accounts_mfadevice", "user_id", "pending_encrypted_secret", "pending_nonce", "MFA_ENCRYPTION_KEY", "mfa:"),
    ("homes_capturechiffree", "evenement_id", "contenu_chiffre", "nonce", "CAPTURE_ENCRYPTION_KEY", "sentinelle-capture:"),
    ("homes_camera", "id", "configuration_source_chiffree", "nonce_configuration_source", "CAMERA_SOURCE_ENCRYPTION_KEY", "sentinelle-camera-source:"),
    ("homes_camera", "id", "cle_signature_evenement_chiffree", "nonce_cle_signature_evenement", "EVENT_SIGNING_ENCRYPTION_KEY", "sentinelle-event-signing:"),
    ("homes_profilbiometrique", "id", "gabarit_chiffre", "nonce_gabarit", "BIOMETRIC_ENCRYPTION_KEY", "sentinelle-biometric-profile:"),
)
KEY_LABELS = {
    "MFA_ENCRYPTION_KEY": "mfa",
    "CAPTURE_ENCRYPTION_KEY": "capture",
    "CAMERA_SOURCE_ENCRYPTION_KEY": "camera-source",
    "BIOMETRIC_ENCRYPTION_KEY": "biometric",
    "EVENT_SIGNING_ENCRYPTION_KEY": "event-signing",
    "BACKUP_ENCRYPTION_KEY": "backup",
    "PUSH_TOKEN_ENCRYPTION_KEY": "push-token",
}
PEPPERS = (
    "DJANGO_SECRET_KEY", "PAIRING_CODE_PEPPER", "CAMERA_CREDENTIAL_PEPPER",
    "CAMERA_JWT_SECRET", "AUDIT_LOG_PEPPER", "MOBILE_JWT_SECRET",
    "MOBILE_CHALLENGE_PEPPER", "MOBILE_REFRESH_PEPPER", "RECOVERY_CODE_PEPPER",
    "EMAIL_OTP_PEPPER", "PUSH_TOKEN_PEPPER", "CHANNEL_ENCRYPTION_KEY",
)


def old_key(config, name):
    value = config.get(name)
    if value:
        return base64.urlsafe_b64decode(value.encode("ascii"))
    secret = config.get("DJANGO_SECRET_KEY") or DEV_SECRET
    return hashlib.sha256(f"sentinelle-dev-{KEY_LABELS[name]}:{secret}".encode()).digest()


def rotate_rows(db, old_config, new_config):
    counts = {}
    for table, identity, cipher, nonce, key_name, aad_prefix in ENCRYPTED_FIELDS:
        old = AESGCM(old_key(old_config, key_name))
        new = AESGCM(base64.urlsafe_b64decode(new_config[key_name]))
        rows = db.execute(
            f"SELECT rowid, {identity}, {cipher}, {nonce} FROM {table} WHERE {cipher} IS NOT NULL"
        ).fetchall()
        for rowid, identifier, ciphertext, old_nonce in rows:
            if old_nonce is None:
                raise ValueError(f"Missing nonce in {table}.{cipher}")
            if identity != "user_id":
                identifier = str(uuid.UUID(str(identifier)))
            aad = f"{aad_prefix}{identifier}".encode("ascii")
            try:
                plain = old.decrypt(bytes(old_nonce), bytes(ciphertext), aad)
            except Exception as exc:
                raise ValueError(f"Cannot decrypt {table}.{cipher} with the current key") from exc
            fresh_nonce = os.urandom(12)
            encrypted = new.encrypt(fresh_nonce, plain, aad)
            if new.decrypt(fresh_nonce, encrypted, aad) != plain:
                raise ValueError(f"Rotation verification failed for {table}.{cipher}")
            db.execute(
                f"UPDATE {table} SET {cipher} = ?, {nonce} = ? WHERE rowid = ?",
                (encrypted, fresh_nonce, rowid),
            )
        counts[f"{table}.{cipher}"] = len(rows)
    return counts


def invalidate_old_access(db):
    now = datetime.now(timezone.utc).isoformat()
    db.execute("DELETE FROM django_session")
    db.execute("DELETE FROM accounts_mfarecoverycode")
    db.execute("UPDATE accounts_mfaemailchallenge SET used_at = ? WHERE used_at IS NULL", (now,))
    db.execute("UPDATE accounts_mobileauthchallenge SET used_at = ? WHERE used_at IS NULL", (now,))
    db.execute("UPDATE accounts_mobilesession SET revoked_at = ? WHERE revoked_at IS NULL", (now,))
    db.execute(
        "UPDATE notifications_pushinstallation SET active = 0, token_ciphertext = NULL, "
        "token_nonce = NULL, token_digest = NULL, invalidated_at = ?",
        (now,),
    )
    db.execute(
        "UPDATE notifications_pushdelivery SET status = 'invalid', next_attempt_at = NULL "
        "WHERE status IN ('pending', 'retry')"
    )
    db.execute("UPDATE homes_codeappairage SET utilise = 1, date_utilisation = ? WHERE utilise = 0", (now,))
    db.execute("DELETE FROM homes_noncerequetecamera")
    db.execute(
        "UPDATE homes_camera SET statut_appairage = 'unpaired', identifiant_appareil = NULL, "
        "secret_appareil_hash = '', cle_signature_evenement_chiffree = NULL, "
        "nonce_cle_signature_evenement = NULL, surveillance_active = 0, "
        "surveillance_appliquee = NULL, surveillance_appliquee_le = NULL, "
        "derniere_connexion = NULL, date_appairage = NULL, "
        "version_jeton = version_jeton + 1 WHERE statut_appairage = 'paired'"
    )


def prepare(source, output, domain):
    source = source.resolve(strict=True)
    output = output.resolve()
    if source == output / "db.sqlite3":
        raise ValueError("Source and destination must differ")
    output.mkdir(parents=True, exist_ok=False)
    database = output / "db.sqlite3"
    env_file = output / ".env.production"
    old_config = dict(dotenv_values(ROOT / ".env"))
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as original:
        with sqlite3.connect(database) as clone:
            original.backup(clone)
    new_config = {key: value for key, value in old_config.items() if value is not None}
    for key in KEY_LABELS:
        new_config[key] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    for key in PEPPERS:
        new_config[key] = secrets.token_urlsafe(48)
    new_config.update({
        "DJANGO_DEBUG": "False",
        "DJANGO_ALLOWED_HOSTS": f"{domain},localhost,127.0.0.1",
        "DJANGO_CSRF_TRUSTED_ORIGINS": f"https://{domain}",
        "MOBILE_WEB_ALLOWED_ORIGINS": f"https://{domain}",
        "DJANGO_SECURE_SSL_REDIRECT": "True",
        "DJANGO_SECURE_COOKIES": "True",
        "DJANGO_SECURE_HSTS_SECONDS": "0",
        "DATABASE_URL": f"sqlite:///{database.as_posix()}",
        "REDIS_URL": "",
    })
    with sqlite3.connect(database) as clone:
        clone.execute("PRAGMA foreign_keys = ON")
        with clone:
            counts = rotate_rows(clone, old_config, new_config)
            invalidate_old_access(clone)
        if clone.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        if clone.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("SQLite foreign key check failed")
    env_file.touch(exist_ok=False)
    for key, value in new_config.items():
        set_key(str(env_file), key, value, quote_mode="always")
    if dict(dotenv_values(env_file)) != new_config:
        raise ValueError("Production environment round-trip failed")
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--domain", default="sentinelle.smartxcongo.com")
    args = parser.parse_args()
    result = prepare(args.source, args.output, args.domain)
    for field, count in result.items():
        print(f"{field}: {count} rotated")
    print("Isolated copy ready; active database unchanged. REDIS_URL remains unset.")
