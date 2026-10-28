from django.urls import path
from . import views

app_name = "mapper"

urlpatterns = [
    # --- Spatial filter endpoints (must come before <pk> to avoid collision) ---
    path("pins/nearest/", views.pins_nearest, name="pin-nearest"),
    path("pins/within/", views.pins_within, name="pin-within"),

    # --- SafetyPin CRUD ---
    path("pins/", views.SafetyPinListCreateView.as_view(), name="pin-list-create"),
    path("pins/<int:pk>/", views.SafetyPinDetailView.as_view(), name="pin-detail"),

    # --- CityBoundary ---
    path("boundaries/", views.CityBoundaryListView.as_view(), name="boundary-list"),
]
