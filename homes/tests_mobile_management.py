import uuid

from django.test import TestCase
from django.urls import reverse

from accounts.mobile_security import issue_session_tokens
from accounts.models import User
from homes.models import (Maison, Camera, MembreMaison, AccesCamera, PlageSurveillance,
                          ExceptionSurveillance, DerogationSurveillance, StatutInvitation)
from notifications.models import CameraPushPreference


class MobileManagementTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('manage-owner', 'owner@example.test', 'Test!2026')
        self.guest = User.objects.create_user('manage-guest', 'guest@example.test', 'Test!2026')
        self.house = Maison.objects.create(nom='Maison', proprietaire=self.owner)
        self.other = Maison.objects.create(nom='Autre', proprietaire=self.guest)
        self.camera = Camera.objects.create(nom='Camera', maison=self.house)
        self.foreign_camera = Camera.objects.create(nom='Autre camera', maison=self.other)
        self.auth = self.token(self.owner)
        self.guest_auth = self.token(self.guest)
        self.schedule = reverse('mobile-api:house-schedule', args=[self.house.pk])
        self.members = reverse('mobile-api:house-members', args=[self.house.pk])
        self.preferences = reverse('mobile-api:camera-preferences', args=[self.camera.pk])
        self.invitations = reverse('mobile-api:invitations')

    def token(self, user):
        _, token, _ = issue_session_tokens(user, device_id=str(user.pk), device_name='Phone')
        return {'HTTP_AUTHORIZATION': f'Bearer {token}'}

    def post(self, url, data, auth=None):
        return self.client.post(url, data, content_type='application/json', **(auth or self.auth))

    def invite(self):
        response = self.post(self.members, {'action': 'invite', 'username': self.guest.username,
            'role': 'family', 'access': [{'camera_id': str(self.camera.pk), 'peut_voir': True, 'peut_controler': True}],
            'statut': 'accepted', 'permissions': ['owner']})
        self.assertEqual(response.status_code, 200, response.content)
        return MembreMaison.objects.get(maison=self.house, utilisateur=self.guest)

    def test_daily_replacement_and_clear_preserve_advanced_windows(self):
        window = PlageSurveillance.objects.create(maison=self.house, nom='Weekend', jour=6,
            heure_debut='12:00', heure_fin='13:00')
        for start in ('20:00', '21:00'):
            response = self.post(self.schedule, {'action': 'daily', 'heure_activation': start, 'heure_arret': '06:00'})
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(self.house.plages_surveillance.filter(nom='Planning quotidien').count(), 7)
        self.assertEqual(self.post(self.schedule, {'action': 'daily_clear'}).status_code, 200)
        self.assertEqual(list(self.house.plages_surveillance.values_list('pk', flat=True)), [window.pk])

    def test_invalid_daily_and_collision_roll_back(self):
        PlageSurveillance.objects.create(maison=self.house, nom='Advanced', jour=0,
            heure_debut='20:00', heure_fin='06:00')
        for start, end in [('08:00', '08:00'), ('invalid', '10:00'), ('20:00', '06:00')]:
            response = self.post(self.schedule, {'action': 'daily', 'heure_activation': start, 'heure_arret': end})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.house.plages_surveillance.count(), 1)

    def test_weekly_crud_scoped_to_house(self):
        data = {'action': 'window', 'nom': 'Nuit', 'jour': 2, 'heure_debut': '21:00', 'heure_fin': '05:00', 'active': True}
        self.assertEqual(self.post(self.schedule, data).status_code, 200)
        window = self.house.plages_surveillance.get()
        self.assertEqual(self.post(self.schedule, {**data, 'id': window.pk, 'active': False}).status_code, 200)
        window.refresh_from_db()
        self.assertFalse(window.active)
        foreign = PlageSurveillance.objects.create(maison=self.other, nom='Foreign', jour=0,
            heure_debut='01:00', heure_fin='02:00')
        self.assertEqual(self.post(self.schedule, {**data, 'id': foreign.pk}).status_code, 404)
        self.assertEqual(self.post(self.schedule, {'action': 'window_delete', 'id': foreign.pk}).status_code, 404)
        self.assertEqual(self.post(self.schedule, {'action': 'window_delete', 'id': window.pk}).status_code, 200)

    def test_exception_validation_timezone_and_delete(self):
        data = {'action': 'exception', 'nom': 'Absence', 'date_debut': '2026-11-01T20:00',
                'date_fin': '2026-11-02T08:00', 'surveillance_active': True, 'priorite': 20}
        self.assertEqual(self.post(self.schedule, data).status_code, 200)
        item = ExceptionSurveillance.objects.get(maison=self.house)
        self.assertEqual(item.date_debut.hour, 19)  # Kinshasa local input, UTC database.
        self.assertEqual(self.post(self.schedule, {**data, 'id': item.pk, 'date_fin': '2026-10-01T08:00'}).status_code, 400)
        self.assertEqual(self.post(self.schedule, {'action': 'exception_delete', 'id': item.pk}).status_code, 200)

    def test_override_enforces_duration_and_clears(self):
        self.assertEqual(self.post(self.schedule, {'action': 'override', 'surveillance_active': False,
            'duree_minutes': 60}).status_code, 200)
        self.assertFalse(DerogationSurveillance.objects.get(maison=self.house).surveillance_active)
        self.assertEqual(self.post(self.schedule, {'action': 'override', 'surveillance_active': True,
            'duree_minutes': 99999}).status_code, 400)
        self.assertEqual(self.post(self.schedule, {'action': 'override_clear'}).status_code, 200)
        self.assertFalse(DerogationSurveillance.objects.filter(maison=self.house).exists())

    def test_pending_invitation_does_not_grant_access_and_accept_is_personal(self):
        member = self.invite()
        self.assertEqual(member.statut, StatutInvitation.EN_ATTENTE)
        self.assertEqual(member.permissions, [])
        self.assertFalse(Camera.objects.visible_to(self.guest).filter(pk=self.camera.pk).exists())
        self.assertEqual(self.client.get(self.invitations, **self.guest_auth).json()['invitations'][0]['id'], member.pk)
        self.assertEqual(self.post(self.invitations, {'id': member.pk, 'action': 'accept'}).status_code, 404)
        self.assertEqual(self.post(self.invitations, {'id': member.pk, 'action': 'accept'}, self.guest_auth).status_code, 200)
        self.assertTrue(Camera.objects.visible_to(self.guest).filter(pk=self.camera.pk).exists())
        self.assertTrue(Camera.objects.controllable_by(self.guest).filter(pk=self.camera.pk).exists())
        self.assertEqual(self.post(self.invitations, {'id': member.pk, 'action': 'accept'}, self.guest_auth).status_code, 404)

    def test_refusal_and_removal(self):
        member = self.invite()
        self.assertEqual(self.post(self.invitations, {'id': member.pk, 'action': 'refuse'}, self.guest_auth).status_code, 200)
        self.assertFalse(Maison.objects.visible_to(self.guest).filter(pk=self.house.pk).exists())
        self.assertEqual(self.post(self.members, {'action': 'remove', 'id': member.pk}).status_code, 200)
        self.assertFalse(AccesCamera.objects.filter(membre_id=member.pk).exists())

    def test_owner_immutable_and_role_escalation_rejected(self):
        owner_member = self.house.membres.get(utilisateur=self.owner)
        for action in ('remove', 'update'):
            self.assertEqual(self.post(self.members, {'action': action, 'id': owner_member.pk, 'role': 'guest'}).status_code, 400)
        self.assertEqual(self.post(self.members, {'action': 'invite', 'username': self.guest.username, 'role': 'owner'}).status_code, 400)
        self.assertFalse(self.house.membres.filter(utilisateur=self.guest).exists())

    def test_member_cannot_manage_or_write_schedule(self):
        member = self.invite()
        self.post(self.invitations, {'id': member.pk, 'action': 'accept'}, self.guest_auth)
        self.assertEqual(self.client.get(self.members, **self.guest_auth).status_code, 404)
        self.assertEqual(self.post(self.members, {'action': 'remove', 'id': member.pk}, self.guest_auth).status_code, 404)
        result = self.client.get(self.schedule, **self.guest_auth)
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json()['can_edit'])
        self.assertEqual(self.post(self.schedule, {'action': 'daily_clear'}, self.guest_auth).status_code, 404)

    def test_camera_access_scoping_and_atomicity(self):
        member = self.invite()
        for access in ([{'camera_id': str(self.foreign_camera.pk), 'peut_voir': True, 'peut_controler': False}],
                       [{'camera_id': str(self.camera.pk), 'peut_voir': False, 'peut_controler': True}]):
            response = self.post(self.members, {'action': 'update', 'id': member.pk, 'role': 'guest', 'access': access})
            self.assertEqual(response.status_code, 400)
        member.refresh_from_db()
        self.assertEqual(member.role, 'family')
        self.assertTrue(member.acces_cameras.get().peut_controler)
        self.assertEqual(self.post(self.members, {'action': 'update', 'id': member.pk,
            'role': 'guest', 'access': []}).status_code, 200)
        self.assertFalse(member.acces_cameras.exists())

    def test_preferences_personal_and_quiet_validation(self):
        initial = self.client.get(self.preferences, **self.auth)
        self.assertTrue(initial.json()['enabled'])
        self.assertFalse(CameraPushPreference.objects.exists())
        payload = {'enabled': False, 'people': True, 'objects_enabled': False,
                   'quiet_start': '22:00', 'quiet_end': '06:00', 'urgent_during_quiet': True,
                   'user': self.guest.pk}
        self.assertEqual(self.post(self.preferences, payload).status_code, 200)
        self.assertEqual(CameraPushPreference.objects.get().user, self.owner)
        self.assertEqual(self.post(self.preferences, {**payload, 'quiet_end': None}).status_code, 400)
        self.assertEqual(self.post(self.preferences, {**payload, 'quiet_end': '22:00'}).status_code, 400)
        self.assertEqual(self.post(self.preferences, {**payload, 'quiet_start': None, 'quiet_end': None}).status_code, 200)
        self.assertIsNone(CameraPushPreference.objects.get().quiet_start)

    def test_lock_screen_validation_and_legacy_client_preserves_choice(self):
        payload = {'enabled': True, 'people': True, 'objects_enabled': True, 'urgent_during_quiet': False}
        self.assertEqual(self.client.get(self.preferences, **self.auth).json()['lock_screen'], 'private')
        for value in ('secret', 'public', 'private'):
            response = self.post(self.preferences, {**payload, 'lock_screen': value})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['lock_screen'], value)
        self.post(self.preferences, {**payload, 'lock_screen': 'secret'})
        self.assertEqual(self.post(self.preferences, payload).json()['lock_screen'], 'secret')
        self.assertEqual(self.post(self.preferences, {**payload, 'lock_screen': 'invalid'}).status_code, 400)
        self.assertEqual(CameraPushPreference.objects.get().lock_screen, 'secret')
        self.assertEqual(self.post(self.preferences, {**payload, 'lock_screen': 'public'}, self.guest_auth).status_code, 404)

    def test_notification_event_details_recheck_camera_access(self):
        from homes.models import Evenement, TypeEvenement
        event = Evenement.objects.create(client_event_id=uuid.uuid4(), camera=self.camera, maison=self.house,
            type=TypeEvenement.PERSONNE_DETECTEE, confiance_ia=0.9)
        url = f'/api/v1/events/{event.pk}/'
        self.assertEqual(self.client.get(url, **self.guest_auth).status_code, 404)
        member = self.invite()
        member.statut = StatutInvitation.ACCEPTEE
        member.save()
        self.assertEqual(self.client.get(url, **self.guest_auth).status_code, 200)
        AccesCamera.objects.filter(membre=member).delete()
        self.assertEqual(self.client.get(url, **self.guest_auth).status_code, 404)

    def test_preferences_require_camera_access_and_revocation_takes_effect(self):
        self.assertEqual(self.client.get(self.preferences, **self.guest_auth).status_code, 404)
        member = self.invite()
        self.post(self.invitations, {'id': member.pk, 'action': 'accept'}, self.guest_auth)
        self.assertEqual(self.client.get(self.preferences, **self.guest_auth).status_code, 200)
        self.post(self.members, {'action': 'remove', 'id': member.pk})
        self.assertEqual(self.client.get(self.preferences, **self.guest_auth).status_code, 404)
        self.assertFalse(Camera.objects.visible_to(self.guest).filter(pk=self.camera.pk).exists())

    def test_anonymous_endpoints_rejected(self):
        for url in (self.schedule, self.members, self.preferences, self.invitations):
            self.assertEqual(self.client.get(url).status_code, 401)
            self.assertEqual(self.client.post(url, {}, content_type='application/json').status_code, 401)
