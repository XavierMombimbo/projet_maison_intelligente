from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class MobileAPITestView(LoginRequiredMixin, TemplateView):
    template_name = "registration/mobile_api_test.html"
