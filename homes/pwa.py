from django.http import JsonResponse
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView


def manifest(request):
    return JsonResponse({
        "id": "/", "name": "Sentinelle Maison", "short_name": "Sentinelle",
        "lang": "fr", "start_url": reverse("dashboard"), "scope": "/",
        "display": "standalone", "background_color": "#f2f6f5", "theme_color": "#23484c",
        "prefer_related_applications": False,
        "icons": [
            {"src": static(f"icons/sentinelle-{size}.png"), "sizes": f"{size}x{size}",
             "type": "image/png", "purpose": "any"} for size in (192, 512)
        ] + [
            {"src": static(f"icons/sentinelle-maskable-{size}.png"), "sizes": f"{size}x{size}",
             "type": "image/png", "purpose": "maskable"} for size in (192, 512)
        ],
        "shortcuts": [
            {"name": "Caméras", "url": reverse("camera-list")},
            {"name": "Alertes", "url": reverse("event-list")},
            {"name": "Maisons", "url": reverse("maison-list")},
        ],
    }, content_type="application/manifest+json")


service_worker = never_cache(TemplateView.as_view(
    template_name="pwa/service-worker.js", content_type="application/javascript"))
offline = TemplateView.as_view(template_name="pwa/offline.html")
