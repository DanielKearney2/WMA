"""
URL configuration for the mapper app API.

Mounted at /api/v1/ in config/urls.py.

Endpoints:
  GET  /api/v1/pins/                            – all pins (+ optional ?category= / ?bbox= filters)
  POST /api/v1/pins/                            – create a pin
  GET  /api/v1/pins/<id>/                       – single pin
  DELETE /api/v1/pins/<id>/                     – delete pin
  GET  /api/v1/pins/nearest/?lat=&lon=&limit=   – KNN nearest (SPEC Q1)
  GET  /api/v1/pins/within/?lat=&lon=&radius_m= – radius search (SPEC Q2)
  GET  /api/v1/boundaries/                      – city boundary polygons
"""

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
