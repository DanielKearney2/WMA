from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from .models import City, HazardPin


@admin.register(City)
class CityAdmin(GISModelAdmin):
    list_display = ["code", "name", "created_at", "updated_at"]
    search_fields = ["code", "name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(HazardPin)
class HazardPinAdmin(GISModelAdmin):
    list_display = ["id", "description", "owner_token", "expires_at", "created_at"]
    list_filter = ["expires_at", "created_at"]
    search_fields = ["description", "owner_token"]
    readonly_fields = ["buffer_geom", "created_at", "updated_at"]
