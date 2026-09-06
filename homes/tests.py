from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from .models import AccesCamera, Camera, Maison, MembreMaison, RoleMaison, StatutInvitation


class HomeAndCameraPermissionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner_a = User.objects.create_user("owner-a", "a@example.test", "Secret!2026")
        cls.owner_b = User.objects.create_user("owner-b", "b@example.test", "Secret!2026")
        cls.family = User.objects.create_user("family", "family@example.test", "Secret!2026")
        cls.guest = User.objects.create_user("guest", "guest@example.test", "Secret!2026")
        cls.house_a = Maison.objects.create(nom="Maison A", proprietaire=cls.owner_a)
        cls.house_b = Maison.objects.create(nom="Maison B", proprietaire=cls.owner_b)
        cls.camera_a = Camera.objects.create(nom="Salon A", maison=cls.house_a)
        cls.camera_b = Camera.objects.create(nom="Salon B", maison=cls.house_b)
        cls.family_membership = MembreMaison.objects.create(
            maison=cls.house_a,
            utilisateur=cls.family,
            role=RoleMaison.FAMILLE,
            statut=StatutInvitation.ACCEPTEE,
        )
        MembreMaison.objects.create(
            maison=cls.house_a,
            utilisateur=cls.guest,
            role=RoleMaison.INVITE,
            statut=StatutInvitation.ACCEPTEE,
        )
        AccesCamera.objects.create(membre=cls.family_membership, camera=cls.camera_a)

    def test_house_creation_makes_request_user_owner_and_member(self):
        self.client.force_login(self.owner_a)
        response = self.client.post(reverse("maison-create"), {"nom": "Nouvelle maison"})

        self.assertRedirects(response, reverse("maison-list"))
        house = Maison.objects.get(nom="Nouvelle maison")
        self.assertEqual(house.proprietaire, self.owner_a)
        membership = house.membres.get(utilisateur=self.owner_a)
        self.assertEqual(membership.role, RoleMaison.PROPRIETAIRE)
        self.assertEqual(membership.statut, StatutInvitation.ACCEPTEE)

    def test_roles_have_expected_camera_visibility(self):
        self.assertQuerySetEqual(Camera.objects.visible_to(self.owner_a), [self.camera_a])
        self.assertQuerySetEqual(Camera.objects.visible_to(self.family), [self.camera_a])
        self.assertFalse(Camera.objects.visible_to(self.guest).exists())
        self.assertFalse(Camera.objects.visible_to(self.owner_b).filter(pk=self.camera_a.pk).exists())

    def test_user_cannot_read_another_users_camera_by_changing_url(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("camera-detail", kwargs={"pk": self.camera_b.pk}))

        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "Salon B", status_code=404)

    def test_api_filters_and_rejects_foreign_camera_identifier(self):
        self.client.force_login(self.owner_a)
        listing = self.client.get(reverse("api:camera-list"))
        foreign_detail = self.client.get(
            reverse("api:camera-detail", kwargs={"pk": self.camera_b.pk})
        )

        self.assertEqual(listing.status_code, 200)
        ids = {item["id"] for item in listing.json()}
        self.assertEqual(ids, {str(self.camera_a.pk)})
        self.assertEqual(foreign_detail.status_code, 404)

    def test_member_with_view_access_cannot_control_camera(self):
        self.client.force_login(self.family)
        response = self.client.post(reverse("camera-toggle", kwargs={"pk": self.camera_a.pk}))

        self.assertEqual(response.status_code, 403)
        self.camera_a.refresh_from_db()
        self.assertFalse(self.camera_a.surveillance_active)

    def test_owner_can_toggle_own_camera(self):
        self.client.force_login(self.owner_a)
        response = self.client.post(reverse("camera-toggle", kwargs={"pk": self.camera_a.pk}))

        self.assertRedirects(response, reverse("camera-detail", kwargs={"pk": self.camera_a.pk}))
        self.camera_a.refresh_from_db()
        self.assertTrue(self.camera_a.surveillance_active)

    def test_camera_form_rejects_house_owned_by_another_user(self):
        self.client.force_login(self.owner_a)
        response = self.client.post(
            reverse("camera-create"), {"nom": "Caméra injectée", "maison": self.house_b.pk}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sélectionnez un choix valide")
        self.assertFalse(Camera.objects.filter(nom="Caméra injectée").exists())

    @override_settings(DEBUG=False)
    def test_404_page_does_not_leak_debug_information(self):
        response = self.client.get("/ressource-inexistante/")

        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "Traceback", status_code=404)
        self.assertNotContains(response, "DJANGO_SECRET_KEY", status_code=404)
