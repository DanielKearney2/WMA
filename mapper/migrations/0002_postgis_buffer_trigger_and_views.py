from django.db import migrations


TRIGGER_AND_VIEWS_SQL = """
-- 1. Database trigger function to auto-generate 100-meter PostGIS buffer polygon
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

-- 2. Attach trigger to mapper_safetypin table
DROP TRIGGER IF EXISTS trg_safetypin_buffer ON mapper_safetypin;
CREATE TRIGGER trg_safetypin_buffer
BEFORE INSERT OR UPDATE OF geom, buffer_geom ON mapper_safetypin
FOR EACH ROW
EXECUTE FUNCTION generate_safetypin_buffer();

-- 3. Compatibility views mapping_* for SPEC#1.md raw SQL queries
CREATE OR REPLACE VIEW mapping_safetypin AS SELECT * FROM mapper_safetypin;
CREATE OR REPLACE VIEW mapping_cityboundary AS SELECT * FROM mapper_cityboundary;
"""

REVERSE_TRIGGER_AND_VIEWS_SQL = """
DROP VIEW IF EXISTS mapping_safetypin;
DROP VIEW IF EXISTS mapping_cityboundary;
DROP TRIGGER IF EXISTS trg_safetypin_buffer ON mapper_safetypin;
DROP FUNCTION IF EXISTS generate_safetypin_buffer();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('mapper', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql=TRIGGER_AND_VIEWS_SQL,
            reverse_sql=REVERSE_TRIGGER_AND_VIEWS_SQL,
        ),
    ]
