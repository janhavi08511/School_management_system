from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mysql.connector import Error as MySQLError
import pytest

from Admin import create_admin_router
from AdminModules import create_admin_modules_router
from Auth import _create_access_token
from Teacher import create_teacher_router


AUTH_SECRET = "attendance-test-secret-key-at-least-32-characters"


@pytest.fixture
def attendance_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, "AttendanceDB", dict[str, str], dict[str, str]]:
    monkeypatch.setenv("AUTH_SECRET_KEY", AUTH_SECRET)
    database = AttendanceDB()

    def database_dependency():
        yield database

    app = FastAPI()
    app.include_router(create_admin_router(database_dependency))
    app.include_router(create_admin_modules_router(database_dependency))
    app.include_router(create_teacher_router(database_dependency))
    client = TestClient(app)
    admin_headers = {
        "Authorization": f"Bearer {_create_access_token('1', ['admin'])}"
    }
    teacher_headers = {
        "Authorization": f"Bearer {_create_access_token('42', ['teacher'])}"
    }
    return client, database, admin_headers, teacher_headers


def test_admin_records_and_lists_staff_attendance(attendance_api):
    client, database, admin_headers, _ = attendance_api
    attendance_date = date.today()

    recorded = client.post(
        "/admin/staff-attendance",
        headers=admin_headers,
        json={
            "staff_id": 88,
            "attendance_date": attendance_date.isoformat(),
            "status": "late",
            "check_in": "09:15",
            "check_out": "17:00",
            "notes": "  Traffic delay  ",
        },
    )
    listing = client.get(
        "/admin/staff-attendance",
        params={
            "attendance_date": attendance_date.isoformat(),
            "staff_type": "teacher",
            "staff_id": 88,
        },
        headers=admin_headers,
    )

    assert recorded.status_code == 200
    assert recorded.json()["status"] == "late"
    assert recorded.json()["notes"] == "Traffic delay"
    assert recorded.json()["recorded_by_username"] == "1"
    assert listing.status_code == 200
    assert listing.json()["data"][0]["name"] == "Taylor Teacher"
    assert listing.json()["data"][0]["attendance_status"] == "late"
    assert listing.json()["data"][0]["check_in"] == "09:15"
    assert database.commits == 1
    list_query = next(
        (query, params)
        for query, params in database.queries
        if "left join staff_attendance as a" in query.lower()
    )
    assert list_query[1] == (attendance_date, "teacher", 88, 25, 0)


def test_admin_staff_attendance_upserts_same_staff_and_date(attendance_api):
    client, database, admin_headers, _ = attendance_api
    payload = {
        "staff_id": 88,
        "attendance_date": date.today().isoformat(),
        "status": "present",
        "check_in": "08:55",
    }
    first = client.post("/admin/staff-attendance", headers=admin_headers, json=payload)
    payload.update({"status": "half_day", "notes": "Updated"})
    second = client.post("/admin/staff-attendance", headers=admin_headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(database.staff_attendance) == 1
    assert database.staff_attendance[0]["status"] == "half_day"
    assert database.staff_attendance[0]["notes"] == "Updated"
    assert database.commits == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"staff_id": 0, "attendance_date": "2026-11-18", "status": "present"},
        {"staff_id": 88, "attendance_date": "not-a-date", "status": "present"},
        {"staff_id": 88, "attendance_date": "2026-11-18", "status": "holiday"},
        {"staff_id": 88, "attendance_date": "2026-11-18", "status": "present", "notes": "x" * 501},
        {"staff_id": 88, "attendance_date": "2026-11-18", "status": "present", "check_in": "25:00"},
        {"staff_id": 88, "attendance_date": "2026-11-18", "status": "present", "check_out": "not-time"},
    ],
)
def test_admin_rejects_invalid_staff_attendance_without_database_access(
    attendance_api, payload
):
    client, database, admin_headers, _ = attendance_api

    response = client.post(
        "/admin/staff-attendance", headers=admin_headers, json=payload
    )

    assert response.status_code == 422
    assert database.queries == []
    assert database.commits == 0


