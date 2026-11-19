import django.contrib.gis.db.models.fields
import django.contrib.postgres.indexes
from django.db import migrations, models
import mapper.models


TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION generate_hazardpin_buffer()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.geom IS NOT NULL AND (
        NEW.buffer_geom IS NULL OR
        (TG_OP = 'UPDATE' AND (OLD.geom IS NULL OR NOT ST_Equals(NEW.geom, OLD.geom)))
    ) THEN
        NEW.buffer_geom := ST_Buffer(NEW.geom::geography, 100)::geometry;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION generate_safetypin_buffer()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.geom IS NOT NULL AND (
        NEW.buffer_geom IS NULL OR
        (TG_OP = 'UPDATE' AND (OLD.geom IS NULL OR NOT ST_Equals(NEW.geom, OLD.geom)))
    ) THEN
        NEW.buffer_geom := ST_Buffer(NEW.geom::geography, 100)::geometry;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_hazardpin_buffer ON mapper_hazardpin;
CREATE TRIGGER trg_hazardpin_buffer
BEFORE INSERT OR UPDATE OF geom, buffer_geom ON mapper_hazardpin
FOR EACH ROW
EXECUTE FUNCTION generate_hazardpin_buffer();
"""

REVERSE_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS trg_hazardpin_buffer ON mapper_hazardpin;
DROP FUNCTION IF EXISTS generate_hazardpin_buffer();
DROP FUNCTION IF EXISTS generate_safetypin_buffer();
"""


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='City',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(help_text="City code identifier (e.g. 'paris')", max_length=32, unique=True)),
                ('name', models.CharField(help_text="Name of the city (e.g. 'Paris')", max_length=100, unique=True)),
                ('geom', django.contrib.gis.db.models.fields.PolygonField(help_text='City boundary polygon in EPSG:4326 coordinates', srid=4326)),
                ('high_threshold', models.IntegerField(blank=True, help_text='Heatmap risk threshold', null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'City',
                'verbose_name_plural': 'Cities',
                'ordering': ['name'],
                'indexes': [
                    django.contrib.postgres.indexes.GistIndex(fields=['geom'], name='mapper_city_geom_gist'),
                ],
            },
        ),
        migrations.CreateModel(
            name='HazardPin',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('description', models.TextField(blank=True, help_text='Optional description of the incident', null=True)),
                ('geom', django.contrib.gis.db.models.fields.PointField(help_text='Point geometry (Longitude, Latitude) in EPSG:4326', srid=4326)),
                ('buffer_geom', django.contrib.gis.db.models.fields.PolygonField(blank=True, help_text='100-meter buffer polygon generated from geom by database trigger', null=True, srid=4326)),
                ('owner_token', models.UUIDField(help_text='Client-supplied ownership UUID token')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField(default=mapper.models.default_pin_expiry, help_text='Timestamp when the pin expires (default now() + 90 min)')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Hazard Pin',
                'verbose_name_plural': 'Hazard Pins',
                'ordering': ['-created_at'],
                'indexes': [
                    django.contrib.postgres.indexes.GistIndex(fields=['geom'], name='mapper_hazardpin_geom_gist'),
                    django.contrib.postgres.indexes.GistIndex(fields=['buffer_geom'], name='mapper_hazardpin_buf_gist'),
                    models.Index(fields=['expires_at'], name='mapper_pin_expires_idx'),
                    models.Index(fields=['owner_token'], name='mapper_pin_owner_idx'),
                ],
            },
        ),
        migrations.RunSQL(
            sql=TRIGGER_SQL,
            reverse_sql=REVERSE_TRIGGER_SQL,
        ),
    ]
