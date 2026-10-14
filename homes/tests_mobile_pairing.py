from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.mobile_security import issue_session_tokens
from accounts.models import User
from homes.models import (AccesCamera, Camera, CodeAppairage, JournalAudit, Maison,
                          MembreMaison, RoleMaison, StatutAppairage, StatutInvitation)
from homes.security import hash_pairing_code
from homes.services import PairingError, consume_pairing_code
from homes.throttling import RateLimitResult


class MobilePairingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user('pair-owner', 'pair@example.test', 'Test!2026')
        self.other = User.objects.create_user('pair-other', 'other@example.test', 'Test!2026')
        self.house = Maison.objects.create(nom='Maison', proprietaire=self.owner)
        self.camera = Camera.objects.create(nom='Entree', maison=self.house)
        _, token, _ = issue_session_tokens(self.owner, device_id='phone', device_name='Phone')
        self.auth = {'HTTP_AUTHORIZATION': f'Bearer {token}'}
        _, token, _ = issue_session_tokens(self.other, device_id='other', device_name='Other')
        self.other_auth = {'HTTP_AUTHORIZATION': f'Bearer {token}'}
        self.url = reverse('mobile-api:camera-pairing-code', args=[self.camera.pk])

    def post(self):
        return self.client.post(self.url, {}, content_type='application/json', **self.auth)

    def test_code_is_hashed_short_lived_and_response_not_cached(self):
        response = self.post()
        self.assertEqual(response.status_code, 201)
        self.assertIn('no-store', response['Cache-Control'])
        data = response.json()
        self.assertEqual(set(data), {'code', 'expires_at'})
        self.assertRegex(data['code'], r'^\d{6}$')
        stored = CodeAppairage.objects.get(camera=self.camera)
        self.assertEqual(stored.code_hash, hash_pairing_code(data['code']))
        self.assertLessEqual(stored.date_expiration, timezone.now() + timedelta(minutes=5))
        self.assertGreater(stored.date_expiration, timezone.now() + timedelta(minutes=4))
        self.assertNotIn(data['code'], str(list(JournalAudit.objects.values())))

    def test_replacement_invalidates_previous_code_and_existing_gateway_can_consume(self):
        first = self.post().json()['code']
        second = self.post().json()['code']
        with self.assertRaises(PairingError):
            consume_pairing_code(first)
        response = self.client.post(reverse('api-camera-pair'), {'code': second},
                                    content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['camera_id'], str(self.camera.pk))
        self.assertEqual(self.post().status_code, 409)
        with self.assertRaises(PairingError):
            consume_pairing_code(second)

    def test_expired_code_rejected(self):
        code = self.post().json()['code']
        CodeAppairage.objects.filter(camera=self.camera).update(date_expiration=timezone.now())
        with self.assertRaises(PairingError):
            consume_pairing_code(code)

    def test_member_even_with_control_cannot_generate(self):
        member = MembreMaison.objects.create(maison=self.house, utilisateur=self.other,
            role=RoleMaison.FAMILLE, statut=StatutInvitation.ACCEPTEE)
        AccesCamera.objects.create(camera=self.camera, membre=member, peut_voir=True, peut_controler=True)
        response = self.client.post(self.url, {}, content_type='application/json', **self.other_auth)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(CodeAppairage.objects.exists())

    def test_anonymous_outsider_and_revoked_rejected(self):
        self.assertEqual(self.client.post(self.url).status_code, 401)
        self.assertEqual(self.client.post(self.url, **self.other_auth).status_code, 404)
        self.camera.statut_appairage = StatutAppairage.REVOQUEE
        self.camera.save()
        self.assertEqual(self.post().status_code, 409)
        self.assertFalse(CodeAppairage.objects.exists())

    @patch('homes.mobile_api.check_rate_limit', return_value=RateLimitResult(False, 30, 5, 6))
    def test_rate_limit_does_not_create_or_invalidate_code(self, limiter):
        response = self.post()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response['Retry-After'], '30')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertFalse(CodeAppairage.objects.exists())
        self.assertEqual(limiter.call_args.kwargs['identifier'], f'{self.owner.pk}:{self.camera.pk}')
