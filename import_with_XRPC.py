import sys
import os
from datetime import datetime, timedelta
support_tools_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '/home/odoo/Desktop/src/support-tools'))
sys.path.insert(0, support_tools_path)

from lib.odoorpc import OdooXR
from lib.password_manager import OePassword

def get_model_id(target: OdooXR, model_name: str):
    result = target.search_read(
        model="ir.model", domain=[("model", "=", model_name)], fields_to_get=["id"]
    )
    return result[0]["id"] if result else None


def import_server_actions(source: OdooXR, target: OdooXR):
    """Extract server actions from source and import inSto target."""
    print("Fetching server actions from source...")
    actions = source.search_read(
        model="hr.applicant",
        domain=[("partner_name","=",False)],
        fields_to_get=[
            "id", "state", "model_name", "binding_type", "code",
            "usage", "sequence", "type", "xml_id","group_ids"
        ],
    )
    missing_actions = []
    for action in actions:
        if action['xml_id'] in domain:
            # print(action['xml_id'])
            missing_actions.append(action)


    print(f"Found {len(missing_actions)} server actions.")

    for action in missing_actions:
        # print(action)
        model_name = action.get("model_name")
        # print(target, model_name)
        model_id = get_model_id(target, model_name)
        # print("finish")
        if not model_id:
            print(f"Skipping '{action['name']}' – model '{model_name}' not found in target.")
            continue

        xml_id = action.get("xml_id")
        if not xml_id:
            print(f"Skipping '{action['name']}' – no XML ID found.")
            continue

        values = {
            "name": action["name"],
            "state": action["state"],
            "model_id": model_id,
            "binding_type": action.get("binding_type"),
            "code": action.get("code"),
            "usage": action.get("usage"),
            "sequence": action.get("sequence"),
            "type": action.get("type"),
            "create_uid": 1,
            "group_ids": action["group_ids"]
        }

        try:
            # print(values)
            new_id = target.create("ir.actions.server", [values])
            if "." in xml_id:
                module, name = xml_id.split(".", 1)
                target.create("ir.model.data", [{
                    "name": name,
                    "module": module,
                    "model": "ir.actions.server",
                    "res_id": new_id,
                    "noupdate": True,
                }])
                print(f"Imported: {action['name']} with xml_id {xml_id}")
            else:
                print(f"Skipped XML ID creation – invalid format: {xml_id}")
        except Exception as e:
            print(f"Failed to import '{action['name']}': {e}")


def import_leaves(source: OdooXR, target: OdooXR):
    """Extract leaves from source and import into target."""
    print("Fetching applicants from source...")
    source_records = source.search_read(
        model="hr.leave",
        domain=[],
        fields_to_get=["id", "number_of_days_display", "number_of_hours_display"],
    )
    print("Fetched from source")
    updated_ids = []

    for record in source_records:
        target.write(
            model="hr.leave",
            ids=[record['id']],
            data={
                "number_of_days": record["number_of_days_display"],
                "number_of_hours": record["number_of_hours_display"],
            },
        )
        updated_ids.append(record["id"])

    print(f" Updated {len(updated_ids)} records from source DB.")

def sanitize_record(data: dict) -> dict:
    """
    Clean up record data so Odoo create/write gets only proper IDs for relational fields.
    - For many2one (`xxx_id`): keep only the integer ID if tuple/list given.
    - For many2many/one2many (`xxx_ids`): keep only the list of IDs.
    """
    cleaned = {}
    for k, v in data.items():
        if v is None:
            cleaned[k] = None
            continue

        # many2one fields
        if k.endswith("_id"):
            if isinstance(v, (list, tuple)):
                cleaned[k] = v[0]  # keep only ID
            else:
                cleaned[k] = v

        # many2many / one2many fields
        elif k.endswith("_ids"):
            if isinstance(v, (list, tuple)):
                # If Studio/export gives [ [id, name], ... ] flatten to ids
                if v and isinstance(v[0], (list, tuple)):
                    cleaned[k] = [x[0] for x in v]
                else:
                    cleaned[k] = v
            else:
                cleaned[k] = [v]

        else:
            cleaned[k] = v
    return cleaned