def test_admin_cannot_record_attendance_for_missing_or_inactive_staff(attendance_api):
    client, database, admin_headers, _ = attendance_api
    database.inactive_staff_ids.add(88)
    original_attendance = database.staff_attendance.copy()

    response = client.post(
        "/admin/staff-attendance",
        headers=admin_headers,
        json={
            "staff_id": 88,
            "attendance_date": date.today().isoformat(),
            "status": "present",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Active staff member not found."
    assert database.rollbacks == 1
    assert database.commits == 0
    assert database.staff_attendance == original_attendance


def test_admin_staff_attendance_database_error_rolls_back(attendance_api):
    client, database, admin_headers, _ = attendance_api
    database.fail_on = "insert into staff_attendance"
    original_attendance = database.staff_attendance.copy()

    response = client.post(
        "/admin/staff-attendance",
        headers=admin_headers,
        json={
            "staff_id": 88,
            "attendance_date": date.today().isoformat(),
            "status": "present",
        },
    )

    assert response.status_code == 503
    assert database.rollbacks == 1
    assert database.commits == 0
    assert database.staff_attendance == original_attendance


def test_admin_staff_attendance_report_validates_month_and_summarizes_statuses(
    attendance_api,
):
    client, database, admin_headers, _ = attendance_api
    month_start = date.today().replace(day=1)
    next_month = (
        date(month_start.year + 1, 1, 1)
        if month_start.month == 12
        else date(month_start.year, month_start.month + 1, 1)
    )
    previous_month = month_start - timedelta(days=1)
    database.staff_attendance = [
        database.staff_record(month_start + timedelta(days=2), "present"),
        database.staff_record(month_start + timedelta(days=2), "late"),
        database.staff_record(month_start + timedelta(days=3), "on_leave"),
        database.staff_record(previous_month, "absent"),
    ]

    invalid = client.get(
        "/admin/staff-attendance/report",
        params={"month": "2026-13"},
        headers=admin_headers,
    )
    report = client.get(
        "/admin/staff-attendance/report",
        params={
            "month": month_start.strftime("%Y-%m"),
            "staff_type": "teacher",
            "staff_id": 88,
        },
        headers=admin_headers,
    )

    assert invalid.status_code == 422
    assert report.status_code == 200
    assert report.json()["month"] == month_start.strftime("%Y-%m")
    assert report.json()["summary"] == {
        "present": 1,
        "absent": 0,
        "late": 1,
        "half_day": 0,
        "on_leave": 1,
    }
    assert len(report.json()["daily"]) == 3
    assert len(report.json()["records"]) == 3
    assert database.queries[-2][1] == (month_start, next_month, "teacher", 88)


def test_admin_staff_attendance_list_requires_attendance_date(attendance_api):
    client, database, admin_headers, _ = attendance_api

    response = client.get("/admin/staff-attendance", headers=admin_headers)

    assert response.status_code == 422
    assert database.queries == []


def test_teacher_attendance_can_be_filtered_by_month_or_day(attendance_api):
    client, database, _, teacher_headers = attendance_api
    attendance_date = date.today()
    single_day = client.get(
        "/teacher/attendance",
        params={"attendance_date": attendance_date.isoformat()},
        headers=teacher_headers,
    )
    monthly = client.get(
        "/teacher/attendance",
        params={"month": attendance_date.strftime("%Y-%m")},
        headers=teacher_headers,
    )

    assert single_day.status_code == 200
    assert single_day.json()["summary"]["present_days"] == 1
    assert single_day.json()["summary"]["percentage"] == 100.0
    assert monthly.status_code == 200
    assert monthly.json()["month"] == attendance_date.strftime("%Y-%m")
    attendance_queries = [
        params
        for query, params in database.queries
        if "from staff_attendance" in query.lower()
    ]
    assert attendance_queries[0] == (88, attendance_date)
    assert attendance_queries[1] == (
        88,
        attendance_date.replace(day=1),
        date(
            attendance_date.year + (attendance_date.month == 12),
            attendance_date.month % 12 + 1,
            1,
        ),
    )


def test_teacher_attendance_rejects_invalid_month_and_conflicting_filters(attendance_api):
    client, database, _, teacher_headers = attendance_api
    invalid = client.get(
        "/teacher/attendance",
        params={"month": "2026-00"},
        headers=teacher_headers,
    )
    conflicting = client.get(
        "/teacher/attendance",
        params={"month": "2026-11", "attendance_date": date.today().isoformat()},
        headers=teacher_headers,
    )

    assert invalid.status_code == 422
    assert conflicting.status_code == 422
    assert database.queries == []


def test_teacher_attendance_summary_handles_no_working_days_and_leave_records(
    attendance_api,
):
    client, database, _, teacher_headers = attendance_api
    database.staff_attendance = [
        database.staff_record(date.today(), "on_leave"),
        database.staff_record(date.today(), "excused"),
    ]

    response = client.get(
        "/teacher/attendance",
        params={"attendance_date": date.today().isoformat()},
        headers=teacher_headers,
    )

    assert response.status_code == 200
    assert response.json()["summary"]["total_days"] == 2
    assert response.json()["summary"]["leave_days"] == 1
    assert response.json()["summary"]["percentage"] == 0


def test_teacher_views_assigned_course_students_and_existing_attendance(attendance_api):
    client, database, _, teacher_headers = attendance_api
    database.course_attendance[(55, date.today(), 501)] = {
        "status": "late",
        "notes": "Bus",
    }

    response = client.get(
        "/teacher/courses/55/students",
        params={"attendance_date": date.today().isoformat()},
        headers=teacher_headers,
    )

    assert response.status_code == 200
    assert response.json()["course"]["course_code"] == "MATH-101"
    assert response.json()["students"][0]["attendance_status"] == "late"
    assert response.json()["students"][0]["attendance_notes"] == "Bus"
    assert len(response.json()["students"]) == 2
    roster_query = next(
        params
        for query, params in database.queries
        if "left join attendance_sessions" in query.lower()
    )
    assert roster_query == (date.today(), 55, 3)


def test_teacher_course_students_rejects_unassigned_course_and_bad_dates(attendance_api):
    client, database, _, teacher_headers = attendance_api
    unassigned = client.get(
        "/teacher/courses/999/students",
        params={"attendance_date": date.today().isoformat()},
        headers=teacher_headers,
    )
    future = client.get(
        "/teacher/courses/55/students",
        params={"attendance_date": (date.today() + timedelta(days=1)).isoformat()},
        headers=teacher_headers,
    )
    old_date = client.get(
        "/teacher/courses/55/students",
        params={"attendance_date": date(date.today().year - 1, 12, 31).isoformat()},
        headers=teacher_headers,
    )

    assert unassigned.status_code == 404
    assert future.status_code == 422
    assert old_date.status_code == 422
    assert not any(
        "from student_courses" in query.lower()
        and "left join attendance_sessions" in query.lower()
        for query, _ in database.queries
    )


def test_teacher_course_students_rejects_missing_current_academic_year(attendance_api):
    client, database, _, teacher_headers = attendance_api
    database.academic_year = None

    response = client.get(
        "/teacher/courses/55/students",
        params={"attendance_date": date.today().isoformat()},
        headers=teacher_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "No current academic year is configured."
    assert not any(
        "left join attendance_sessions" in query.lower()
        for query, _ in database.queries
    )


def test_teacher_records_attendance_for_multiple_enrolled_students(attendance_api):
    client, database, _, teacher_headers = attendance_api

    response = client.post(
        "/teacher/courses/55/attendance",
        headers=teacher_headers,
        json={
            "attendance_date": date.today().isoformat(),
            "records": [
                {"student_id": 501, "status": "present"},
                {"student_id": 502, "status": "excused", "notes": "  Approved  "},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["students_recorded"] == 2
    assert database.commits == 1
    assert database.course_attendance[(55, date.today(), 501)] == {
        "status": "present",
        "notes": None,
    }
    assert database.course_attendance[(55, date.today(), 502)] == {
        "status": "excused",
        "notes": "Approved",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"attendance_date": "2026-11-18", "records": []},
        {
            "attendance_date": "2026-11-18",
            "records": [
                {"student_id": 501, "status": "present"},
                {"student_id": 501, "status": "absent"},
            ],
        },
        {"attendance_date": "2026-11-18", "records": [{"student_id": 0, "status": "present"}]},
        {"attendance_date": "2026-11-18", "records": [{"student_id": 501, "status": "holiday"}]},
        {
            "attendance_date": "2026-11-18",
            "records": [{"student_id": 501, "status": "present", "notes": "x" * 501}],
        },
        {"attendance_date": "not-a-date", "records": [{"student_id": 501, "status": "present"}]},
    ],
)
def test_teacher_attendance_rejects_invalid_payloads_before_database_access(
    attendance_api, payload
):
    client, database, _, teacher_headers = attendance_api

    response = client.post(
        "/teacher/courses/55/attendance",
        headers=teacher_headers,
        json=payload,
    )

    assert response.status_code == 422
    assert database.queries == []
    assert database.commits == 0


def test_teacher_rejects_unenrolled_students_and_rolls_back(attendance_api):
    client, database, _, teacher_headers = attendance_api

    response = client.post(
        "/teacher/courses/55/attendance",
        headers=teacher_headers,
        json={
            "attendance_date": date.today().isoformat(),
            "records": [{"student_id": 999, "status": "present"}],
        },
    )

    assert response.status_code == 422
    assert database.rollbacks == 1
    assert database.commits == 0
    assert not any(
        "insert into attendance_sessions" in query.lower()
        for query, _ in database.queries
    )


def test_teacher_attendance_database_error_rolls_back_all_changes(attendance_api):
    client, database, _, teacher_headers = attendance_api
    database.fail_on = "insert into attendance_records"

    response = client.post(
        "/teacher/courses/55/attendance",
        headers=teacher_headers,
        json={
            "attendance_date": date.today().isoformat(),
            "records": [{"student_id": 501, "status": "present"}],
        },
    )

    assert response.status_code == 503
    assert database.rollbacks == 1
    assert database.commits == 0
    assert database.course_attendance == {}
    assert database.sessions == {}


def test_teacher_course_attendance_history_validates_month_and_returns_records(
    attendance_api,
):
    client, database, _, teacher_headers = attendance_api
    database.course_attendance[(55, date.today(), 501)] = {
        "status": "late",
        "notes": "Bus",
    }

    invalid = client.get(
        "/teacher/courses/55/attendance/history",
        params={"month": "2026-00"},
        headers=teacher_headers,
    )
    history = client.get(
        "/teacher/courses/55/attendance/history",
        params={"month": date.today().strftime("%Y-%m")},
        headers=teacher_headers,
    )

    assert invalid.status_code == 422
    assert history.status_code == 200
    assert history.json()["records"][0]["name"] == "Casey Student"
    assert history.json()["records"][0]["status"] == "late"
    assert history.json()["records"][0]["notes"] == "Bus"


def test_teacher_course_attendance_history_rejects_unassigned_course(attendance_api):
    client, _, _, teacher_headers = attendance_api

    response = client.get(
        "/teacher/courses/999/attendance/history",
        params={"month": date.today().strftime("%Y-%m")},
        headers=teacher_headers,
    )

    assert response.status_code == 404


def test_attendance_routes_require_the_matching_role(attendance_api):
    client, database, _, teacher_headers = attendance_api
    student_token = _create_access_token("45", ["student"])
    student_headers = {"Authorization": f"Bearer {student_token}"}

    admin_denied = client.get(
        "/admin/staff-attendance",
        params={"attendance_date": date.today().isoformat()},
        headers=teacher_headers,
    )
    teacher_denied = client.get("/teacher/attendance", headers=student_headers)
    no_token = client.post(
        "/admin/staff-attendance",
        headers={},
        json={
            "staff_id": 88,
            "attendance_date": date.today().isoformat(),
            "status": "present",
        },
    )

    assert admin_denied.status_code == 403
    assert teacher_denied.status_code == 403
    assert no_token.status_code == 401
    assert database.queries == []


class AttendanceDB:
    def __init__(self) -> None:
        self.teacher = {
            "staff_id": 88,
            "user_id": 42,
            "employee_number": "EMP000042",
            "designation": "Teacher",
            "hire_date": date(2024, 8, 1),
            "education": "B.Ed.",
            "base_salary": Decimal("45000.00"),
            "status": "active",
            "username": "taylor",
            "first_name": "Taylor",
            "last_name": "Teacher",
            "email": "taylor@example.com",
        }
        self.staff = [
            {
                "staff_id": 88,
                "employee_number": "EMP000042",
                "staff_type": "teacher",
                "designation": "Teacher",
                "staff_status": "active",
                "first_name": "Taylor",
                "last_name": "Teacher",
                "username": "taylor",
            },
            {
                "staff_id": 89,
                "employee_number": "EMP000043",
                "staff_type": "non_teaching",
                "designation": "Clerk",
                "staff_status": "active",
                "first_name": "Alex",
                "last_name": "Clerk",
                "username": "alex",
            },
        ]
        self.inactive_staff_ids: set[int] = set()
        self.staff_attendance = [
            self.staff_record(date.today(), "present")
        ]
        self.academic_year: dict[str, Any] | None = {
            "id": 3,
            "name": f"{date.today().year}-{date.today().year + 1}",
            "start_date": date(date.today().year, 1, 1),
            "end_date": date(date.today().year, 12, 31),
        }
        self.course = {"id": 55, "course_code": "MATH-101", "name": "Mathematics"}
        self.students = [
            {
                "student_id": 501,
                "admission_number": "A-501",
                "class_name": "10-A",
                "username": "casey",
                "first_name": "Casey",
                "last_name": "Student",
                "attendance_status": None,
                "attendance_notes": None,
            },
            {
                "student_id": 502,
                "admission_number": "A-502",
                "class_name": "10-A",
                "username": "jordan",
                "first_name": "Jordan",
                "last_name": "Student",
                "attendance_status": None,
                "attendance_notes": None,
            },
        ]
        self.enrolled_student_ids = {501, 502}
        self.sessions: dict[tuple[int, date], dict[str, Any]] = {}
        self.course_attendance: dict[tuple[int, date, int], dict[str, Any]] = {}
        self.pending_staff: list[dict[str, Any]] = []
        self.pending_session: dict[tuple[int, date], dict[str, Any]] | None = None
        self.pending_records: list[tuple[tuple[int, date, int], dict[str, Any]]] = []
        self.queries: list[tuple[str, tuple[Any, ...]]] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_on: str | None = None
        self.lastrowid = 52

    @staticmethod
    def staff_record(attendance_date: date, status: str) -> dict[str, Any]:
        return {
            "staff_id": 88,
            "attendance_date": attendance_date,
            "status": status,
            "check_in": "09:00",
            "check_out": "17:00",
            "notes": None,
            "recorded_by_username": "admin",
            "staff_type": "teacher",
            "employee_number": "EMP000042",
            "name": "Taylor Teacher",
        }

    def cursor(self, dictionary: bool = False) -> "AttendanceCursor":
        return AttendanceCursor(self)

    def commit(self) -> None:
        for row in self.pending_staff:
            self.staff_attendance = [
                existing
                for existing in self.staff_attendance
                if not (
                    existing["staff_id"] == row["staff_id"]
                    and existing["attendance_date"] == row["attendance_date"]
                )
            ]
            self.staff_attendance.append(row)
        if self.pending_session:
            self.sessions.update(self.pending_session)
        for key, record in self.pending_records:
            self.course_attendance[key] = record
        self.pending_staff = []
        self.pending_session = None
        self.pending_records = []
        self.commits += 1

    def rollback(self) -> None:
        self.pending_staff = []
        self.pending_session = None
        self.pending_records = []
        self.rollbacks += 1


class AttendanceCursor:
    def __init__(self, database: AttendanceDB) -> None:
        self.database = database
        self.query = ""
        self.params: tuple[Any, ...] = ()
        self.result: dict[str, Any] | None = None
        self.rows: list[dict[str, Any]] = []
        self.row_id = 0

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        normalized = " ".join(query.lower().split())
        self.query = normalized
        self.params = tuple(params)
        self.database.queries.append((query, self.params))
        self.result = None
        self.rows = []

        if self.database.fail_on and self.database.fail_on in normalized:
            raise MySQLError("Simulated database error.")

        if "from staff as s" in normalized and "where s.user_id" in normalized:
            if self.params[0] == self.database.teacher["user_id"]:
                self.result = self.database.teacher
        elif "select id from staff where id = %s and status = 'active'" in normalized:
            if (
                self.params[0] in {row["staff_id"] for row in self.database.staff}
                and self.params[0] not in self.database.inactive_staff_ids
            ):
                self.result = {"id": self.params[0]}
        elif "select count(*) as total" in normalized and "from staff as s" in normalized:
            staff_type = self.params[0] if self.params and isinstance(self.params[0], str) else None
            staff_id = self.params[1] if staff_type and len(self.params) > 1 else (
                self.params[0] if self.params and isinstance(self.params[0], int) else None
            )
            rows = [
                row for row in self.database.staff
                if (not staff_type or row["staff_type"] == staff_type)
                and (not staff_id or row["staff_id"] == staff_id)
            ]
            self.result = {"total": len(rows)}
        elif "select count(*) as total" in normalized and "from staff_attendance as a" in normalized:
            start, end = self.params[:2]
            staff_type = self.params[2] if len(self.params) > 2 and isinstance(self.params[2], str) else None
            staff_id = self.params[3] if len(self.params) > 3 else None
            rows = [
                row for row in self.database.staff_attendance
                if start <= row["attendance_date"] < end
                and (not staff_type or row["staff_type"] == staff_type)
                and (not staff_id or row["staff_id"] == staff_id)
            ]
            self.result = {"total": len(rows)}
        elif "select c.id, c.course_code, c.name from courses as c" in normalized:
            if self.params[0] == self.database.course["id"]:
                self.result = self.database.course
        elif "from academic_years" in normalized:
            self.result = self.database.academic_year
        elif "select sc.student_id from student_courses as sc" in normalized:
            self.rows = [
                {"student_id": student_id}
                for student_id in self.params[2:]
                if student_id in self.database.enrolled_student_ids
            ]
        elif "insert into staff_attendance" in normalized:
            staff_id, day, status, check_in, check_out, notes, recorder = self.params
            self.database.pending_staff.append(
                {
                    "staff_id": staff_id,
                    "attendance_date": day,
                    "status": status,
                    "check_in": check_in,
                    "check_out": check_out,
                    "notes": notes,
                    "recorded_by_username": recorder,
                    "staff_type": self._staff_type(staff_id),
                    "employee_number": "EMP000042",
                    "name": "Taylor Teacher",
                }
            )
        elif (
            "from staff_attendance as a" in normalized
            and "select a.attendance_date, a.status, count(*)" in normalized
        ):
            start, end = self.params[:2]
            grouped = Counter(
                (row["attendance_date"], row["status"])
                for row in self.database.staff_attendance
                if start <= row["attendance_date"] < end
                and self._staff_filter_matches(row, self.params[2:])
            )
            self.rows = [
                {"attendance_date": day, "status": status, "count": count}
                for (day, status), count in grouped.items()
            ]
        elif "from staff_attendance as a" in normalized and "select s.id as staff_id" in normalized:
            start, end = self.params[:2]
            self.rows = [
                {
                    **row,
                    "staff_id": row["staff_id"],
                    "name": "Taylor Teacher",
                }
                for row in self.database.staff_attendance
                if start <= row["attendance_date"] < end
                and self._staff_filter_matches(row, self.params[2:])
            ]
        elif "from staff_attendance" in normalized and "where staff_id = %s" in normalized:
            staff_id = self.params[0]
            if "attendance_date = %s" in normalized:
                self.rows = [
                    row
                    for row in self.database.staff_attendance
                    if row["staff_id"] == staff_id
                    and row["attendance_date"] == self.params[1]
                ]
            else:
                start, end = self.params[1:]
                self.rows = [
                    row
                    for row in self.database.staff_attendance
                    if row["staff_id"] == staff_id
                    and start <= row["attendance_date"] < end
                ]
        elif "from staff as s" in normalized and "left join staff_attendance as a" in normalized:
            day = self.params[0]
            staff_type = self.params[1] if len(self.params) > 1 else None
            staff_id = self.params[2] if len(self.params) > 2 else None
            self.rows = []
            for staff in self.database.staff:
                if staff_type and staff["staff_type"] != staff_type:
                    continue
                if staff_id and staff["staff_id"] != staff_id:
                    continue
                attendance = next(
                    (
                        row
                        for row in self.database.staff_attendance
                        if row["staff_id"] == staff["staff_id"]
                        and row["attendance_date"] == day
                    ),
                    None,
                )
                self.rows.append(
                    {
                        **staff,
                        "attendance_status": attendance["status"] if attendance else None,
                        "check_in": self._time_text(attendance["check_in"]) if attendance else None,
                        "check_out": self._time_text(attendance["check_out"]) if attendance else None,
                        "notes": attendance["notes"] if attendance else None,
                    }
                )
        elif "select id, name, start_date, end_date" in normalized and "from academic_years" in normalized:
            self.result = self.database.academic_year
        elif "from student_courses as sc" in normalized and "left join attendance_sessions" in normalized:
            attendance_date, course_id, _year_id = self.params
            self.rows = []
            for student in self.database.students:
                attendance = self.database.course_attendance.get(
                    (course_id, attendance_date, student["student_id"])
                )
                self.rows.append(
                    {
                        **student,
                        "attendance_status": attendance["status"] if attendance else None,
                        "attendance_notes": attendance["notes"] if attendance else None,
                        "name": f"{student['first_name']} {student['last_name']}",
                    }
                )
        elif "insert into attendance_sessions" in normalized:
            course_id, year_id, day, recorded_by = self.params
            session_key = (course_id, day)
            session = self.database.sessions.get(session_key)
            self.row_id = session["id"] if session else self.database.lastrowid
            self.database.pending_session = {
                session_key: {
                    "id": self.row_id,
                    "course_id": course_id,
                    "academic_year_id": year_id,
                    "attendance_date": day,
                    "recorded_by": recorded_by,
                }
            }
        elif "insert into attendance_records" in normalized:
            _session_id, course_id, _year_id, student_id, status, notes = self.params
            session = self.database.sessions.get((course_id, self._attendance_date()))
            if session:
                day = session["attendance_date"]
            elif self.database.pending_session:
                day = next(iter(self.database.pending_session))[1]
            else:
                day = date.today()
            self.database.pending_records.append(
                (
                    (course_id, day, student_id),
                    {"status": status, "notes": notes},
                )
            )
        elif "from attendance_sessions as a" in normalized and "join attendance_records as r" in normalized:
            course_id, _year_id, start, end = self.params
            self.rows = []
            for (record_course_id, day, student_id), record in self.database.course_attendance.items():
                if record_course_id != course_id or not start <= day < end:
                    continue
                student = next(
                    row
                    for row in self.database.students
                    if row["student_id"] == student_id
                )
                self.rows.append(
                    {
                        "attendance_date": day,
                        "student_id": student_id,
                        "admission_number": student["admission_number"],
                        "class_name": student["class_name"],
                        "first_name": student["first_name"],
                        "last_name": student["last_name"],
                        "status": record["status"],
                        "notes": record["notes"],
                        "name": f"{student['first_name']} {student['last_name']}",
                    }
                )

    def _staff_filter_matches(
        self, row: dict[str, Any], filters: tuple[Any, ...]
    ) -> bool:
        if filters and isinstance(filters[0], str):
            if row["staff_type"] != filters[0]:
                return False
            filters = filters[1:]
        return not filters or row["staff_id"] == filters[0]

    def _attendance_date(self) -> date:
        if self.database.pending_session:
            return next(iter(self.database.pending_session))[1]
        return date.today()

    def _staff_type(self, staff_id: int) -> str:
        return next(
            row["staff_type"]
            for row in self.database.staff
            if row["staff_id"] == staff_id
        )

    @staticmethod
    def _time_text(value: Any) -> Any:
        return value.strftime("%H:%M") if isinstance(value, time) else value

    def fetchone(self) -> dict[str, Any] | None:
        return self.result

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows

    @property
    def lastrowid(self) -> int:
        return self.row_id or self.database.lastrowid

    def close(self) -> None:
        pass
