from datetime import date, time
from decimal import Decimal
import logging
import re
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from mysql.connector import Error as MySQLError
from mysql.connector import MySQLConnection
from pydantic import BaseModel, Field

from Auth import DatabaseDependency, _require_admin

logger = logging.getLogger(__name__)


class CourseCreateRequest(BaseModel):
    course_code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=1, max_length=150)
    description: Optional[str] = Field(default=None, max_length=5000)
    class_name: Optional[str] = Field(default=None, max_length=80)
    duration_months: Optional[int] = Field(default=None, ge=1, le=120)
    academic_year_id: Optional[int] = Field(default=None, gt=0)
    teacher_id: Optional[int] = Field(default=None, gt=0)


class CourseScheduleCreateRequest(BaseModel):
    course_id: int = Field(gt=0)
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    class_name: Optional[str] = Field(default=None, max_length=80)
    room: Optional[str] = Field(default=None, max_length=80)


class FeePaymentRequest(BaseModel):
    student_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_method: Literal["cash", "card", "bank_transfer", "online", "other"]
    transaction_reference: Optional[str] = Field(default=None, max_length=120)
    notes: Optional[str] = Field(default=None, max_length=500)


class StaffAttendanceRequest(BaseModel):
    staff_id: int = Field(gt=0)
    attendance_date: date
    status: Literal["present", "absent", "late", "half_day", "on_leave"]
    check_in: Optional[time] = None
    check_out: Optional[time] = None
    notes: Optional[str] = Field(default=None, max_length=500)


