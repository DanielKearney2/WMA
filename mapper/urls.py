from django.urls import path
from . import views

app_name = "mapper"

urlpatterns = [
    # Spatial filter endpoints must precede <int:pk> to avoid route collision
    path("pins/nearest/", views.pins_nearest, name="pin-nearest"),
    path("pins/within/", views.pins_within, name="pin-within"),
    path("pins/", views.HazardPinListCreateView.as_view(), name="pin-list-create"),
    path("pins/<int:pk>/", views.HazardPinDetailView.as_view(), name="pin-detail"),
    path("cities/", views.CityListView.as_view(), name="city-list"),
]
