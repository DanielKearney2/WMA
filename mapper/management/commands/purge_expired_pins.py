from django.core.management.base import BaseCommand
from django.utils import timezone

from mapper.models import HazardPin


class Command(BaseCommand):
    help = "Purges expired hazard pins (expires_at <= now)."

    def handle(self, *args, **options):
        now = timezone.now()
        deleted_count, _ = HazardPin.objects.filter(expires_at__lte=now).delete()
        self.stdout.write(
            self.style.SUCCESS(f"Purged {deleted_count} expired hazard pin(s).")
        )
