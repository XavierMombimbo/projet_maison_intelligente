from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse


class SourceNoticeTests(SimpleTestCase):
    def test_source_offer_is_absent_until_revision_is_published(self):
        with patch.dict("os.environ", {"SENTINELLE_SOURCE_REVISION": ""}):
            response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, ">Code source</a>")

    def test_source_offer_points_to_exact_revision(self):
        revision = "a" * 40
        with patch.dict("os.environ", {"SENTINELLE_SOURCE_REVISION": revision}):
            response = self.client.get(reverse("login"))
        self.assertContains(
            response,
            f"https://github.com/XavierMombimbo/projet_maison_intelligente/archive/{revision}.zip",
        )
        self.assertContains(response, ">Code source</a>")

    def test_invalid_revision_cannot_create_arbitrary_link(self):
        with patch.dict("os.environ", {"SENTINELLE_SOURCE_REVISION": "javascript:alert(1)"}):
            response = self.client.get(reverse("login"))
        self.assertNotContains(response, ">Code source</a>")
