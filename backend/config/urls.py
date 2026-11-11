from django.urls import include, path
from django.http import JsonResponse

urlpatterns = [
    path("health/", lambda request: JsonResponse({"status": "ok"})),
    path("api/", include("backend.runs.urls")),
]
