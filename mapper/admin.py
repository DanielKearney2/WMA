from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from .models import CityBoundary, SafetyPin


@admin.register(CityBoundary)
class CityBoundaryAdmin(GISModelAdmin):
    list_display = ["name", "created_at", "updated_at"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(SafetyPin)
class SafetyPinAdmin(GISModelAdmin):
    list_display = ["title", "category", "created_at", "updated_at"]
    list_filter = ["category", "created_at"]
    search_fields = ["title", "description"]
    readonly_fields = ["buffer_geom", "created_at", "updated_at"]
