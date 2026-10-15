from django.test import TestCase
from django.urls import reverse

from accounts.mobile_security import issue_session_tokens
from accounts.models import User
from homes.models import Maison, MembreMaison, RoleMaison, StatutInvitation


class MobileHouseManagementTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('house-owner', 'owner-house@example.test', 'Test!2026')
        self.member = User.objects.create_user('house-member', 'member-house@example.test', 'Test!2026')
        self.house = Maison.objects.create(nom='Maison', proprietaire=self.owner)
        _, token, _ = issue_session_tokens(self.owner, device_id='owner-phone', device_name='Phone')
        self.auth = {'HTTP_AUTHORIZATION': f'Bearer {token}'}
        _, token, _ = issue_session_tokens(self.member, device_id='member-phone', device_name='Phone')
        self.member_auth = {'HTTP_AUTHORIZATION': f'Bearer {token}'}
        self.url = reverse('mobile-api:house-detail', args=[self.house.pk])

    def test_create_assigns_authenticated_owner_and_trims_name(self):
        response = self.client.post(reverse('mobile-api:house-list'), {
            'nom': ' Nouvelle maison ', 'proprietaire': self.member.pk,
            'fuseau_horaire': 'Africa/Lubumbashi',
        }, content_type='application/json', **self.auth)
        self.assertEqual(response.status_code, 201)
        house = Maison.objects.get(pk=response.json()['id'])
        self.assertEqual(house.proprietaire, self.owner)
        self.assertEqual(house.nom, 'Nouvelle maison')
        self.assertEqual(response.json()['role'], 'owner')

    def test_owner_updates_without_transferring_ownership(self):
        response = self.client.post(self.url, {'nom': 'Nouveau nom', 'proprietaire': self.member.pk},
                                    content_type='application/json', **self.auth)
        self.assertEqual(response.status_code, 200)
        self.house.refresh_from_db()
        self.assertEqual(self.house.nom, 'Nouveau nom')
        self.assertEqual(self.house.proprietaire, self.owner)

    def test_member_can_read_but_not_modify(self):
        MembreMaison.objects.create(maison=self.house, utilisateur=self.member,
                                   role=RoleMaison.FAMILLE, statut=StatutInvitation.ACCEPTEE)
        self.assertEqual(self.client.get(self.url, **self.member_auth).status_code, 200)
        self.assertEqual(self.client.post(self.url, {'nom': 'Interdit'},
                         content_type='application/json', **self.member_auth).status_code, 403)

    def test_outsider_cannot_modify_or_discover_house(self):
        self.assertEqual(self.client.post(self.url, {'nom': 'Interdit'},
                         content_type='application/json', **self.member_auth).status_code, 404)

    def test_invalid_input_does_not_write(self):
        for data in ({'nom': ' '}, {'nom': 'x' * 121}, {'fuseau_horaire': 'Wrong/Zone'}):
            with self.subTest(data=data):
                self.assertEqual(self.client.post(self.url, data, content_type='application/json',
                                                 **self.auth).status_code, 400)
        self.house.refresh_from_db()
        self.assertEqual(self.house.nom, 'Maison')

    def test_anonymous_creation_is_rejected(self):
        self.assertEqual(self.client.post(reverse('mobile-api:house-list'), {'nom': 'Maison'},
                                         content_type='application/json').status_code, 401)
