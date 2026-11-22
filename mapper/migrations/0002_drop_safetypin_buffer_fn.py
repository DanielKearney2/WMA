from django.db import migrations

FORWARD = "DROP FUNCTION IF EXISTS generate_safetypin_buffer();"
REVERSE = """
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
"""


class Migration(migrations.Migration):
    dependencies = [("mapper", "0001_initial")]
    operations = [migrations.RunSQL(sql=FORWARD, reverse_sql=REVERSE)]
