from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from .models import AccesCamera, Camera, CodeAppairage, JournalAudit, Maison, MembreMaison, RoleMaison, StatutAppairage, StatutInvitation
from .security import InvalidCameraToken, authenticate_camera_token
from .services import PairingError, consume_pairing_code, create_pairing_code, renew_camera_token, revoke_camera


class PairingReplacementTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user('reset-owner', 'reset-owner@example.test', 'Secret!2026')
        self.other = User.objects.create_user('reset-other', 'reset-other@example.test', 'Secret!2026')
        self.house = Maison.objects.create(nom='Maison fictive', proprietaire=self.owner)
        self.camera = Camera.objects.create(nom='Caméra fictive', maison=self.house, surveillance_active=True)
        _, self.old_code = create_pairing_code(self.camera)
        self.old = consume_pairing_code(self.old_code)
        self.camera.refresh_from_db()
        self.client.force_login(self.owner)
        self.url = reverse('pairing-code-regenerate', kwargs={'pk': self.camera.pk})

    def grant(self, generation=None):
        context = self.client.get(reverse('camera-monitor')).context['browser_camera_context']
        query = {'camera': str(self.camera.pk)}
        if generation is not None:
            query['pairing_version'] = generation
        return self.client.get(reverse('browser-camera-context'), query, HTTP_X_SENTINELLE_CAMERA_CONTEXT=context)

    def test_replacement_immediately_invalidates_old_identity_and_issues_one_new_code(self):
        self.assertEqual(self.grant().status_code, 200)
        pairing, code = create_pairing_code(self.camera, replace_existing=True)
        self.camera.refresh_from_db()
        self.assertEqual(self.camera.statut_appairage, StatutAppairage.NON_APPAIREE)
        self.assertEqual(self.camera.version_jeton, 2)
        self.assertIsNone(self.camera.identifiant_appareil)
        self.assertEqual(self.camera.secret_appareil_hash, '')
        self.assertIsNone(self.camera.cle_signature_evenement_chiffree)
        self.assertIsNone(self.camera.nonce_cle_signature_evenement)
        with self.assertRaises(InvalidCameraToken):
            authenticate_camera_token(self.old.access_token)
        with self.assertRaises(PairingError):
            renew_camera_token(self.old.device_id, self.old.device_secret)
        with self.assertRaises(PairingError):
            consume_pairing_code(self.old_code)
        self.assertEqual(self.grant(1).status_code, 404)
        self.assertRegex(code, r'^\d{6}$')
        self.assertEqual(CodeAppairage.objects.filter(camera=self.camera, utilise=False).count(), 1)
        self.assertFalse(pairing.utilise)

    def test_old_browser_cannot_refresh_after_new_device_is_paired(self):
        old_browser = self.grant().json()['access_token']
        _, code = create_pairing_code(self.camera, replace_existing=True)
        new = consume_pairing_code(code, user=self.owner)
        self.assertNotEqual(new.device_id, self.old.device_id)
        self.assertNotEqual(new.device_secret, self.old.device_secret)
        self.assertNotEqual(new.event_signing_key, self.old.event_signing_key)
        for token in (self.old.access_token, old_browser):
            with self.assertRaises(InvalidCameraToken):
                authenticate_camera_token(token)
        for generation in (None, '1', '0', 'bad', '02'):
            response = self.grant(generation)
            self.assertEqual(response.status_code, 409)
            self.assertIn('no-store', response['Cache-Control'])
            self.assertNotIn('access_token', response.json())
        current = self.grant('2')
        self.assertEqual(current.status_code, 200)
        authenticate_camera_token(current.json()['access_token'])
        renew_camera_token(new.device_id, new.device_secret)

    def test_new_browser_receives_current_generation_without_device_secrets(self):
        _, code = create_pairing_code(self.camera, replace_existing=True)
        response = self.client.post(reverse('connect-camera'), {'code': code})
        self.assertTrue(response.context['paired'])
        self.assertEqual(response.context['device_credentials'], {'cameraId': str(self.camera.pk), 'pairingVersion': 2})
        self.assertIn('no-store', response['Cache-Control'])

    def test_owner_gets_replacement_notice_no_store_and_redacted_audit(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['pairing_replaced'])
        self.assertContains(response, 'L’ancien appairage a été remplacé.')
        self.assertIn('no-store', response['Cache-Control'])
        audit = JournalAudit.objects.get(action='camera.pairing_code.regenerated')
        self.assertNotIn(response.context['plain_code'], str(audit.metadonnees))
        self.assertNotIn(self.old.device_secret, str(audit.metadonnees))

    def test_get_does_not_replace_any_pairing(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        authenticate_camera_token(self.old.access_token)

    def test_csrf_missing_does_not_replace_any_pairing(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.owner)
        self.assertEqual(strict.post(self.url).status_code, 403)
        authenticate_camera_token(self.old.access_token)

    def test_other_owner_and_member_with_control_cannot_replace_pairing(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(self.url).status_code, 404)
        member = MembreMaison.objects.create(maison=self.house, utilisateur=self.other, role=RoleMaison.FAMILLE, statut=StatutInvitation.ACCEPTEE)
        AccesCamera.objects.create(camera=self.camera, membre=member, peut_voir=True, peut_controler=True)
        self.assertEqual(self.client.post(self.url).status_code, 404)
        self.assertNotContains(self.client.get(reverse('camera-detail', kwargs={'pk': self.camera.pk})), 'Régénérer le code d’appairage')
        authenticate_camera_token(self.old.access_token)

    def test_revoked_camera_is_not_reactivated(self):
        revoke_camera(self.camera)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.camera.refresh_from_db()
        self.assertEqual(self.camera.statut_appairage, StatutAppairage.REVOQUEE)
        self.assertFalse(CodeAppairage.objects.filter(camera=self.camera, utilise=False).exists())

    def test_generation_failure_rolls_back_old_pairing(self):
        with patch('homes.services.secrets.randbelow', return_value=int(self.old_code)):
            with self.assertRaises(PairingError):
                create_pairing_code(self.camera, replace_existing=True)
        self.camera.refresh_from_db()
        self.assertEqual(self.camera.version_jeton, 1)
        self.assertEqual(self.camera.statut_appairage, StatutAppairage.APPAIREE)
        authenticate_camera_token(self.old.access_token)
        renew_camera_token(self.old.device_id, self.old.device_secret)

    def test_previously_used_code_is_never_reissued(self):
        different = '654321' if self.old_code != '654321' else '123456'
        with patch('homes.services.secrets.randbelow', side_effect=[int(self.old_code), int(different)]):
            _, code = create_pairing_code(self.camera, replace_existing=True)
        self.assertEqual(code, different)
        with self.assertRaises(PairingError):
            consume_pairing_code(self.old_code)
        consume_pairing_code(code)

    def test_second_replacement_invalidates_pending_code(self):
        pending, first = create_pairing_code(self.camera, replace_existing=True)
        _, second = create_pairing_code(self.camera, replace_existing=True)
        pending.refresh_from_db()
        self.assertTrue(pending.utilise)
        with self.assertRaises(PairingError):
            consume_pairing_code(first)
        current = consume_pairing_code(second)
        self.assertEqual(current.camera.version_jeton, 3)
        self.assertEqual(self.grant(2).status_code, 409)
        self.assertEqual(self.grant(3).status_code, 200)

    def test_source_settings_are_kept_but_old_connection_acknowledgement_is_cleared(self):
        self.camera.type_source = 'rtsp'
        self.camera.configuration_source_chiffree = b'encrypted-fixture'
        self.camera.nonce_configuration_source = b'x' * 12
        self.camera.derniere_connexion = timezone.now()
        self.camera.surveillance_appliquee = True
        self.camera.surveillance_appliquee_le = timezone.now()
        self.camera.version_planning_appliquee = 'old-planning'
        self.camera.zone_analyse = {'x': 0.1, 'y': 0.1, 'width': 0.7, 'height': 0.7}
        self.camera.save()
        create_pairing_code(self.camera, replace_existing=True)
        self.camera.refresh_from_db()
        self.assertEqual(self.camera.type_source, 'rtsp')
        self.assertEqual(bytes(self.camera.configuration_source_chiffree), b'encrypted-fixture')
        self.assertTrue(self.camera.surveillance_active)
        self.assertEqual(self.camera.zone_analyse['x'], 0.1)
        self.assertIsNone(self.camera.derniere_connexion)
        self.assertIsNone(self.camera.date_appairage)
        self.assertIsNone(self.camera.surveillance_appliquee)
        self.assertIsNone(self.camera.surveillance_appliquee_le)
        self.assertEqual(self.camera.version_planning_appliquee, '')

    def test_rate_limit_refuses_replacement_without_disconnect(self):
        from django.test import override_settings
        from django.conf import settings
        with override_settings(RATE_LIMITS={**settings.RATE_LIMITS, 'pairing_code': (0, 60)}):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response)
        authenticate_camera_token(self.old.access_token)

    def test_owner_button_is_visible_for_paired_camera_and_absent_when_revoked(self):
        detail = reverse('camera-detail', kwargs={'pk': self.camera.pk})
        response = self.client.get(detail)
        self.assertContains(response, 'Régénérer le code d’appairage')
        self.assertContains(response, self.url)
        self.assertContains(response, 'L’ancien appareil sera déconnecté.')
        revoke_camera(self.camera)
        self.assertNotContains(self.client.get(detail), 'Régénérer le code d’appairage')
