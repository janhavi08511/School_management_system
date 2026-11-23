import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mysql.connector import Error as MySQLError

from Auth import _create_access_token
from Teacher import create_teacher_router

AUTH_SECRET = "test-auth-secret-key-that-is-at-least-32-chars"


class TeacherApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cursor = FakeCursor()
        self.connection = FakeConnection(self.cursor)

        def database_dependency():
            yield self.connection

        app = FastAPI()
        app.include_router(create_teacher_router(database_dependency))
        self.client = TestClient(app)

    def teacher_headers(self) -> dict[str, str]:
        token = _create_access_token("42", ["teacher"])
        return {"Authorization": f"Bearer {token}"}

    def test_teacher_can_view_own_attendance_and_salary(self) -> None:
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            profile = self.client.get(
                "/teacher/profile",
                headers=self.teacher_headers(),
            )
            attendance = self.client.get(
                "/teacher/attendance",
                headers=self.teacher_headers(),
            )
            salary = self.client.get(
                "/teacher/salary",
                headers=self.teacher_headers(),
            )

        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json()["name"], "Taylor Teacher")
        self.assertEqual(attendance.status_code, 200)
        self.assertEqual(attendance.json()["records"][0]["status"], "present")
        self.assertEqual(attendance.json()["summary"]["percentage"], 100.0)
        self.assertEqual(salary.status_code, 200)
        self.assertEqual(salary.json()["base_salary"], "45000.00")
        self.assertEqual(salary.json()["payments"][0]["net_amount"], "42000.00")
        self.assertEqual(salary.json()["payments"][0]["allowances"], "0.00")

    def test_teacher_views_students_in_assigned_course(self) -> None:
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.get(
                "/teacher/courses/55/students",
                params={"attendance_date": date.today().isoformat()},
                headers=self.teacher_headers(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["course"]["course_code"], "MATH-101")
        self.assertEqual(response.json()["students"][0]["name"], "Casey Student")

    def test_teacher_cannot_take_attendance_for_unassigned_student(self) -> None:
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.post(
                "/teacher/courses/55/attendance",
                headers=self.teacher_headers(),
                json={
                    "attendance_date": date.today().isoformat(),
                    "records": [{"student_id": 999, "status": "present"}],
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertFalse(
            any("INSERT INTO attendance_sessions" in query for query, _ in self.cursor.queries)
        )
        self.assertTrue(self.connection.rolled_back)

    def test_teacher_records_attendance_for_an_enrolled_student(self) -> None:
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.post(
                "/teacher/courses/55/attendance",
                headers=self.teacher_headers(),
                json={
                    "attendance_date": date.today().isoformat(),
                    "records": [{"student_id": 501, "status": "late", "notes": "Bus"}],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["students_recorded"], 1)
        self.assertTrue(
            any("INSERT INTO attendance_records" in query for query, _ in self.cursor.queries)
        )
        self.assertTrue(self.connection.committed)

    def test_teacher_cannot_record_attendance_outside_current_academic_year(self) -> None:
        outside_date = date(date.today().year - 1, 1, 1)
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.get(
                "/teacher/courses/55/students",
                params={"attendance_date": outside_date.isoformat()},
                headers=self.teacher_headers(),
            )

        self.assertEqual(response.status_code, 422)
        self.assertFalse(
            any("FROM student_courses" in query for query, _ in self.cursor.queries)
        )

    def test_teacher_cannot_record_attendance_for_a_future_date(self) -> None:
        future_date = date.today() + timedelta(days=1)
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.get(
                "/teacher/courses/55/students",
                params={"attendance_date": future_date.isoformat()},
                headers=self.teacher_headers(),
            )

        self.assertEqual(response.status_code, 422)

    def test_teacher_dashboard_returns_overview_sections(self) -> None:
        self.cursor.dashboard_counts = {
            "total_students": 3,
            "attendance_taken": 1,
        }
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.get(
                "/teacher/dashboard",
                headers=self.teacher_headers(),
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["profile"]["name"], "Taylor Teacher")
        self.assertEqual(data["total_students"], 3)
        self.assertEqual(len(data["assigned_courses"]), 1)
        self.assertIn("todays_classes", data)
        self.assertIn("recent_activities", data)

    def test_course_note_upload_stores_file_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as upload_dir:
            with patch("Teacher.NOTE_STORAGE_DIR", Path(upload_dir)):
                with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
                    response = self.client.post(
                        "/teacher/courses/55/notes",
                        headers=self.teacher_headers(),
                        data={"title": "Chapter 1", "description": "First chapter"},
                        files={"file": ("chapter.pdf", b"sample course notes", "application/pdf")},
                    )

            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["title"], "Chapter 1")
            self.assertEqual(response.json()["description"], "First chapter")
            stored_files = list(Path(upload_dir).iterdir())
            self.assertEqual(len(stored_files), 1)
            self.assertEqual(stored_files[0].read_bytes(), b"sample course notes")
            self.assertTrue(
                any("INSERT INTO course_notes" in query for query, _ in self.cursor.queries)
            )

    def test_course_note_upload_rejects_unsupported_file_types(self) -> None:
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.post(
                "/teacher/courses/55/notes",
                headers=self.teacher_headers(),
                data={"title": "Unsafe file"},
                files={"file": ("notes.exe", b"not allowed", "application/octet-stream")},
            )

        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.cursor.queries, [])

    def test_teacher_can_edit_course_note_details(self) -> None:
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.patch(
                "/teacher/notes/91",
                headers=self.teacher_headers(),
                json={"title": "Updated chapter", "description": "Revised notes"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "Updated chapter")
        self.assertTrue(
            any("SET title = %s, description = %s" in query for query, _ in self.cursor.queries)
        )

    def test_teacher_can_delete_course_note_and_file(self) -> None:
        with tempfile.TemporaryDirectory() as upload_dir:
            stored_note = Path(upload_dir) / "stored.pdf"
            stored_note.write_bytes(b"course notes")
            with patch("Teacher.NOTE_STORAGE_DIR", Path(upload_dir)):
                with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
                    response = self.client.delete(
                        "/teacher/notes/91",
                        headers=self.teacher_headers(),
                    )

            self.assertEqual(response.status_code, 200)
            self.assertFalse(stored_note.exists())
            self.assertTrue(self.connection.committed)

    def test_course_note_download_increments_download_count(self) -> None:
        with tempfile.TemporaryDirectory() as upload_dir:
            stored_note = Path(upload_dir) / "stored.pdf"
            stored_note.write_bytes(b"course notes")
            with patch("Teacher.NOTE_STORAGE_DIR", Path(upload_dir)):
                with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
                    response = self.client.get(
                        "/teacher/notes/91/download",
                        headers=self.teacher_headers(),
                    )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"course notes")
            self.assertTrue(
                any(
                    "download_count = download_count + 1" in query
                    for query, _ in self.cursor.queries
                )
            )

    def test_teacher_endpoints_require_a_valid_teacher_token(self) -> None:
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            missing = self.client.get("/teacher/profile")
            invalid = self.client.get(
                "/teacher/profile",
                headers={"Authorization": "Bearer invalid-token"},
            )
            student_token = _create_access_token("42", ["student"])
            wrong_role = self.client.get(
                "/teacher/profile",
                headers={"Authorization": f"Bearer {student_token}"},
            )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(invalid.status_code, 401)
        self.assertEqual(wrong_role.status_code, 403)
        self.assertEqual(self.cursor.queries, [])

    def test_profile_returns_not_found_when_teacher_record_is_missing(self) -> None:
        self.cursor.missing_teacher = True
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.get("/teacher/profile", headers=self.teacher_headers())

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Teacher profile not found.")

    def test_profile_reports_database_errors_as_service_unavailable(self) -> None:
        self.cursor.raise_on = "from staff as s"
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.get("/teacher/profile", headers=self.teacher_headers())

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Unable to load the teacher profile.")

    def test_attendance_rejects_malformed_month_and_conflicting_filters(self) -> None:
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            malformed = self.client.get(
                "/teacher/attendance",
                params={"month": "2026-13"},
                headers=self.teacher_headers(),
            )
            conflicting = self.client.get(
                "/teacher/attendance",
                params={
                    "month": "2026-11",
                    "attendance_date": date.today().isoformat(),
                },
                headers=self.teacher_headers(),
            )

        self.assertEqual(malformed.status_code, 422)
        self.assertEqual(conflicting.status_code, 422)
        self.assertEqual(self.cursor.queries, [])

    def test_attendance_can_be_filtered_to_a_single_date(self) -> None:
        attendance_date = date.today()
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.get(
                "/teacher/attendance",
                params={"attendance_date": attendance_date.isoformat()},
                headers=self.teacher_headers(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["month"])
        self.assertEqual(response.json()["attendance_date"], attendance_date.isoformat())
        attendance_query = next(
            params
            for query, params in self.cursor.queries
            if "from staff_attendance" in query.lower()
        )
        self.assertEqual(attendance_query, (88, attendance_date))

    def test_attendance_summary_is_zero_when_there_are_no_records(self) -> None:
        self.cursor.attendance_rows = []
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.get(
                "/teacher/attendance",
                params={"month": "2026-02"},
                headers=self.teacher_headers(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["summary"],
            {
                "present_days": 0,
                "absent_days": 0,
                "late_days": 0,
                "leave_days": 0,
                "total_days": 0,
                "percentage": 0,
            },
        )

    def test_salary_returns_empty_payments_when_none_exist(self) -> None:
        self.cursor.salary_rows = []
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.get("/teacher/salary", headers=self.teacher_headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"base_salary": "45000.00", "payments": []})

    def test_courses_returns_an_empty_list_when_teacher_has_no_courses(self) -> None:
        self.cursor.course_rows = []
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.get("/teacher/courses", headers=self.teacher_headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_dashboard_handles_missing_academic_year(self) -> None:
        self.cursor.missing_academic_year = True
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.get("/teacher/dashboard", headers=self.teacher_headers())

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "No current academic year is configured.")

    def test_dashboard_returns_not_recorded_salary_when_no_payment_exists(self) -> None:
        self.cursor.latest_salary = None
        self.cursor.dashboard_counts = {"total_students": 0, "attendance_taken": 0}
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.get("/teacher/dashboard", headers=self.teacher_headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_students"], 0)
        self.assertEqual(
            response.json()["salary_status"],
            {"status": "not_recorded", "pay_period": None, "net_amount": None},
        )

    def test_course_students_rejects_unassigned_course_and_missing_academic_year(self) -> None:
        attendance_date = date.today().isoformat()
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            unassigned = self.client.get(
                "/teacher/courses/999/students",
                params={"attendance_date": attendance_date},
                headers=self.teacher_headers(),
            )
            self.cursor.missing_academic_year = True
            missing_year = self.client.get(
                "/teacher/courses/55/students",
                params={"attendance_date": attendance_date},
                headers=self.teacher_headers(),
            )

        self.assertEqual(unassigned.status_code, 404)
        self.assertEqual(missing_year.status_code, 409)

    def test_course_students_returns_empty_roster(self) -> None:
        self.cursor.student_rows = []
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.get(
                "/teacher/courses/55/students",
                params={"attendance_date": date.today().isoformat()},
                headers=self.teacher_headers(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["students"], [])

    def test_attendance_submission_rejects_empty_duplicate_and_invalid_records(self) -> None:
        attendance_url = "/teacher/courses/55/attendance"
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            headers = self.teacher_headers()
            empty = self.client.post(
                attendance_url,
                headers=headers,
                json={"attendance_date": date.today().isoformat(), "records": []},
            )
            duplicate = self.client.post(
                attendance_url,
                headers=headers,
                json={
                    "attendance_date": date.today().isoformat(),
                    "records": [
                        {"student_id": 501, "status": "present"},
                        {"student_id": 501, "status": "absent"},
                    ],
                },
            )
            invalid_status = self.client.post(
                attendance_url,
                headers=headers,
                json={
                    "attendance_date": date.today().isoformat(),
                    "records": [{"student_id": 501, "status": "on_leave"}],
                },
            )
            invalid_student = self.client.post(
                attendance_url,
                headers=headers,
                json={
                    "attendance_date": date.today().isoformat(),
                    "records": [{"student_id": 0, "status": "present"}],
                },
            )
            excessive_notes = self.client.post(
                attendance_url,
                headers=headers,
                json={
                    "attendance_date": date.today().isoformat(),
                    "records": [
                        {
                            "student_id": 501,
                            "status": "present",
                            "notes": "x" * 501,
                        }
                    ],
                },
            )

        self.assertEqual(
            [empty.status_code, duplicate.status_code, invalid_status.status_code,
             invalid_student.status_code, excessive_notes.status_code],
            [422, 422, 422, 422, 422],
        )
        self.assertEqual(self.cursor.queries, [])

    def test_attendance_submission_trims_notes_and_records_multiple_students(self) -> None:
        self.cursor.enrolled_student_ids = {501, 502}
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.post(
                "/teacher/courses/55/attendance",
                headers=self.teacher_headers(),
                json={
                    "attendance_date": date.today().isoformat(),
                    "records": [
                        {"student_id": 501, "status": "excused", "notes": "  Family  "},
                        {"student_id": 502, "status": "absent"},
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["students_recorded"], 2)
        record_writes = [
            params
            for query, params in self.cursor.queries
            if "insert into attendance_records" in query.lower()
        ]
        self.assertEqual(record_writes[0][-2:], ("excused", "Family"))
        self.assertEqual(record_writes[1][-2:], ("absent", None))
        self.assertTrue(self.connection.committed)

    def test_attendance_database_error_rolls_back_and_returns_503(self) -> None:
        self.cursor.raise_on = "insert into attendance_records"
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.post(
                "/teacher/courses/55/attendance",
                headers=self.teacher_headers(),
                json={
                    "attendance_date": date.today().isoformat(),
                    "records": [{"student_id": 501, "status": "present"}],
                },
            )

        self.assertEqual(response.status_code, 503)
        self.assertTrue(self.connection.rolled_back)
        self.assertFalse(self.connection.committed)

    def test_attendance_history_rejects_invalid_month_and_returns_records(self) -> None:
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            invalid = self.client.get(
                "/teacher/courses/55/attendance/history",
                params={"month": "2026-00"},
                headers=self.teacher_headers(),
            )
            self.cursor.history_rows = [
                {
                    "attendance_date": date(2026, 11, 12),
                    "student_id": 501,
                    "admission_number": "A-501",
                    "class_name": "10-A",
                    "first_name": "Casey",
                    "last_name": "Student",
                    "status": "late",
                    "notes": "Bus",
                }
            ]
            valid = self.client.get(
                "/teacher/courses/55/attendance/history",
                params={"month": "2026-11"},
                headers=self.teacher_headers(),
            )

        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.json()["records"][0]["name"], "Casey Student")
        self.assertEqual(valid.json()["records"][0]["status"], "late")

    def test_course_notes_list_and_unassigned_course_behavior(self) -> None:
        self.cursor.note_rows = [
            {
                "id": 91,
                "title": "Chapter 1",
                "description": None,
                "original_filename": "chapter.pdf",
                "file_size": 12,
                "uploaded_at": datetime(2026, 11, 13, 9, 0),
                "download_count": 0,
            }
        ]
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            listed = self.client.get(
                "/teacher/courses/55/notes", headers=self.teacher_headers()
            )
            unassigned = self.client.get(
                "/teacher/courses/999/notes", headers=self.teacher_headers()
            )

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["title"], "Chapter 1")
        self.assertEqual(unassigned.status_code, 404)

    def test_note_upload_rejects_empty_file_and_oversized_file(self) -> None:
        with tempfile.TemporaryDirectory() as upload_dir:
            with patch("Teacher.NOTE_STORAGE_DIR", Path(upload_dir)):
                with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
                    empty = self.client.post(
                        "/teacher/courses/55/notes",
                        headers=self.teacher_headers(),
                        data={"title": "Empty"},
                        files={"file": ("empty.pdf", b"", "application/pdf")},
                    )
                    oversized = self.client.post(
                        "/teacher/courses/55/notes",
                        headers=self.teacher_headers(),
                        data={"title": "Large"},
                        files={
                            "file": (
                                "large.pdf",
                                b"x" * (15 * 1024 * 1024 + 1),
                                "application/pdf",
                            )
                        },
                    )

                self.assertEqual(empty.status_code, 422)
                self.assertEqual(oversized.status_code, 413)
                self.assertEqual(list(Path(upload_dir).iterdir()), [])
        self.assertFalse(
            any("INSERT INTO course_notes" in query for query, _ in self.cursor.queries)
        )

    def test_note_upload_database_failure_removes_partial_file(self) -> None:
        self.cursor.raise_on = "insert into course_notes"
        with tempfile.TemporaryDirectory() as upload_dir:
            with patch("Teacher.NOTE_STORAGE_DIR", Path(upload_dir)):
                with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
                    response = self.client.post(
                        "/teacher/courses/55/notes",
                        headers=self.teacher_headers(),
                        data={"title": "Chapter"},
                        files={"file": ("chapter.pdf", b"course notes", "application/pdf")},
                    )

            self.assertEqual(response.status_code, 503)
            self.assertEqual(list(Path(upload_dir).iterdir()), [])
        self.assertTrue(self.connection.rolled_back)

    def test_note_upload_returns_service_unavailable_without_confirmed_metadata(self) -> None:
        self.cursor.note_metadata_missing = True
        with tempfile.TemporaryDirectory() as upload_dir:
            with patch("Teacher.NOTE_STORAGE_DIR", Path(upload_dir)):
                with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
                    response = self.client.post(
                        "/teacher/courses/55/notes",
                        headers=self.teacher_headers(),
                        data={"title": "Chapter"},
                        files={"file": ("chapter.pdf", b"course notes", "application/pdf")},
                    )

            self.assertEqual(response.status_code, 503)
            self.assertEqual(list(Path(upload_dir).iterdir()), [])
        self.assertTrue(self.connection.rolled_back)

    def test_note_update_rejects_blank_title_and_missing_note(self) -> None:
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            blank = self.client.patch(
                "/teacher/notes/91",
                headers=self.teacher_headers(),
                json={"title": "   "},
            )
            self.cursor.missing_note = True
            missing = self.client.patch(
                "/teacher/notes/999",
                headers=self.teacher_headers(),
                json={"title": "Updated"},
            )

        self.assertEqual(blank.status_code, 422)
        self.assertEqual(missing.status_code, 404)
        self.assertTrue(self.connection.rolled_back)

    def test_note_update_database_error_rolls_back_and_returns_503(self) -> None:
        self.cursor.raise_on = "update course_notes"
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.patch(
                "/teacher/notes/91",
                headers=self.teacher_headers(),
                json={"title": "Updated"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertTrue(self.connection.rolled_back)

    def test_note_delete_returns_not_found_for_unassigned_note(self) -> None:
        self.cursor.missing_note = True
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.delete(
                "/teacher/notes/999", headers=self.teacher_headers()
            )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            any("DELETE FROM course_notes" in query for query, _ in self.cursor.queries)
        )

    def test_note_download_returns_not_found_for_missing_record_or_file(self) -> None:
        with tempfile.TemporaryDirectory() as upload_dir:
            with patch("Teacher.NOTE_STORAGE_DIR", Path(upload_dir)):
                with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
                    self.cursor.missing_note = True
                    missing_record = self.client.get(
                        "/teacher/notes/999/download",
                        headers=self.teacher_headers(),
                    )
                    self.cursor.missing_note = False
                    missing_file = self.client.get(
                        "/teacher/notes/91/download",
                        headers=self.teacher_headers(),
                    )

        self.assertEqual(missing_record.status_code, 404)
        self.assertEqual(missing_file.status_code, 404)
        self.assertFalse(
            any(
                "download_count = download_count + 1" in query
                for query, _ in self.cursor.queries
            )
        )

    def test_note_download_database_error_returns_service_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as upload_dir:
            (Path(upload_dir) / "stored.pdf").write_bytes(b"course notes")
            self.cursor.raise_on = "update course_notes set download_count"
            with patch("Teacher.NOTE_STORAGE_DIR", Path(upload_dir)):
                with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
                    response = self.client.get(
                        "/teacher/notes/91/download",
                        headers=self.teacher_headers(),
                    )

        self.assertEqual(response.status_code, 503)


class FakeCursor:
    def __init__(self) -> None:
        self.queries: list[tuple[str, tuple[object, ...]]] = []
        self.current_query = ""
        self.current_params: tuple[object, ...] = ()
        self.enrolled_student_ids = {501}
        self.dashboard_counts = {"total_students": 1, "attendance_taken": 0}
        self.missing_teacher = False
        self.missing_academic_year = False
        self.missing_course = False
        self.missing_note = False
        self.note_metadata_missing = False
        self.latest_salary: dict[str, object] | None = {
            "status": "paid",
            "pay_period": date.today().replace(day=1),
            "net_amount": Decimal("42000.00"),
        }
        self.attendance_rows: list[dict[str, object]] = [
            {
                "attendance_date": date(2026, 11, 12),
                "status": "present",
                "check_in": "09:00",
                "check_out": "17:00",
                "notes": None,
                "recorded_at": datetime(2026, 11, 12, 9, 0),
            }
        ]
        self.salary_rows: list[dict[str, object]] = [
            {
                "id": 2,
                "pay_period": date(2026, 10, 1),
                "gross_amount": Decimal("45000.00"),
                "allowances": Decimal("0.00"),
                "deductions": Decimal("3000.00"),
                "net_amount": Decimal("42000.00"),
                "status": "paid",
                "paid_at": datetime(2026, 10, 31, 12, 0),
                "notes": None,
            }
        ]
        self.student_rows: list[dict[str, object]] = [
            {
                "student_id": 501,
                "admission_number": "A-501",
                "class_name": "10-A",
                "username": "casey",
                "first_name": "Casey",
                "last_name": "Student",
                "attendance_status": None,
                "attendance_notes": None,
            }
        ]
        self.course_rows: list[dict[str, object]] = [
            {
                "id": 55,
                "course_code": "MATH-101",
                "name": "Mathematics",
                "description": "Math",
            }
        ]
        self.history_rows: list[dict[str, object]] = []
        self.note_rows: list[dict[str, object]] = []
        self.raise_on: str | None = None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> None:
        self.current_query = query.lower()
        self.current_params = params
        self.queries.append((query, params))
        if self.raise_on and self.raise_on in self.current_query:
            raise MySQLError("Database operation failed.")

    def fetchone(self) -> dict[str, object] | None:
        if "from staff as s" in self.current_query and "where s.user_id" in self.current_query:
            if self.missing_teacher:
                return None
            return {
                "staff_id": 88,
                "user_id": 42,
                "employee_number": "EMP000042",
                "designation": "Teacher",
                "hire_date": date(2026, 8, 1),
                "education": "B.Ed.",
                "base_salary": Decimal("45000.00"),
                "status": "active",
                "username": "taylor",
                "first_name": "Taylor",
                "last_name": "Teacher",
                "email": "taylor@example.com",
            }
        if "from courses as c" in self.current_query:
            if self.current_params[0] == 55 and not self.missing_course:
                return {"id": 55, "course_code": "MATH-101", "name": "Mathematics"}
            return None
        if "from academic_years" in self.current_query:
            if self.missing_academic_year:
                return None
            return {
                "id": 3,
                "name": f"{date.today().year}-{date.today().year + 1}",
                "start_date": date.today().replace(month=1, day=1),
                "end_date": date.today().replace(month=12, day=31),
            }
        if "as total_students" in self.current_query:
            return {"total_students": self.dashboard_counts["total_students"]}
        if "as attendance_taken" in self.current_query:
            return {"attendance_taken": self.dashboard_counts["attendance_taken"]}
        if "coalesce(sum(status = 'present')" in self.current_query:
            return {
                "present_days": 5,
                "absent_days": 0,
                "late_days": 0,
                "leave_days": 0,
            }
        if "select status, pay_period, net_amount" in self.current_query:
            return self.latest_salary
        if "select uploaded_at, download_count" in self.current_query:
            if self.note_metadata_missing:
                return None
            return {"uploaded_at": datetime(2026, 11, 13, 9, 0), "download_count": 0}
        if "n.content_type" in self.current_query:
            if self.missing_note:
                return None
            return {
                "stored_filename": "stored.pdf",
                "original_filename": "chapter.pdf",
                "content_type": "application/pdf",
            }
        if "from course_notes as n" in self.current_query:
            if self.missing_note:
                return None
            return {"id": 91, "course_id": 55, "stored_filename": "stored.pdf"}
        if "select id, title, description, original_filename" in self.current_query:
            return {
                "id": 91,
                "title": "Updated chapter",
                "description": "Revised notes",
                "original_filename": "chapter.pdf",
                "file_size": 12,
                "uploaded_at": datetime(2026, 11, 13, 9, 0),
                "download_count": 1,
            }
        return None

    def fetchall(self) -> list[dict[str, object]]:
        if "from staff_attendance" in self.current_query:
            return self.attendance_rows
        if "from salary_payments" in self.current_query:
            return self.salary_rows
        if "from student_courses" in self.current_query:
            if "student_id in" in self.current_query:
                return [
                    {"student_id": student_id}
                    for student_id in self.current_params[2:]
                    if student_id in self.enrolled_student_ids
                ]
            return self.student_rows
        if "from attendance_sessions as a" in self.current_query:
            return self.history_rows
        if "from courses" in self.current_query and "where teacher_id" in self.current_query:
            return self.course_rows
        if "from course_notes" in self.current_query:
            return self.note_rows
        if "from (" in self.current_query:
            return []
        return []

    @property
    def lastrowid(self) -> int:
        if "insert into course_notes" in self.current_query:
            return 91
        if "insert into attendance_sessions" in self.current_query:
            return 52
        return 0

    def close(self) -> None:
        pass


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.fake_cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self, dictionary: bool = False) -> FakeCursor:
        return self.fake_cursor

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


if __name__ == "__main__":
    unittest.main()
