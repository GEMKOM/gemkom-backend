"""
Migration: Re-apply ON UPDATE CASCADE to FK constraints pointing at
projects_joborder.job_no.

Migration 0038 added ON UPDATE CASCADE to every FK referencing
projects_joborder(job_no) that existed at that time. The phase support
added in 0053 introduced a new self-FK (source_job_order) which was created
with Django's default NO ACTION update rule. Without ON UPDATE CASCADE,
renaming a job_no that has production phases fails with a
ForeignKeyViolation because the phase mirrors still reference the old job_no.

This migration re-runs the same dynamic ON UPDATE CASCADE SQL as 0038 so the
new source_job_order constraint (and any other later additions) are covered.
The SQL drops and recreates every matching FK, so it is safe to re-run.
"""

from django.db import migrations

# Identical to migration 0038: dynamically find every FK that references
# projects_joborder(job_no) and recreate it with ON UPDATE CASCADE, preserving
# the existing ON DELETE rule. Uses information_schema so no constraint names
# are hard-coded.
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
        ('projects', '0053_joborder_phase_fields'),
    ]

    operations = [
        migrations.RunSQL(
            sql=ADD_ON_UPDATE_CASCADE,
            reverse_sql=REMOVE_ON_UPDATE_CASCADE,
        ),
    ]
