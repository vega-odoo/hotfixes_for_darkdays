SHOULD_COMMIT          = True
SHOULD_LOG             = True
upgrade_date           = "2025-12-05" # YYYY-MM-DD of the upgrade to >= v.19 as negative overtime is only missing after that date

atts = env['hr.attendance'].search([('check_in', '!=', False), ('check_out', '!=', False),('check_in','>=',upgrade_date)])

atts._update_overtime()
env['hr.attendance.overtime.line'].search([]).write({'compensable_as_leave': True})
env['hr.version'].search([('ruleset_id', '=', False)]).write({'ruleset_id': env.ref('hr_attendance.hr_attendance_default_ruleset', raise_if_not_found=False)})

# Attendance aggregation
attendances = env['hr.attendance'].with_context(lang='en_US')._read_group(
    domain=[('check_in', '!=', False), ('check_out', '!=', False),('check_in','>=','2025-12-05')],
    aggregates=['worked_hours:sum'],
    groupby=['employee_id', 'check_in:day'],
)

# Calendar tracking
calendar_field = env.ref('hr.field_hr_employee__resource_calendar_id')

mails = env['mail.message'].search([
    ('model', '=', 'hr.employee'),
    ('tracking_value_ids.field_id', '=', calendar_field.id),
])

emp_versions = {}
for mail in mails:
    tv = mail.tracking_value_ids.filtered(lambda t: t.field_id.id == calendar_field.id)
    if not tv or not tv.old_value_integer:
        continue
    emp_versions.setdefault(int(mail.res_id), []).append(
        (mail.date.date(), tv.old_value_integer)
    )

# Main processing loop
report_lines = []
corrections = []

for row in attendances:
    employee = row[0]
    day = row[1].date()
    worked_hours = row[2] or 0.0

    tz = timezone(employee.tz or 'UTC')

    start_dt = tz.localize(datetime.datetime.combine(day, datetime.time.min))
    end_dt = tz.localize(datetime.datetime.combine(day, datetime.time.max))

    expected_hours = sum((iv[1] - iv[0]).total_seconds() / 3600.0 for iv in employee.resource_calendar_id._work_intervals_batch(start_dt, end_dt, employee.resource_id).get(employee.resource_id.id, []))
    
    # Calendar history override
    if employee.id in emp_versions and expected_hours > 0:
        for change_date, calendar_id in sorted(emp_versions[employee.id]):
            if day < change_date:
                expected_hours = env['resource.calendar'].browse(calendar_id).hours_per_day
                if not expected_hours:
                    report_lines.append(
                        f" ⚪ Employee {employee.id} skipped on {day} (flexible calendar)"
                    )
                    expected_hours = None
                break

    if expected_hours is None or expected_hours == 0:
        continue

    extra_hours = worked_hours - expected_hours

    # Ruleset threshold
    must_exceed = 0.0
    rule = employee.ruleset_id.rule_ids.filtered(
        lambda r: r.base_off == 'quantity' and not r.expected_hours_from_contract)[:1]

    if rule:
        must_exceed = rule.expected_hours

    if extra_hours >= 0 or worked_hours < must_exceed:
        continue

    start = datetime.datetime.combine(day, datetime.time.min)
    end = start + datetime.timedelta(days=1)
    
    day_atts = env['hr.attendance'].search([
        ('employee_id', '=', employee.id),
        ('check_in', '>=', start),
        ('check_in', '<', end)
    ])

    if not day_atts or any(not a.check_out for a in day_atts):
        continue

    att = max(day_atts, key=lambda a: a.check_out)
    if att.validated_overtime_hours != att.overtime_hours and att.validated_overtime_hours != 0:
        report_lines.append(f" ⚪ Attendance ID {att.id} on {day} skipped (validated mismatch)\n")
        continue

    correction_vals = {
        'employee_id': employee.id,
        'date': day,
        'duration': extra_hours,
        'manual_duration': extra_hours,
        'compensable_as_leave': True,
        'status': 'approved',
        'time_start': att.check_in,
        'time_stop': att.check_out + datetime.timedelta(hours=abs(extra_hours)),
        'work_entry_type_overtime_id': 9,
    }

    overtime_line = env['hr.attendance.overtime.line'].search([
        ('employee_id', '=', employee.id),
        ('date', '=', day)
    ], limit=1)

    if SHOULD_COMMIT:
        if overtime_line:
            overtime_line.sudo().write(correction_vals)
        else:
            env['hr.attendance.overtime.line'].sudo().create(correction_vals)

    report_lines.append(
        f" 🔴  Attendance {att.id}: {abs(extra_hours)}h missing vs expected"
    )

report = ("Corrections applied:\n") + "\n".join(report_lines)

if SHOULD_LOG:
    log(report, "info")

if SHOULD_COMMIT:
    atts._compute_linked_overtime_ids()
    atts._compute_overtime_hours()
    atts._compute_validated_overtime_hours()
    env.cr.commit()

else:   
    raise UserError(report)





# ============================================================
