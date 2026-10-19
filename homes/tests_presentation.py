import os
import uuid
from pathlib import Path
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.mfa import VERIFIED_USER_KEY, generate_secret
from accounts.models import MFADevice, User
from .models import Camera, Evenement, Maison
from .templatetags.presentation import camera_summary, event_summary


class PresentationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('demo', email='demo@example.test')
        cls.house = Maison.objects.create(nom='Maison de démonstration', proprietaire=cls.user)
        cls.camera = Camera.objects.create(nom='Entrée', maison=cls.house, statut_appairage='paired')
        cls.event = Evenement.objects.create(client_event_id=uuid.uuid4(), camera=cls.camera,
            maison=cls.house, type='person_detected', confiance_ia=.9, notification_supprimee=True,
            metadonnees={'alerte': {'notification_supprimee': True},
                         'regle': {'id': 'presence-zone', 'type': 'presence_prolonged', 'version': 1}})
        device = MFADevice(user=cls.user, confirmed_at=timezone.now())
        device.set_secret(generate_secret())
        device.save()

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session[VERIFIED_USER_KEY] = self.user.pk
        session.save()

    def test_recognized_presence_is_history_not_pending_alert(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['alertes_nouvelles'], 0)
        self.assertContains(response, 'Personne reconnue')
        self.assertContains(response, 'Sans alerte')
        response = self.client.get(reverse('event-detail', args=[self.event.pk]))
        self.assertContains(response, 'Non envoyée')
        self.assertContains(response, 'Non demandée')
        self.assertNotContains(response, 'Confirmer l’intrusion')
        self.assertNotContains(response, 'La surveillance reste active')
        if os.environ.get('MOBILE_WEB_ARTIFACTS'):
            directory = Path(os.environ['MOBILE_WEB_ARTIFACTS'])
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'recognized.html').write_bytes(response.content)

    def test_crossing_and_unknown_still_need_review(self):
        self.event.notification_supprimee = False
        self.event.metadonnees = {'regle': {'type': 'line_crossing'},
                                 'identite_locale': {'statut': 'recognized'}}
        self.event.save()
        response = self.client.get(reverse('event-detail', args=[self.event.pk]))
        self.assertContains(response, 'Passage détecté')
        self.assertContains(response, 'Confirmer l’intrusion')
        self.assertNotContains(response, 'Non envoyée')
        self.assertEqual(self.client.get(reverse('dashboard')).context['alertes_nouvelles'], 1)
        self.event.metadonnees = {}
        self.assertFalse(event_summary(self.event)['quiet'])

    def test_grouping_does_not_imply_face_recognition(self):
        self.event.metadonnees = {}
        self.event.save()
        response = self.client.get(reverse('event-list'))
        self.assertContains(response, 'Regroupé')
        self.assertNotContains(response, 'Personne reconnue')
        self.assertFalse(event_summary(self.event)['quiet'])

    def test_network_camera_errors_remain_visible(self):
        response = self.client.post(reverse('camera-create'), {
            'maison': self.house.pk, 'nom': 'Jardin', 'type_source': 'rtsp', 'adresse_rtsp': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<details class="disclosure" open>')
        self.assertContains(response, 'L’adresse RTSP est obligatoire.')
        self.assertFalse(Camera.objects.filter(nom='Jardin').exists())

    def test_camera_state_needs_recent_confirmation(self):
        self.camera.surveillance_active = True
        self.camera.derniere_connexion = timezone.now() - timedelta(minutes=10)
        self.camera.surveillance_appliquee = True
        self.camera.surveillance_appliquee_le = timezone.now()
        self.assertEqual(camera_summary(self.camera), 'Hors ligne')
        self.camera.derniere_connexion = timezone.now()
        self.camera.surveillance_appliquee = False
        self.assertEqual(camera_summary(self.camera), 'Mise à jour en cours')
        self.camera.surveillance_appliquee = True
        self.assertEqual(camera_summary(self.camera), 'Surveillance active')
        self.camera.statut_appairage = 'revoked'
        self.assertEqual(camera_summary(self.camera), 'Accès retiré')
