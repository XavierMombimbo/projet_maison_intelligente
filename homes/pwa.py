from django.http import JsonResponse
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView


def manifest(request):
    return JsonResponse({
        "id": "/", "name": "Sentinelle Maison", "short_name": "Sentinelle",
        "lang": "fr", "start_url": reverse("dashboard"), "scope": "/",
        "display": "standalone", "background_color": "#f2f6f5", "theme_color": "#0f172a",
        "prefer_related_applications": False,
        "icons": [{"src": static("icons/sentinelle.svg"), "sizes": "192x192 512x512 any",
                   "type": "image/svg+xml", "purpose": "any"}],
        "shortcuts": [
            {"name": "Caméras", "url": reverse("camera-list")},
            {"name": "Alertes", "url": reverse("event-list")},
            {"name": "Maisons", "url": reverse("maison-list")},
        ],
    }, content_type="application/manifest+json")


service_worker = never_cache(TemplateView.as_view(
    template_name="pwa/service-worker.js", content_type="application/javascript"))
offline = TemplateView.as_view(template_name="pwa/offline.html")
