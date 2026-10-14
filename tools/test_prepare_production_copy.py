import base64
import os
import sqlite3
import unittest
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from prepare_production_copy import KEY_LABELS, old_key, rotate_rows


class ProductionCopyRotationTests(unittest.TestCase):
    def test_derived_development_key_is_stable(self):
        self.assertEqual(len(old_key({}, "CAPTURE_ENCRYPTION_KEY")), 32)
        self.assertEqual(old_key({}, "CAPTURE_ENCRYPTION_KEY"), old_key({}, "CAPTURE_ENCRYPTION_KEY"))

    def test_rotates_uuid_aad_and_verifies_plaintext(self):
        event_id = uuid.uuid4()
        plaintext = b"capture test"
        nonce = os.urandom(12)
        old = AESGCM(old_key({}, "CAPTURE_ENCRYPTION_KEY"))
        ciphertext = old.encrypt(nonce, plaintext, f"sentinelle-capture:{event_id}".encode())
        config = {
            name: base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
            for name in KEY_LABELS
        }
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE TABLE accounts_mfadevice (user_id INTEGER, encrypted_secret BLOB, nonce BLOB, pending_encrypted_secret BLOB, pending_nonce BLOB)")
            db.execute("CREATE TABLE homes_capturechiffree (evenement_id TEXT, contenu_chiffre BLOB, nonce BLOB)")
            db.execute("CREATE TABLE homes_camera (id TEXT, configuration_source_chiffree BLOB, nonce_configuration_source BLOB, cle_signature_evenement_chiffree BLOB, nonce_cle_signature_evenement BLOB)")
            db.execute("CREATE TABLE homes_profilbiometrique (id TEXT, gabarit_chiffre BLOB, nonce_gabarit BLOB)")
            db.execute("INSERT INTO homes_capturechiffree VALUES (?, ?, ?)", (event_id.hex, ciphertext, nonce))
            counts = rotate_rows(db, {}, config)
            self.assertEqual(counts["homes_capturechiffree.contenu_chiffre"], 1)
            new_ciphertext, new_nonce = db.execute("SELECT contenu_chiffre, nonce FROM homes_capturechiffree").fetchone()
            new = AESGCM(base64.urlsafe_b64decode(config["CAPTURE_ENCRYPTION_KEY"]))
            self.assertEqual(new.decrypt(new_nonce, new_ciphertext, f"sentinelle-capture:{event_id}".encode()), plaintext)
            self.assertNotEqual(ciphertext, new_ciphertext)


if __name__ == "__main__":
    unittest.main()
