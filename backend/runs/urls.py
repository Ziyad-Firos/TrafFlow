from django.urls import path

from backend.runs.views import NetworkDetailView, NetworkListView, RunDetailView, RunListCreateView, ScenarioListView

urlpatterns = [
    path("runs/", RunListCreateView.as_view(), name="runs"),
    path("runs/<uuid:run_id>/", RunDetailView.as_view(), name="run-detail"),
    path("networks/", NetworkListView.as_view(), name="networks"),
    path("networks/<str:network_id>/", NetworkDetailView.as_view(), name="network-detail"),
    path("scenarios/", ScenarioListView.as_view(), name="scenarios"),
]