def create_admin_router(database_dependency: DatabaseDependency) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])

    @router.get("/academic-years")
    def list_academic_years(
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> list[dict[str, Any]]:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT id, name, start_date, end_date, is_current
                FROM academic_years
                ORDER BY start_date DESC, id DESC
                """
            )
            return cursor.fetchall()
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load academic years.",
            ) from exc
        finally:
            cursor.close()

    @router.get("/analytics")
    def get_admin_analytics(
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM students WHERE status = 'active')
                        AS active_students,
                    (SELECT COUNT(*) FROM staff
                     WHERE staff_type = 'teacher' AND status = 'active')
                        AS active_teachers,
                    (SELECT COUNT(*) FROM staff
                     WHERE staff_type = 'non_teaching' AND status = 'active')
                        AS active_non_teaching_staff,
                    (SELECT COUNT(*) FROM courses) AS courses,
                    (SELECT COUNT(*) FROM course_notes) AS course_notes,
                    (SELECT COALESCE(SUM(s.fee_amount), 0)
                     FROM students AS s WHERE s.status = 'active')
                      + (SELECT COALESCE(SUM(i.amount), 0)
                         FROM fee_invoices AS i WHERE i.status != 'waived')
                        AS total_fee_amount,
                    (SELECT COALESCE(SUM(p.amount), 0)
                     FROM student_fee_payments AS p)
                      + (SELECT COALESCE(SUM(p.amount), 0)
                         FROM fee_payments AS p)
                        AS fee_amount_collected,
                    (SELECT COALESCE(SUM(sp.net_amount), 0)
                     FROM salary_payments AS sp
                     WHERE sp.status = 'paid'
                       AND sp.pay_period >= DATE_FORMAT(CURRENT_DATE(), '%Y-%m-01')
                       AND sp.pay_period < DATE_ADD(
                           DATE_FORMAT(CURRENT_DATE(), '%Y-%m-01'),
                           INTERVAL 1 MONTH
                       ))
                        AS salary_expenses,
                    (SELECT COUNT(*) FROM attendance_records AS r
                     JOIN attendance_sessions AS a ON a.id = r.session_id
                     WHERE a.attendance_date = CURRENT_DATE()
                       AND r.status = 'present')
                        AS student_attendance_present_today,
                    (SELECT COUNT(*) FROM attendance_records AS r
                     JOIN attendance_sessions AS a ON a.id = r.session_id
                     WHERE a.attendance_date = CURRENT_DATE()
                       AND r.status = 'absent')
                        AS student_attendance_absent_today,
                    (SELECT COUNT(*) FROM attendance_records AS r
                     JOIN attendance_sessions AS a ON a.id = r.session_id
                     WHERE a.attendance_date = CURRENT_DATE()
                       AND r.status = 'late')
                        AS student_attendance_late_today,
                    (SELECT COUNT(*) FROM attendance_records AS r
                     JOIN attendance_sessions AS a ON a.id = r.session_id
                     WHERE a.attendance_date = CURRENT_DATE()
                       AND r.status = 'excused')
                        AS student_attendance_excused_today,
                    (SELECT COUNT(*) FROM staff_attendance
                     WHERE attendance_date = CURRENT_DATE()
                       AND status = 'present')
                        AS staff_attendance_present_today,
                    (SELECT COUNT(*) FROM staff_attendance
                     WHERE attendance_date = CURRENT_DATE()
                       AND status = 'absent')
                        AS staff_attendance_absent_today,
                    (SELECT COUNT(*) FROM staff_attendance
                     WHERE attendance_date = CURRENT_DATE()
                       AND status = 'late')
                        AS staff_attendance_late_today,
                    (SELECT COUNT(*) FROM staff_attendance
                     WHERE attendance_date = CURRENT_DATE()
                       AND status = 'on_leave')
                        AS staff_attendance_on_leave_today
                """
            )
            metrics = cursor.fetchone()
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load admin analytics.",
            ) from exc
        finally:
            cursor.close()

        if metrics is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Analytics data is unavailable.",
            )

        total_fees = Decimal(metrics["total_fee_amount"])
        collected_fees = Decimal(metrics["fee_amount_collected"])
        return {
            **metrics,
            "total_fee_amount": f"{total_fees:.2f}",
            "fee_amount_collected": f"{collected_fees:.2f}",
            "salary_expenses": f"{Decimal(metrics['salary_expenses']):.2f}",
            "fee_balance": f"{max(total_fees - collected_fees, Decimal('0')):.2f}",
        }

    @router.get("/directory")
    def list_user_directory(
        student_page: int = Query(default=1, ge=1),
        teacher_page: int = Query(default=1, ge=1),
        non_teaching_page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
        search: Optional[str] = Query(default=None, max_length=120),
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        """Return paginated directory pages; course lists are fetched only for page IDs."""
        cursor = connection.cursor(dictionary=True)
        search_term = search.strip() if search else ""
        person_search = ""
        person_parameters: list[Any] = []
        if search_term:
            pattern = f"%{search_term}%"
            person_search = """
                AND (u.first_name LIKE %s OR u.last_name LIKE %s
                     OR CONCAT(u.first_name, ' ', u.last_name) LIKE %s
                     OR u.username LIKE %s OR u.email LIKE %s)
            """
            person_parameters = [pattern] * 5

        try:
            student_filters = person_search
            student_parameters = list(person_parameters)
            if search_term:
                student_filters += """
                    AND (s.admission_number LIKE %s OR s.class_name LIKE %s
                         OR EXISTS (SELECT 1 FROM student_courses sc
                                    JOIN courses c ON c.id = sc.course_id
                                    WHERE sc.student_id = s.id
                                      AND (c.name LIKE %s OR c.course_code LIKE %s)))
                """
                student_parameters.extend([pattern] * 4)

            cursor.execute(
                "SELECT COUNT(*) AS total FROM students s JOIN users u ON u.id = s.user_id WHERE 1=1 " + student_filters,
                tuple(student_parameters),
            )
            student_total = int(cursor.fetchone()["total"])
            student_offset = (student_page - 1) * page_size
            cursor.execute("""
                SELECT s.id, s.user_id, s.admission_number, s.date_of_birth,
                       s.gender, s.admission_date, s.address, s.parent_guardian_name,
                       s.parent_contact, s.status, s.class_name, s.fee_amount,
                       u.username, u.first_name, u.last_name, u.email, u.phone
                FROM students s JOIN users u ON u.id = s.user_id
                WHERE 1=1 """ + student_filters + " ORDER BY u.last_name, u.first_name, s.admission_number LIMIT %s OFFSET %s",
                tuple(student_parameters + [page_size, student_offset]),
            )
            student_rows = cursor.fetchall()
            if student_rows:
                student_ids = [int(row["id"]) for row in student_rows]
                marks = ",".join(["%s"] * len(student_ids))
                cursor.execute(f"""
                    SELECT sc.student_id,
                           GROUP_CONCAT(DISTINCT c.course_code ORDER BY c.course_code SEPARATOR ', ') AS course_codes
                    FROM student_courses sc JOIN courses c ON c.id = sc.course_id
                    WHERE sc.student_id IN ({marks})
                    GROUP BY sc.student_id
                """, tuple(student_ids))
                student_courses = {int(row["student_id"]): row["course_codes"] or "" for row in cursor.fetchall()}
            else:
                student_courses = {}
            students = [{**row, "name": f"{row['first_name']} {row['last_name']}".strip(), "fee_amount": f"{Decimal(row['fee_amount'] or 0):.2f}", "enrolled_courses": student_courses.get(int(row["id"]), "")} for row in student_rows]

            def fetch_staff_page(staff_type: str, page: int) -> tuple[list[dict[str, Any]], int, int]:
                staff_filters = ""
                staff_parameters = [staff_type, *person_parameters]
                if search_term:
                    staff_filters = """
                        AND (s.employee_number LIKE %s OR s.designation LIKE %s
                             OR s.department LIKE %s
                             OR EXISTS (SELECT 1 FROM courses c WHERE c.teacher_id = s.id
                                        AND (c.course_code LIKE %s OR c.name LIKE %s)))
                    """
                    staff_parameters.extend([pattern] * 5)
                cursor.execute("SELECT COUNT(*) AS total FROM staff s JOIN users u ON u.id = s.user_id WHERE s.staff_type = %s " + person_search + staff_filters, tuple(staff_parameters))
                total = int(cursor.fetchone()["total"])
                offset = (page - 1) * page_size
                cursor.execute("""
                    SELECT s.id, s.user_id, s.employee_number, s.staff_type, s.designation,
                           s.hire_date, s.education, s.experience_years, s.department,
                           s.address, s.base_salary, s.shift, s.status,
                           u.username, u.first_name, u.last_name, u.email, u.phone
                    FROM staff s JOIN users u ON u.id = s.user_id
                    WHERE s.staff_type = %s """ + person_search + staff_filters + " ORDER BY u.last_name, u.first_name, s.employee_number LIMIT %s OFFSET %s",
                    tuple(staff_parameters + [page_size, offset]),
                )
                rows = cursor.fetchall()
                if rows and staff_type == "teacher":
                    staff_ids = [int(row["id"]) for row in rows]
                    marks = ",".join(["%s"] * len(staff_ids))
                    cursor.execute(f"SELECT teacher_id, GROUP_CONCAT(course_code ORDER BY course_code SEPARATOR ', ') AS course_codes FROM courses WHERE teacher_id IN ({marks}) GROUP BY teacher_id", tuple(staff_ids))
                    course_map = {int(row["teacher_id"]): row["course_codes"] or "" for row in cursor.fetchall()}
                else:
                    course_map = {}
                normalized = [{**row, "name": f"{row['first_name']} {row['last_name']}".strip(), "base_salary": f"{Decimal(row['base_salary'] or 0):.2f}", "courses_taught": course_map.get(int(row["id"]), "")} for row in rows]
                return normalized, total, offset

            teacher_rows, teacher_total, teacher_offset = fetch_staff_page("teacher", teacher_page)
            non_teaching_rows, non_teaching_total, non_teaching_offset = fetch_staff_page("non_teaching", non_teaching_page)
        except MySQLError as exc:
            logger.exception("Directory endpoint database failure")
            raise HTTPException(status_code=503, detail="Unable to load the user directory.") from exc
        finally:
            cursor.close()

        def section(rows: list[dict[str, Any]], page: int, total: int, offset: int) -> dict[str, Any]:
            return {"data": rows, "pagination": {"page": page, "page_size": page_size, "total_records": total, "total_pages": (total + page_size - 1) // page_size, "has_next": offset + page_size < total, "has_previous": page > 1}}

        return {
            "students": section(students, student_page, student_total, student_offset),
            "teachers": section(teacher_rows, teacher_page, teacher_total, teacher_offset),
            "non_teaching_staff": section(non_teaching_rows, non_teaching_page, non_teaching_total, non_teaching_offset),
        }

    @router.get("/staff-attendance")
    def list_staff_attendance(
        attendance_date: date,
        staff_type: Optional[Literal["teacher", "non_teaching"]] = None,
        staff_id: Optional[int] = None,
        search: Optional[str] = Query(default=None, max_length=120),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        """Return one page of active staff attendance rows with server-side search."""
        offset = (page - 1) * page_size
        filters = ["s.status = 'active'"]
        parameters: list[Any] = []

        if staff_type:
            filters.append("s.staff_type = %s")
            parameters.append(staff_type)
        if staff_id:
            filters.append("s.id = %s")
            parameters.append(staff_id)

        search_term = search.strip() if search else ""
        if search_term:
            pattern = f"%{search_term}%"
            filters.append(
                """(
                    CONCAT(u.first_name, ' ', u.last_name) LIKE %s
                    OR u.first_name LIKE %s
                    OR u.last_name LIKE %s
                    OR u.username LIKE %s
                    OR s.employee_number LIKE %s
                    OR s.designation LIKE %s
                    OR s.department LIKE %s
                    OR EXISTS (
                        SELECT 1
                        FROM courses AS c
                        WHERE c.teacher_id = s.id
                          AND (c.course_code LIKE %s OR c.name LIKE %s)
                    )
                )"""
            )
            parameters.extend([pattern] * 9)

        where_sql = " AND ".join(filters)
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM staff AS s
                JOIN users AS u ON u.id = s.user_id
                WHERE {where_sql}
                """,
                tuple(parameters),
            )
            total = int(cursor.fetchone()["total"])

            cursor.execute(
                f"""
                SELECT
                    s.id AS staff_id,
                    s.employee_number,
                    s.staff_type,
                    s.designation,
                    s.department,
                    s.status AS staff_status,
                    u.first_name,
                    u.last_name,
                    u.username,
                    a.status AS attendance_status,
                    TIME_FORMAT(a.check_in, '%H:%i') AS check_in,
                    TIME_FORMAT(a.check_out, '%H:%i') AS check_out,
                    a.notes
                FROM staff AS s
                JOIN users AS u ON u.id = s.user_id
                LEFT JOIN staff_attendance AS a
                    ON a.staff_id = s.id AND a.attendance_date = %s
                WHERE {where_sql}
                ORDER BY u.last_name, u.first_name, s.employee_number
                LIMIT %s OFFSET %s
                """,
                tuple([attendance_date, *parameters, page_size, offset]),
            )
            rows = cursor.fetchall()
        except MySQLError as exc:
            logger.exception("Staff attendance endpoint database failure")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load staff attendance.",
            ) from exc
        finally:
            cursor.close()

        return {
            "data": [
                {
                    **row,
                    "name": f"{row['first_name']} {row['last_name']}".strip(),
                }
                for row in rows
            ],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_records": total,
                "total_pages": (total + page_size - 1) // page_size,
                "has_next": offset + page_size < total,
                "has_previous": page > 1,
            },
        }

    @router.post("/staff-attendance")
    def record_staff_attendance(
        request: StaffAttendanceRequest,
        admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        notes = request.notes.strip() if request.notes else None
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT id FROM staff WHERE id = %s AND status = 'active'",
                (request.staff_id,),
            )
            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Active staff member not found.",
                )

            cursor.execute(
                """
                INSERT INTO staff_attendance (
                    staff_id, attendance_date, status, check_in, check_out,
                    notes, recorded_by_username
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    status = VALUES(status),
                    check_in = VALUES(check_in),
                    check_out = VALUES(check_out),
                    notes = VALUES(notes),
                    recorded_by_username = VALUES(recorded_by_username)
                """,
                (
                    request.staff_id,
                    request.attendance_date,
                    request.status,
                    request.check_in,
                    request.check_out,
                    notes,
                    str(admin["sub"]),
                ),
            )
            connection.commit()
        except MySQLError as exc:
            connection.rollback()
            logger.exception("Staff attendance write failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to record staff attendance.",
            ) from exc
        except HTTPException:
            connection.rollback()
            raise
        finally:
            cursor.close()

        return {
            "staff_id": request.staff_id,
            "attendance_date": request.attendance_date,
            "status": request.status,
            "check_in": request.check_in,
            "check_out": request.check_out,
            "notes": notes,
            "recorded_by_username": str(admin["sub"]),
        }

    @router.get("/courses")
    def list_courses(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
        search: Optional[str] = Query(default=None, max_length=120),
        class_name: Optional[str] = Query(default=None, max_length=80),
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if class_name:
            clauses.append("class_name = %s")
            parameters.append(class_name.strip())
        if search and search.strip():
            pattern = f"%{search.strip()}%"
            clauses.append("(course_code LIKE %s OR name LIKE %s OR COALESCE(class_name, '') LIKE %s)")
            parameters.extend([pattern, pattern, pattern])

        where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        offset = (page - 1) * page_size
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(f"SELECT COUNT(*) AS total FROM courses{where_sql}", tuple(parameters))
            total = int((cursor.fetchone() or {"total": 0})["total"])
            cursor.execute(
                f"""
                SELECT id, course_code, name, description, class_name, duration_months,
                       academic_year_id, teacher_id, created_at
                FROM courses
                {where_sql}
                ORDER BY course_code
                LIMIT %s OFFSET %s
                """,
                tuple([*parameters, page_size, offset]),
            )
            rows = cursor.fetchall()
        except MySQLError as exc:
            logger.exception("Course catalog endpoint database failure")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load courses.",
            ) from exc
        finally:
            cursor.close()
        return {
            "data": rows,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_records": total,
                "total_pages": (total + page_size - 1) // page_size,
                "has_next": offset + page_size < total,
                "has_previous": page > 1,
            },
        }

    @router.get("/courses/{course_id}")
    def get_course(
        course_id: int,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT c.id, c.course_code, c.name, c.description, c.class_name,
                       c.duration_months, c.academic_year_id, c.teacher_id,
                       c.created_at,
                       ay.name AS academic_year_name,
                       CONCAT(u.first_name, ' ', u.last_name) AS teacher_name
                FROM courses AS c
                LEFT JOIN academic_years AS ay ON ay.id = c.academic_year_id
                LEFT JOIN staff AS s ON s.id = c.teacher_id
                LEFT JOIN users AS u ON u.id = s.user_id
                WHERE c.id = %s
                """,
                (course_id,),
            )
            course = cursor.fetchone()
            if course is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Course not found.",
                )
            return course
        except HTTPException:
            raise
        except MySQLError as exc:
            logger.exception("Course details endpoint database failure")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load course details.",
            ) from exc
        finally:
            cursor.close()

    @router.post("/courses", status_code=status.HTTP_201_CREATED)
    def create_course(
        request: CourseCreateRequest,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        course_code = request.course_code.strip().upper()
        course_name = request.name.strip()
        description = request.description.strip() if request.description else None
        class_name = request.class_name.strip() if request.class_name else None
        if not re.fullmatch(r"[A-Z0-9._-]{2,40}", course_code) or not course_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Course code and name are required; codes may contain letters, numbers, '.', '_' or '-'.",
            )

        cursor = connection.cursor(dictionary=True)
        try:
            if request.teacher_id is not None:
                cursor.execute(
                    "SELECT id FROM staff WHERE id = %s AND staff_type = 'teacher'",
                    (request.teacher_id,),
                )
                if cursor.fetchone() is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Select a valid teacher profile.",
                    )
            if request.academic_year_id is not None:
                cursor.execute(
                    "SELECT id FROM academic_years WHERE id = %s",
                    (request.academic_year_id,),
                )
                if cursor.fetchone() is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="The selected academic year does not exist.",
                    )
            cursor.execute(
                "SELECT id FROM courses WHERE course_code = %s",
                (course_code,),
            )
            if cursor.fetchone() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A course with that code already exists.",
                )

            cursor.execute(
                """
                INSERT INTO courses (
                    course_code, name, description, class_name, duration_months,
                    academic_year_id, teacher_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    course_code,
                    course_name,
                    description,
                    class_name,
                    request.duration_months,
                    request.academic_year_id,
                    request.teacher_id,
                ),
            )
            course_id = cursor.lastrowid
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            if exc.errno == 1062:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A course with that code already exists.",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to create the course.",
            ) from exc
        finally:
            cursor.close()

        return {
            "id": course_id,
            "course_code": course_code,
            "name": course_name,
            "description": description,
            "class_name": class_name,
            "duration_months": request.duration_months,
            "academic_year_id": request.academic_year_id,
            "teacher_id": request.teacher_id,
        }

    @router.get("/schedules")
    def list_course_schedules(
        day_of_week: Optional[int] = Query(default=None, ge=0, le=6),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1, le=100),
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        cursor = connection.cursor(dictionary=True)
        offset = (page - 1) * page_size
        try:
            clauses = ""
            parameters: list[Any] = []
            if day_of_week is not None:
                clauses = " WHERE sc.day_of_week = %s"
                parameters.append(day_of_week)
            cursor.execute(
                """
                SELECT sc.day_of_week, COUNT(*) AS total
                FROM teacher_course_schedules AS sc
                GROUP BY sc.day_of_week
                """
            )
            day_counts = {int(row["day_of_week"]): int(row["total"]) for row in cursor.fetchall()}
            cursor.execute(
                "SELECT COUNT(*) AS total FROM teacher_course_schedules AS sc" + clauses,
                tuple(parameters),
            )
            total = int((cursor.fetchone() or {"total": 0})["total"])
            cursor.execute(
                """
                SELECT
                    sc.id,
                    sc.course_id,
                    c.course_code,
                    c.name AS course_name,
                    sc.day_of_week,
                    TIME_FORMAT(sc.start_time, '%H:%i') AS start_time,
                    TIME_FORMAT(sc.end_time, '%H:%i') AS end_time,
                    sc.class_name,
                    sc.room,
                    CONCAT(u.first_name, ' ', u.last_name) AS teacher_name
                FROM teacher_course_schedules AS sc
                JOIN courses AS c ON c.id = sc.course_id
                LEFT JOIN staff AS s ON s.id = c.teacher_id
                LEFT JOIN users AS u ON u.id = s.user_id
                """ + clauses + """
                ORDER BY sc.day_of_week, sc.start_time, c.course_code
                LIMIT %s OFFSET %s
                """,
                tuple([*parameters, page_size, offset]),
            )
            rows = cursor.fetchall()
        except MySQLError as exc:
            logger.exception("Schedule catalog endpoint database failure")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load course schedules.",
            ) from exc
        finally:
            cursor.close()
        return {
            "data": rows,
            "day_counts": day_counts,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_records": total,
                "total_pages": (total + page_size - 1) // page_size,
                "has_next": offset + page_size < total,
                "has_previous": page > 1,
            },
        }

    @router.post("/schedules", status_code=status.HTTP_201_CREATED)
    def create_course_schedule(
        request: CourseScheduleCreateRequest,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        if request.end_time <= request.start_time:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Schedule end time must be after the start time.",
            )
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT id, teacher_id FROM courses WHERE id = %s",
                (request.course_id,),
            )
            course = cursor.fetchone()
            if course is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Course not found.",
                )
            if course["teacher_id"] is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Assign a teacher to this course before scheduling it.",
                )
            cursor.execute(
                """
                INSERT INTO teacher_course_schedules (
                    course_id, day_of_week, start_time, end_time, class_name, room
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    request.course_id,
                    request.day_of_week,
                    request.start_time,
                    request.end_time,
                    request.class_name.strip() if request.class_name else None,
                    request.room.strip() if request.room else None,
                ),
            )
            schedule_id = cursor.lastrowid
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            if exc.errno == 1062:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This course already has a schedule at that start time on this day.",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to create the course schedule.",
            ) from exc
        finally:
            cursor.close()

        return {
            "id": schedule_id,
            "course_id": request.course_id,
            "day_of_week": request.day_of_week,
            "start_time": request.start_time.strftime("%H:%M"),
            "end_time": request.end_time.strftime("%H:%M"),
            "class_name": request.class_name,
            "room": request.room,
        }

    @router.get("/enrollment-students")
    def search_enrollment_students(
        search: Optional[str] = Query(default=None, max_length=120),
        class_name: Optional[str] = Query(default=None, max_length=80),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        filters = ["s.status = 'active'"]
        parameters: list[Any] = []
        if class_name and class_name.strip():
            filters.append("s.class_name = %s")
            parameters.append(class_name.strip())
        search_term = search.strip() if search else ""
        if search_term:
            pattern = f"%{search_term}%"
            filters.append(
                """(
                    CONCAT(u.first_name, ' ', u.last_name) LIKE %s
                    OR u.first_name LIKE %s OR u.last_name LIKE %s
                    OR s.admission_number LIKE %s OR u.username LIKE %s
                )"""
            )
            parameters.extend([pattern] * 5)
        where_sql = " AND ".join(filters)
        offset = (page - 1) * page_size
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM students AS s
                JOIN users AS u ON u.id = s.user_id
                WHERE {where_sql}
                """,
                tuple(parameters),
            )
            total = int((cursor.fetchone() or {"total": 0})["total"])
            cursor.execute(
                f"""
                SELECT s.id, s.admission_number, s.class_name,
                       u.first_name, u.last_name
                FROM students AS s
                JOIN users AS u ON u.id = s.user_id
                WHERE {where_sql}
                ORDER BY u.last_name, u.first_name, s.admission_number
                LIMIT %s OFFSET %s
                """,
                tuple([*parameters, page_size, offset]),
            )
            rows = cursor.fetchall()
        except MySQLError as exc:
            logger.exception("Enrollment student search database failure")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to search students for enrollment.",
            ) from exc
        finally:
            cursor.close()

        return {
            "data": [
                {
                    **row,
                    "name": f"{row['first_name']} {row['last_name']}".strip(),
                }
                for row in rows
            ],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_records": total,
                "total_pages": (total + page_size - 1) // page_size,
                "has_next": offset + page_size < total,
                "has_previous": page > 1,
            },
        }

    @router.get("/students")
    def list_students_for_payments(
        search: Optional[str] = Query(default=None, max_length=120),
        class_name: Optional[str] = None,
        course_id: Optional[int] = None,
        student_status: Optional[Literal["active", "inactive", "graduated", "withdrawn"]] = None,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=100, ge=1, le=100),
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        filters: list[str] = []
        parameters: list[Any] = []
        search_term = search.strip() if search else ""
        if search_term:
            pattern = f"%{search_term}%"
            filters.append("(CONCAT(u.first_name, ' ', u.last_name) LIKE %s OR u.first_name LIKE %s OR u.last_name LIKE %s OR s.admission_number LIKE %s OR u.email LIKE %s)")
            parameters.extend([pattern] * 5)
        if class_name:
            filters.append("s.class_name = %s")
            parameters.append(class_name)
        if course_id:
            filters.append("EXISTS (SELECT 1 FROM student_courses sc WHERE sc.student_id = s.id AND sc.course_id = %s)")
            parameters.append(course_id)
        if student_status:
            filters.append("s.status = %s")
            parameters.append(student_status)
        where_sql = " WHERE " + " AND ".join(filters) if filters else ""
        offset = (page - 1) * page_size
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SELECT COUNT(*) AS total FROM students AS s JOIN users AS u ON u.id = s.user_id" + where_sql, tuple(parameters))
            total = int(cursor.fetchone()["total"])
            cursor.execute("""
                SELECT s.id, s.admission_number, s.class_name, s.status, s.fee_amount,
                       u.username, u.first_name, u.last_name
                FROM students AS s JOIN users AS u ON u.id = s.user_id
            """ + where_sql + " ORDER BY s.id DESC LIMIT %s OFFSET %s", tuple(parameters + [page_size, offset]))
            rows = cursor.fetchall()
            if rows:
                ids = [int(row["id"]) for row in rows]
                placeholders = ",".join(["%s"] * len(ids))
                cursor.execute(f"SELECT student_id, COALESCE(SUM(amount), 0) AS paid_amount FROM student_fee_payments WHERE student_id IN ({placeholders}) GROUP BY student_id", tuple(ids))
                paid_by_student = {int(row["student_id"]): row["paid_amount"] for row in cursor.fetchall()}
            else:
                paid_by_student = {}
        except MySQLError as exc:
            logger.exception("Students endpoint database failure")
            raise HTTPException(status_code=503, detail="Unable to load students and fee balances.") from exc
        finally:
            cursor.close()
        students = []
        for row in rows:
            total_fee = Decimal(row["fee_amount"] or 0)
            paid_amount = Decimal(paid_by_student.get(int(row["id"]), 0) or 0)
            students.append({"id": row["id"], "admission_number": row["admission_number"], "class_name": row["class_name"], "status": row["status"], "username": row["username"], "name": f"{row['first_name']} {row['last_name']}".strip(), "fee_amount": f"{total_fee:.2f}", "paid_amount": f"{paid_amount:.2f}", "balance": f"{max(total_fee - paid_amount, Decimal('0')):.2f}"})
        return {"data": students, "pagination": {"page": page, "page_size": page_size, "total_records": total, "total_pages": (total + page_size - 1) // page_size, "has_next": offset + page_size < total, "has_previous": page > 1}}

    @router.post("/payments", status_code=status.HTTP_201_CREATED)
    def create_fee_payment(
        request: FeePaymentRequest,
        admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        transaction_reference = (
            request.transaction_reference.strip()
            if request.transaction_reference
            else None
        )
        notes = request.notes.strip() if request.notes else None
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT id, fee_amount FROM students WHERE id = %s FOR UPDATE",
                (request.student_id,),
            )
            student = cursor.fetchone()
            if student is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Student not found.",
                )

            cursor.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS paid_amount
                FROM student_fee_payments
                WHERE student_id = %s
                """,
                (request.student_id,),
            )
            paid_amount = Decimal(cursor.fetchone()["paid_amount"])
            balance = max(Decimal(student["fee_amount"]) - paid_amount, Decimal("0"))
            if request.amount > balance:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Payment exceeds the remaining fee balance of {balance:.2f}.",
                )

            cursor.execute(
                """
                INSERT INTO student_fee_payments (
                    student_id, amount, payment_method, transaction_reference,
                    received_by_username, notes
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    request.student_id,
                    request.amount,
                    request.payment_method,
                    transaction_reference,
                    str(admin["sub"]),
                    notes,
                ),
            )
            payment_id = cursor.lastrowid
            remaining_balance = balance - request.amount
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            if exc.errno == 1062:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="That transaction reference has already been recorded.",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to record the fee payment.",
            ) from exc
        finally:
            cursor.close()

        return {
            "id": payment_id,
            "student_id": request.student_id,
            "amount": f"{request.amount:.2f}",
            "remaining_balance": f"{remaining_balance:.2f}",
        }

    @router.get("/payments")
    def list_fee_payments(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1, le=100),
        search: Optional[str] = Query(default=None, max_length=120),
        class_name: Optional[str] = Query(default=None, max_length=80),
        payment_method: Optional[
            Literal["cash", "card", "bank_transfer", "online", "other"]
        ] = None,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        filters: list[str] = []
        parameters: list[Any] = []
        search_term = search.strip() if search else ""
        if search_term:
            pattern = f"%{search_term}%"
            filters.append(
                """(
                    CONCAT(u.first_name, ' ', u.last_name) LIKE %s
                    OR u.first_name LIKE %s
                    OR u.last_name LIKE %s
                    OR s.admission_number LIKE %s
                    OR u.username LIKE %s
                    OR p.transaction_reference LIKE %s
                )"""
            )
            parameters.extend([pattern] * 6)
        if class_name and class_name.strip():
            filters.append("s.class_name = %s")
            parameters.append(class_name.strip())
        if payment_method:
            filters.append("p.payment_method = %s")
            parameters.append(payment_method)

        where_sql = " WHERE " + " AND ".join(filters) if filters else ""
        offset = (page - 1) * page_size
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM student_fee_payments AS p
                JOIN students AS s ON s.id = p.student_id
                JOIN users AS u ON u.id = s.user_id
                """ + where_sql,
                tuple(parameters),
            )
            total = int((cursor.fetchone() or {"total": 0})["total"])
            cursor.execute(
                """
                SELECT
                    p.id,
                    p.student_id,
                    p.amount,
                    p.paid_at,
                    p.payment_method,
                    p.transaction_reference,
                    p.received_by_username,
                    p.notes,
                    s.admission_number,
                    s.class_name,
                    u.username,
                    u.first_name,
                    u.last_name
                FROM student_fee_payments AS p
                JOIN students AS s ON s.id = p.student_id
                JOIN users AS u ON u.id = s.user_id
                """ + where_sql + """
                ORDER BY p.paid_at DESC, p.id DESC
                LIMIT %s OFFSET %s
                """,
                tuple(parameters + [page_size, offset]),
            )
            rows = cursor.fetchall()
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load fee payment entries.",
            ) from exc
        finally:
            cursor.close()

        return {
            "data": [
                {
                    **row,
                    "amount": f"{Decimal(row['amount']):.2f}",
                    "student_name": f"{row['first_name']} {row['last_name']}".strip(),
                }
                for row in rows
            ],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_records": total,
                "total_pages": (total + page_size - 1) // page_size,
                "has_next": offset + page_size < total,
                "has_previous": page > 1,
            },
        }

    return router
