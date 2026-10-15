from django.test import TestCase
from django.urls import reverse

from accounts.mobile_security import issue_session_tokens
from accounts.models import User
from homes.crypto import decrypt_camera_source_config
from homes.models import AccesCamera, Camera, Maison, MembreMaison, RoleMaison, StatutInvitation, StatutAppairage


class MobileCameraManagementTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('camera-owner', 'cam-owner@example.test', 'Test!2026')
        self.member = User.objects.create_user('camera-member', 'cam-member@example.test', 'Test!2026')
        self.house = Maison.objects.create(nom='Maison', proprietaire=self.owner)
        self.other_house = Maison.objects.create(nom='Autre', proprietaire=self.member)
        MembreMaison.objects.create(maison=self.house, utilisateur=self.member,
                                   role=RoleMaison.FAMILLE, statut=StatutInvitation.ACCEPTEE)
        self.auth = self.token(self.owner)
        self.member_auth = self.token(self.member)
        self.url = reverse('mobile-api:camera-list')

    def token(self, user):
        _, access, _ = issue_session_tokens(user, device_id=str(user.pk), device_name='Phone')
        return {'HTTP_AUTHORIZATION': f'Bearer {access}'}

    def create(self, **extra):
        return self.client.post(self.url, {'maison': self.house.pk, 'nom': ' Entree ',
            'type_source': 'webcam', **extra}, content_type='application/json', **self.auth)

    def test_owner_creates_unpaired_inactive_webcam_without_injected_fields(self):
        response = self.create(surveillance_active=True, statut_appairage='paired')
        self.assertEqual(response.status_code, 201)
        camera = Camera.objects.get(pk=response.json()['id'])
        self.assertEqual(camera.nom, 'Entree')
        self.assertEqual(camera.statut_appairage, StatutAppairage.NON_APPAIREE)
        self.assertFalse(camera.surveillance_active)
        self.assertIsNone(camera.configuration_source_chiffree)

    def test_rtsp_secrets_encrypted_and_not_returned(self):
        response = self.create(type_source='rtsp', adresse_rtsp='rtsp://camera.local/live',
                               utilisateur_rtsp='private-user', mot_de_passe_rtsp='private-password')
        self.assertEqual(response.status_code, 201)
        camera = Camera.objects.get(pk=response.json()['id'])
        config = decrypt_camera_source_config(bytes(camera.configuration_source_chiffree),
                                              bytes(camera.nonce_configuration_source), camera.pk)
        self.assertEqual(config['password'], 'private-password')
        for url in (self.url, reverse('mobile-api:camera-detail', args=[camera.pk])):
            content = self.client.get(url, **self.auth).content.decode()
            for secret in ('private-user', 'private-password', 'camera.local', 'configuration_source_chiffree'):
                self.assertNotIn(secret, content)
        self.assertNotIn('private-password', response.content.decode())

    def test_invalid_source_data_does_not_create_camera(self):
        for data in ({'nom': ' '}, {'nom': 'x' * 121}, {'type_source': 'invalid'},
                     {'type_source': 'rtsp'}, {'adresse_rtsp': 'rtsp://camera/live'},
                     {'type_source': 'rtsp', 'adresse_rtsp': 'rtsp://user:pass@camera/live'}):
            with self.subTest(data=data):
                self.assertEqual(self.create(**data).status_code, 400)
        self.assertEqual(Camera.objects.count(), 0)

    def test_member_and_other_owner_cannot_create_in_house(self):
        response = self.client.post(self.url, {'maison': self.house.pk, 'nom': 'No',
            'type_source': 'webcam'}, content_type='application/json', **self.member_auth)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.create(maison=self.other_house.pk).status_code, 400)
        self.assertEqual(Camera.objects.count(), 0)

    def test_rename_preserves_house_source_and_pairing(self):
        camera = Camera.objects.create(maison=self.house, nom='Avant')
        url = reverse('mobile-api:camera-detail', args=[camera.pk])
        response = self.client.post(url, {'nom': ' Apres ', 'maison': self.other_house.pk,
            'type_source': 'rtsp', 'surveillance_active': True}, content_type='application/json', **self.auth)
        self.assertEqual(response.status_code, 200)
        camera.refresh_from_db()
        self.assertEqual(camera.nom, 'Apres')
        self.assertEqual(camera.maison, self.house)
        self.assertEqual(camera.type_source, 'webcam')
        self.assertFalse(camera.surveillance_active)
        AccesCamera.objects.create(camera=camera,
            membre=MembreMaison.objects.get(maison=self.house, utilisateur=self.member),
            peut_voir=True, peut_controler=True)
        self.assertEqual(self.client.post(url, {'nom': 'No'}, content_type='application/json',
                                         **self.member_auth).status_code, 403)

    def test_outsider_revoked_and_anonymous_rejected(self):
        camera = Camera.objects.create(maison=self.other_house, nom='Other')
        url = reverse('mobile-api:camera-detail', args=[camera.pk])
        self.assertEqual(self.client.post(url, {'nom': 'No'}, content_type='application/json',
                                         **self.auth).status_code, 404)
        camera.statut_appairage = StatutAppairage.REVOQUEE
        camera.save()
        self.assertEqual(self.client.post(url, {'nom': 'No'}, content_type='application/json',
                                         **self.member_auth).status_code, 409)
        self.assertEqual(self.client.post(self.url, {}, content_type='application/json').status_code, 401)
