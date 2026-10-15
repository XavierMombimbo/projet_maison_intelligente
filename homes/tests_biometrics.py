import base64

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from .biometrics import revoke_biometric_profile
from .models import (
    AccusePurgeBiometrique,
    Camera,
    JournalAudit,
    Maison,
    MembreMaison,
    ProfilBiometrique,
    RoleMaison,
    StatutInvitation,
    StatutProfilBiometrique,
)
from .services import consume_pairing_code, create_pairing_code


class BiometricProfileTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            "bio-owner", "bio-owner@example.test", "Secret!2026"
        )
        self.member = User.objects.create_user(
            "bio-member", "bio-member@example.test", "Secret!2026"
        )
        self.outsider = User.objects.create_user(
            "bio-outsider", "bio-outsider@example.test", "Secret!2026"
        )
        self.house = Maison.objects.create(nom="Maison biométrique", proprietaire=self.owner)
        MembreMaison.objects.create(
            maison=self.house,
            utilisateur=self.member,
            role=RoleMaison.FAMILLE,
            statut=StatutInvitation.ACCEPTEE,
        )
        self.profile = ProfilBiometrique.objects.create(
            maison=self.house,
            utilisateur=self.member,
            libelle="Profil volontaire",
        )

    def test_template_is_encrypted_and_decryptable(self):
        template = b"face-vector-fixture-that-must-not-appear-in-database"

        self.profile.set_template(template, "arcface-vector-v1")
        self.profile.refresh_from_db()

        self.assertNotIn(template, bytes(self.profile.gabarit_chiffre))
        self.assertEqual(self.profile.decrypt_template(), template)
        self.assertEqual(self.profile.format_gabarit, "arcface-vector-v1")

    def test_creation_requires_explicit_consent_and_accepted_membership(self):
        self.client.force_login(self.owner)
        url = reverse("biometric-profile-list", kwargs={"maison_pk": self.house.pk})

        rejected = self.client.post(url, {"libelle": "Moi"})
        accepted = self.client.post(url, {"libelle": "Moi", "consentement": "on"})

        self.assertEqual(rejected.status_code, 400)
        self.assertRedirects(accepted, url)
        self.assertTrue(
            ProfilBiometrique.objects.filter(
                maison=self.house,
                utilisateur=self.owner,
                statut=StatutProfilBiometrique.ACTIF,
            ).exists()
        )
        self.assertTrue(JournalAudit.objects.filter(action="biometric.profile.consent").exists())

        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(
            self.client.post(url, {"libelle": "Intrus", "consentement": "on"}).status_code,
            404,
        )

    def test_only_data_subject_can_export_template(self):
        template = b"private-face-template"
        self.profile.set_template(template, "test-vector-v1")
        url = reverse(
            "biometric-profile-export",
            kwargs={"maison_pk": self.house.pk, "profile_pk": self.profile.pk},
        )

        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.member)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store, private")
        self.assertEqual(
            response.json()["template_base64"], base64.b64encode(template).decode("ascii")
        )

    def test_subject_or_owner_can_withdraw_and_template_is_destroyed(self):
        template = b"template-to-destroy"
        self.profile.set_template(template, "test-vector-v1")
        url = reverse(
            "biometric-profile-revoke",
            kwargs={"maison_pk": self.house.pk, "profile_pk": self.profile.pk},
        )

        self.client.force_login(self.owner)
        response = self.client.post(url)

        self.assertRedirects(
            response,
            reverse("biometric-profile-list", kwargs={"maison_pk": self.house.pk}),
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.statut, StatutProfilBiometrique.REVOQUE)
        self.assertIsNone(self.profile.gabarit_chiffre)
        self.assertIsNone(self.profile.nonce_gabarit)
        audit = JournalAudit.objects.get(action="biometric.profile.withdraw")
        self.assertNotIn(template.decode("ascii"), str(audit.metadonnees))


class BiometricGatewayAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            "gateway-bio-owner", "gateway-bio@example.test", "Secret!2026"
        )
        self.house = Maison.objects.create(nom="Maison sync", proprietaire=self.owner)
        self.camera = Camera.objects.create(nom="Caméra sync", maison=self.house)
        _, code = create_pairing_code(self.camera)
        self.credentials = consume_pairing_code(code)
        self.profile = ProfilBiometrique.objects.create(
            maison=self.house,
            utilisateur=self.owner,
            libelle="Profil sync",
        )
        self.template = b"encrypted-template-sent-to-own-house-only"
        self.profile.set_template(self.template, "test-vector-v1")
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {self.credentials.access_token}"}

    def test_manifest_is_short_lived_scoped_and_not_cached(self):
        other_owner = User.objects.create_user(
            "other-bio-owner", "other-bio@example.test", "Secret!2026"
        )
        other_house = Maison.objects.create(nom="Autre maison", proprietaire=other_owner)
        other = ProfilBiometrique.objects.create(
            maison=other_house,
            utilisateur=other_owner,
            libelle="Profil étranger",
        )
        other.set_template(b"foreign-template", "test-vector-v1")

        response = self.client.get(reverse("api-camera-biometric-profiles"), **self.auth)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store, private")
        payload = response.json()
        self.assertEqual(payload["cache_ttl_seconds"], 300)
        self.assertEqual(len(payload["profiles"]), 1)
        self.assertEqual(payload["profiles"][0]["profile_id"], str(self.profile.pk))
        self.assertEqual(
            base64.b64decode(payload["profiles"][0]["template"]), self.template
        )
        self.assertNotContains(response, "foreign-template")
        self.assertNotContains(response, self.owner.username)

    def test_withdrawal_becomes_tombstone_and_gateway_can_confirm_purge(self):
        self.profile = revoke_biometric_profile(self.profile)

        manifest = self.client.get(reverse("api-camera-biometric-profiles"), **self.auth)
        payload = manifest.json()
        self.assertEqual(payload["profiles"], [])
        self.assertEqual(
            payload["revoked"],
            [{"profile_id": str(self.profile.pk), "version": self.profile.version}],
        )

        response = self.client.post(
            reverse("api-camera-biometric-purge-ack"),
            {"purges": payload["revoked"]},
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AccusePurgeBiometrique.objects.filter(
                camera=self.camera,
                profil=self.profile,
                version=self.profile.version,
            ).exists()
        )

    def test_gateway_cannot_ack_foreign_or_active_profile(self):
        response = self.client.post(
            reverse("api-camera-biometric-purge-ack"),
            {"purges": [{"profile_id": str(self.profile.pk), "version": self.profile.version}]},
            content_type="application/json",
            **self.auth,
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(AccusePurgeBiometrique.objects.exists())

    def test_gateway_can_enroll_an_active_profile_in_its_own_house(self):
        self.profile.gabarit_chiffre = None
        self.profile.nonce_gabarit = None
        self.profile.format_gabarit = ""
        self.profile.save(update_fields=("gabarit_chiffre", "nonce_gabarit", "format_gabarit"))
        template = bytes(range(256)) * 8
        response = self.client.post(
            reverse("api-camera-biometric-enroll", kwargs={"profile_id": self.profile.pk}),
            {"format": "arcface-f32le-v1", "template": base64.b64encode(template).decode("ascii")},
            content_type="application/json", **self.auth,
        )
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.decrypt_template(), template)
        self.assertEqual(self.profile.format_gabarit, "arcface-f32le-v1")
        self.assertTrue(JournalAudit.objects.filter(action="biometric.profile.enroll").exists())

    def test_gateway_cannot_enroll_a_profile_from_another_house(self):
        owner = User.objects.create_user("other-enroll", "other-enroll@example.test", "Secret!2026")
        other = ProfilBiometrique.objects.create(
            maison=Maison.objects.create(nom="Autre maison", proprietaire=owner),
            utilisateur=owner, libelle="Profil étranger",
        )
        response = self.client.post(
            reverse("api-camera-biometric-enroll", kwargs={"profile_id": other.pk}),
            {"format": "arcface-f32le-v1", "template": base64.b64encode(bytes(range(256)) * 8).decode("ascii")},
            content_type="application/json", **self.auth,
        )
        self.assertEqual(response.status_code, 404)
