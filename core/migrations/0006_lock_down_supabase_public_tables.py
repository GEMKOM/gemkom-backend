from django.db import migrations


LOCK_DOWN_PUBLIC_TABLES_SQL = """
DO $$
DECLARE
    table_record record;
    sequence_record record;
BEGIN
    FOR table_record IN
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE schemaname = 'public'
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',
            table_record.schemaname,
            table_record.tablename
        );

        IF to_regrole('anon') IS NOT NULL THEN
            EXECUTE format(
                'REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM anon',
                table_record.schemaname,
                table_record.tablename
            );
        END IF;

        IF to_regrole('authenticated') IS NOT NULL THEN
            EXECUTE format(
                'REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM authenticated',
                table_record.schemaname,
                table_record.tablename
            );
        END IF;
    END LOOP;

    FOR sequence_record IN
        SELECT sequence_schema, sequence_name
        FROM information_schema.sequences
        WHERE sequence_schema = 'public'
    LOOP
        IF to_regrole('anon') IS NOT NULL THEN
            EXECUTE format(
                'REVOKE ALL PRIVILEGES ON SEQUENCE %I.%I FROM anon',
                sequence_record.sequence_schema,
                sequence_record.sequence_name
            );
        END IF;

        IF to_regrole('authenticated') IS NOT NULL THEN
            EXECUTE format(
                'REVOKE ALL PRIVILEGES ON SEQUENCE %I.%I FROM authenticated',
                sequence_record.sequence_schema,
                sequence_record.sequence_name
            );
        END IF;
    END LOOP;

    IF to_regrole('anon') IS NOT NULL THEN
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            REVOKE ALL PRIVILEGES ON TABLES FROM anon;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            REVOKE ALL PRIVILEGES ON SEQUENCES FROM anon;
    END IF;

    IF to_regrole('authenticated') IS NOT NULL THEN
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            REVOKE ALL PRIVILEGES ON TABLES FROM authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            REVOKE ALL PRIVILEGES ON SEQUENCES FROM authenticated;
    END IF;
END $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("admin", "0003_logentry_add_action_flag_choices"),
        ("approvals", "0016_approvallstage_role_user_group"),
        ("attendance", "0015_alter_attendancerecord_early_leave_minutes_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("cnc_cutting", "0017_remove_cnctask_selected_plate_remnantplateusage_and_more"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("core", "0005_initial"),
        ("equipment", "0001_initial"),
        ("finance", "0002_salesofferinstallmentreceipt"),
        ("linear_cutting", "0010_linearcuttingpart_image_no"),
        ("machines", "0023_alter_machine_machine_type_alter_machine_used_in"),
        ("machining", "0024_alter_jobcostagguser_unique_together_and_more"),
        ("notifications", "0027_alter_notificationconfig_user_groups"),
        ("organization", "0007_remove_usergroup_organization_usergroup_slug_unique_and_more"),
        ("overtime", "0004_remove_team_index"),
        ("planning", "0009_planningrequestitem_delivered_at_and_more"),
        ("procurement", "0036_dbspayment"),
        ("projects", "0048_alter_departmenttasktemplateitem_task_type_and_more"),
        ("quality_control", "0014_ncr_assigned_team_to_usergroup"),
        ("sales", "0013_add_pricing_mode_to_salesoffer"),
        ("sessions", "0001_initial"),
        ("subcontracting", "0011_add_tier_type_to_price_tier"),
        ("tasks", "0002_remove_tool_operationtool"),
        ("teams", "0001_initial"),
        ("users", "0041_add_personel_fields_to_userprofile"),
        ("vacation_requests", "0008_backfill_vacation_hr_stage_approvers"),
        ("welding", "0006_internalteamassignment"),
    ]

    operations = [
        migrations.RunSQL(
            sql=LOCK_DOWN_PUBLIC_TABLES_SQL,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