def import_records(source: OdooXR, target: OdooXR, model: str, ids: list, fields: list):
    """
    Import records from source to target for a given model.
    
    Args:
        source (OdooXR): Source DB connector
        target (OdooXR): Target DB connector
        model (str): Model name, e.g. "ir.ui.view"
        ids (list): List of IDs to fetch from source
        fields (list): Fields to transfer
    """

    print(f"Fetching {model} records from source...")
    records = source.search_read(
        model=model,
        domain=[("id", "in", ids)],
        fields_to_get=fields,
    )
    print(f"Fetched {len(records)} {model} records from source")
    # print(records)
    for rec in records:
        # remove ID so target can assign a new one
        data = {k: v for k, v in rec.items() if k != "id"}
        data = sanitize_record(data)
        print(data)
        print("\n\n")
        target.create(model=model, data=[data])
        
    print(f"Imported {len(records)} {model} records into target")

def import_overtime_attendance_corrections(source: OdooXR, target: OdooXR):
    print("Fetching overtime attendance corrections from source...")

    # Fetch attendance
    corrections = source.search_read(
        model="hr.attendance",
        domain=[('validated_overtime_hours', '!=', 0)],
        fields_to_get=[
            "id", "employee_id", "overtime_hours", "validated_overtime_hours",
            "check_in", "check_out"
        ],
    )

    if not corrections:
        print("No overtime corrections found.")
        return

    # Pre-fetch existing overtime lines 
    employee_dates = [(c['employee_id'][0], c['check_in'][:10]) for c in corrections]
    existing_lines = target.search_read(
        "hr.attendance.overtime.line",
        domain=[('employee_id', 'in', [e for e, _ in employee_dates]),
                ('date', 'in', [d for _, d in employee_dates])],
        fields_to_get=['id', 'employee_id', 'date']
    )

    line_map = {}
    for l in existing_lines:
        emp_id = l['employee_id'][0] 
        line_map[(emp_id, l['date'])] = l['id']

    to_write = []
    to_create = []
    i=0
    for corr in corrections:
        employee_id = corr['employee_id'][0]
        manual_duration = corr['validated_overtime_hours']
        duration = corr['overtime_hours']

        check_in_dt = datetime.fromisoformat(corr['check_in'])
        check_out_dt = datetime.fromisoformat(corr['check_out'])

        vals = {
            "employee_id": employee_id,
            "date": check_in_dt.date().isoformat(),
            "duration": duration,
            "manual_duration": manual_duration,
            "compensable_as_leave": True,
            "status": "approved",
            "time_start": check_in_dt.isoformat().replace("T", " "),
            "time_stop": ((check_out_dt + timedelta(hours=abs(duration))).isoformat()).replace("T", " "),
            'work_entry_type_overtime_id': 9,
        }

        key = (employee_id, check_in_dt.date().isoformat())
        if key in line_map:
            to_write.append((line_map[key], vals))
        else:
            to_create.append(vals)
            

    for line_id, vals in to_write:
        target.write("hr.attendance.overtime.line", [line_id], {
            "manual_duration": vals["manual_duration"],
            "compensable_as_leave": vals["compensable_as_leave"],
        })
        print(f"UPDATE {i+1}/{len(corrections)}")
        i+=1

    if to_create:
        for vals in to_create:
            target.create("hr.attendance.overtime.line", [vals])
            print(f"CREATE {i+1}/{len(corrections)}")
            i+=1

    print(f"Imported {len(corrections)} overtime attendance corrections into target")
    print(f" - Updated {len(to_write)} existing lines")
    print(f" - Created {len(to_create)} new lines")

    # run sa for recompute validated_overtime_hours
    mid = target.search_read("ir.model", [("name", "=", "Server Action")], ["id"])[0]["id"]
    sa = target.create("ir.actions.server", [{
        "name": "Recompute Overtime Hours",
        "model_id": mid,
        "state": "code",
        "code": "records = env['hr.attendance'].search([])\nrecords._compute_linked_overtime_ids()\nrecords._compute_overtime_hours()\nrecords._compute_validated_overtime_hours()"
    }])
    target.call_button("ir.actions.server", [sa])
    target.unlink("ir.actions.server", [sa])
    print("Recomputed overtime hours via server action.")


if __name__ == "__main__":
    #  Credentials
    source_pm = OePassword("office@example.com")
    target_pm = OePassword("office@example.com")
    session_id_source = "XXXXXX"
    session_id_target = "XXXXXX"
    #  Connect to source and target Odoo instances
    source = OdooXR(api_mode=1, db="example-20251208.odoo.com", host="https://example-20251208.odoo.com/", pm=source_pm, session_id=session_id_source)
    target = OdooXR(api_mode=1, db="example.odoo.com", host="https://example.odoo.com/", pm=target_pm, session_id=session_id_target)

    #  Run the import process
    import_overtime_attendance_corrections(source=source,target=target)
