import django.contrib.postgres.indexes
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('mapper', '0002_postgis_buffer_trigger_and_views'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='cityboundary',
            index=django.contrib.postgres.indexes.GistIndex(fields=['geom'], name='mapper_cityboundary_geom_gist'),
        ),
        migrations.AddIndex(
            model_name='safetypin',
            index=django.contrib.postgres.indexes.GistIndex(fields=['geom'], name='mapper_pin_geom_gist'),
        ),
        migrations.AddIndex(
            model_name='safetypin',
            index=django.contrib.postgres.indexes.GistIndex(fields=['buffer_geom'], name='mapper_pin_buffer_gist'),
        ),
    ]
