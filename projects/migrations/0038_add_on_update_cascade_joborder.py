"""
Migration: Add ON UPDATE CASCADE to all FK constraints pointing at projects_joborder.job_no

This is required to support renaming job_no (the primary key) without
manually chasing down every FK reference inside the projects app.
Cross-app CharField references are handled in the rename_job_no service.
"""

from django.db import migrations

# Dynamically find every FK that references projects_joborder(job_no) and
# recreate it with ON UPDATE CASCADE.  Uses the information_schema so the
# migration does not need hard-coded constraint names.
ADD_ON_UPDATE_CASCADE = """
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT
            tc.table_schema,
            tc.table_name,
            tc.constraint_name,
            kcu.column_name,
            rc.delete_rule
        FROM
            information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.referential_constraints AS rc
                ON tc.constraint_name = rc.constraint_name
                AND tc.constraint_schema = rc.constraint_schema
            JOIN information_schema.constraint_column_usage AS ccu
                ON rc.unique_constraint_name = ccu.constraint_name
                AND rc.unique_constraint_schema = ccu.constraint_schema
        WHERE
            tc.constraint_type = 'FOREIGN KEY'
            AND ccu.table_name = 'projects_joborder'
            AND ccu.column_name = 'job_no'
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I DROP CONSTRAINT %I',
            r.table_schema, r.table_name, r.constraint_name
        );
        EXECUTE format(
            'ALTER TABLE %I.%I ADD CONSTRAINT %I '
            'FOREIGN KEY (%I) REFERENCES %I.projects_joborder(job_no) '
            'ON DELETE %s ON UPDATE CASCADE',
            r.table_schema, r.table_name, r.constraint_name,
            r.column_name,
            r.table_schema,
            r.delete_rule
        );
    END LOOP;
END $$;
"""

# Reverse: remove ON UPDATE CASCADE (restore to plain ON DELETE <rule>)
REMOVE_ON_UPDATE_CASCADE = """
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT
            tc.table_schema,
            tc.table_name,
            tc.constraint_name,
            kcu.column_name,
            rc.delete_rule
        FROM
            information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.referential_constraints AS rc
                ON tc.constraint_name = rc.constraint_name
                AND tc.constraint_schema = rc.constraint_schema
            JOIN information_schema.constraint_column_usage AS ccu
                ON rc.unique_constraint_name = ccu.constraint_name
                AND rc.unique_constraint_schema = ccu.constraint_schema
        WHERE
            tc.constraint_type = 'FOREIGN KEY'
            AND ccu.table_name = 'projects_joborder'
            AND ccu.column_name = 'job_no'
            AND rc.update_rule = 'CASCADE'
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I DROP CONSTRAINT %I',
            r.table_schema, r.table_name, r.constraint_name
        );
        EXECUTE format(
            'ALTER TABLE %I.%I ADD CONSTRAINT %I '
            'FOREIGN KEY (%I) REFERENCES %I.projects_joborder(job_no) '
            'ON DELETE %s',
            r.table_schema, r.table_name, r.constraint_name,
            r.column_name,
            r.table_schema,
            r.delete_rule
        );
    END LOOP;
END $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0037_remove_discussion_notification'),
    ]

    operations = [
        migrations.RunSQL(
            sql=ADD_ON_UPDATE_CASCADE,
            reverse_sql=REMOVE_ON_UPDATE_CASCADE,
        ),
    ]
