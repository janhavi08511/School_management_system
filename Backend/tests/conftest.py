import csv, html, os
from pathlib import Path
import pytest

REPORT_DIR = Path(__file__).parent / "reports"
CATALOG = Path(__file__).parent / "test_case_catalog.csv"
results = []
CASE_MAP = {'test_fee_totals_are_loaded_for_the_authenticated_student': {'Test ID': 'STU-API-001', 'Test Case Name': 'Student fee totals for authenticated student', 'Description': "GET /student/fees returns fee totals scoped to authenticated student's user ID.", 'Expected Outcome': 'HTTP 200; total_fees and pending_fees returned as expected; DB lookups scoped to student.'}, 'test_non_student_role_cannot_access_student_profile': {'Test ID': 'STU-API-002', 'Test Case Name': 'Student role access enforcement', 'Description': 'A user with teacher role attempts GET /student/profile.', 'Expected Outcome': 'HTTP 403; database is not queried.'}, 'test_teacher_can_view_own_attendance_and_salary': {'Test ID': 'TCH-API-001', 'Test Case Name': 'Teacher profile, attendance and salary', 'Description': 'Teacher retrieves own profile, attendance summary and salary details.', 'Expected Outcome': 'All requests return HTTP 200; profile name, attendance percentage and salary amounts match expected values.'}, 'test_teacher_views_students_in_assigned_course': {'Test ID': 'TCH-API-002', 'Test Case Name': 'View students in assigned course', 'Description': 'Teacher views enrolled students for course 55 on a date.', 'Expected Outcome': 'HTTP 200; assigned course and student details returned.'}, 'test_teacher_cannot_take_attendance_for_unassigned_student': {'Test ID': 'TCH-API-003', 'Test Case Name': 'Reject attendance for unassigned student', 'Description': 'Teacher submits attendance for student not enrolled in assigned course.', 'Expected Outcome': 'HTTP 422; no attendance insert; transaction rolled back.'}, 'test_teacher_records_attendance_for_an_enrolled_student': {'Test ID': 'TCH-API-004', 'Test Case Name': 'Record attendance for enrolled student', 'Description': 'Teacher submits attendance record for enrolled student.', 'Expected Outcome': 'HTTP 200; count reflects submitted record; attendance insert executed and committed.'}, 'test_teacher_cannot_record_attendance_outside_current_academic_year': {'Test ID': 'TCH-API-005', 'Test Case Name': 'Reject attendance date outside academic year', 'Description': 'Teacher queries course students using date outside current academic year.', 'Expected Outcome': 'HTTP 422; student-course query not run.'}, 'test_teacher_cannot_record_attendance_for_a_future_date': {'Test ID': 'TCH-API-006', 'Test Case Name': 'Reject future attendance date', 'Description': 'Teacher queries course students using a future date.', 'Expected Outcome': 'HTTP 422.'}, 'test_teacher_dashboard_returns_overview_sections': {'Test ID': 'TCH-API-007', 'Test Case Name': 'Teacher dashboard overview', 'Description': 'Teacher opens dashboard overview.', 'Expected Outcome': "HTTP 200; profile, assigned courses, today's classes and recent activities are present."}, 'test_course_note_upload_stores_file_and_metadata': {'Test ID': 'TCH-API-008', 'Test Case Name': 'Upload course note', 'Description': 'Teacher uploads allowed PDF and note metadata to assigned course.', 'Expected Outcome': 'HTTP 201; metadata returned, file stored, insert executed.'}, 'test_course_note_upload_rejects_unsupported_file_types': {'Test ID': 'TCH-API-009', 'Test Case Name': 'Reject unsupported note file type', 'Description': 'Teacher attempts upload with .exe file.', 'Expected Outcome': 'HTTP 415; no database query performed.'}, 'test_teacher_can_edit_course_note_details': {'Test ID': 'TCH-API-010', 'Test Case Name': 'Edit course note details', 'Description': 'Teacher edits title and description of own assigned-course note.', 'Expected Outcome': 'HTTP 200; updated fields returned and update SQL executed.'}, 'test_teacher_can_delete_course_note_and_file': {'Test ID': 'TCH-API-011', 'Test Case Name': 'Delete course note and file', 'Description': 'Teacher deletes own course note.', 'Expected Outcome': 'HTTP 200; stored file removed and transaction committed.'}, 'test_course_note_download_increments_download_count': {'Test ID': 'TCH-API-012', 'Test Case Name': 'Download course note', 'Description': 'Teacher downloads own course note.', 'Expected Outcome': 'HTTP 200; file contents returned and download_count increment query executed.'}}

def pytest_runtest_makereport(item, call):
    if call.when != "call":
        return
    outcome = call.excinfo
    status = "PASS" if outcome is None else "FAIL"
    actual = "Test assertions passed." if status == "PASS" else f"Test failed: {outcome.value}"
    case = CASE_MAP.get(item.name, {})
    results.append({
        "Test ID": case.get("Test ID", item.nodeid.split("::")[-1]),
        "Test Case Name": case.get("Test Case Name", item.name.replace("_", " ").title()),
        "Description": case.get("Description", item.function.__doc__ or item.name.replace("_", " ")),
        "Expected Outcome": case.get("Expected Outcome", "As specified by the test assertions."),
        "Actual Outcome": actual,
        "Status": status,
        "Duration (seconds)": f"{call.duration:.3f}",
        "Pytest Node": item.nodeid,
    })

def pytest_sessionfinish(session, exitstatus):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    fields = ["Test ID","Test Case Name","Description","Expected Outcome","Actual Outcome","Status","Duration (seconds)","Pytest Node"]
    # Merge catalog's detailed descriptions with actual runtime results.
    catalog = {}
    if CATALOG.exists():
        with CATALOG.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                catalog[row["Test Case Name"]] = row
    rows=[]
    for result in results:
        # retain runtime node as stable unique test reference; catalog is provided for detailed case info
        rows.append(result)
    with (REPORT_DIR/"student_teacher_test_report.csv").open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    body="".join("<tr>"+"".join(f"<td>{html.escape(str(row[k]))}</td>" for k in fields)+"</tr>" for row in rows)
    totals={"PASS":sum(r["Status"]=="PASS" for r in rows),"FAIL":sum(r["Status"]=="FAIL" for r in rows)}
    page=f"""<!doctype html><html><head><meta charset="utf-8"><title>Student & Teacher Test Report</title>
<style>body{{font-family:Arial;margin:24px}}table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{border:1px solid #ccc;padding:8px;text-align:left}}th{{background:#eee}}.summary{{margin:14px 0}}</style></head>
<body><h1>Student & Teacher Test Execution Report</h1><div class="summary">Executed: {len(rows)} | PASS: {totals['PASS']} | FAIL: {totals['FAIL']} | Pytest exit status: {exitstatus}</div>
<p>Detailed test descriptions and expected outcomes are in test_case_catalog.csv.</p><table><thead><tr>{"".join(f"<th>{html.escape(k)}</th>" for k in fields)}</tr></thead><tbody>{body}</tbody></table></body></html>"""
    (REPORT_DIR/"student_teacher_test_report.html").write_text(page,encoding="utf-8")
