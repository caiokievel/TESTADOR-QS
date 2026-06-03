from __future__ import annotations

from django.urls import include, path


urlpatterns = [
    path("", include("exam_simulator.webapp.urls")),
]
