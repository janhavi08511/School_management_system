from datetime import date
from decimal import Decimal
import mimetypes
from pathlib import Path
import re
from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from mysql.connector import Error as MySQLError
from mysql.connector import MySQLConnection
from pydantic import BaseModel, Field

from Auth import DatabaseDependency, _require_teacher

NOTE_STORAGE_DIR = Path(__file__).resolve().parent / "uploads" / "course_notes"
MAX_NOTE_SIZE = 15 * 1024 * 1024
ALLOWED_NOTE_EXTENSIONS = {".doc", ".docx", ".pdf", ".ppt", ".pptx"}


class StudentAttendanceEntry(BaseModel):
    student_id: int = Field(gt=0)
    status: Literal["present", "absent", "late", "excused"]
    notes: Optional[str] = Field(default=None, max_length=500)


class CourseAttendanceRequest(BaseModel):
    attendance_date: date
    records: list[StudentAttendanceEntry] = Field(min_length=1)


class CourseNoteUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    description: Optional[str] = Field(default=None, max_length=2000)


def _teacher_user_id(claims: dict[str, Any]) -> int:
    try:
        return int(claims["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Teacher account is not valid.",
        ) from exc


def _get_teacher(cursor: Any, user_id: int) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT
            s.id AS staff_id,
            s.user_id,
            s.employee_number,
            s.designation,
            s.hire_date,
            s.education,
            s.base_salary,
            s.status,
            u.username,
            u.first_name,
            u.last_name,
            u.email
        FROM staff AS s
        JOIN users AS u ON u.id = s.user_id
        WHERE s.user_id = %s AND s.staff_type = 'teacher'
        """,
        (user_id,),
    )
    teacher = cursor.fetchone()
    if teacher is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Teacher profile not found.",
        )
    return teacher


def _get_assigned_course(
    cursor: Any,
    user_id: int,
    course_id: int,
) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT c.id, c.course_code, c.name
        FROM courses AS c
        JOIN staff AS s ON s.id = c.teacher_id
        WHERE c.id = %s AND s.user_id = %s AND s.staff_type = 'teacher'
        """,
        (course_id, user_id),
    )
    course = cursor.fetchone()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assigned course not found.",
        )
    return course


def _get_assigned_note(cursor: Any, user_id: int, note_id: int) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT n.id, n.course_id, n.stored_filename
        FROM course_notes AS n
        JOIN courses AS c ON c.id = n.course_id
        JOIN staff AS s ON s.id = c.teacher_id
        WHERE n.id = %s AND s.user_id = %s AND s.staff_type = 'teacher'
        """,
        (note_id, user_id),
    )
    note = cursor.fetchone()
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course note not found.",
        )
    return note


def _current_academic_year(cursor: Any) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT id, name, start_date, end_date
        FROM academic_years
        WHERE is_current = TRUE
        ORDER BY start_date DESC, id DESC
        LIMIT 1
        """
    )
    academic_year = cursor.fetchone()
    if academic_year is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No current academic year is configured.",
        )
    return academic_year


def _validate_attendance_date(attendance_date: date, academic_year: dict[str, Any]) -> None:
    if (
        attendance_date > date.today()
        or attendance_date < academic_year["start_date"]
        or attendance_date > academic_year["end_date"]
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Attendance can only be recorded within the current academic year and not for a future date.",
        )


def create_teacher_router(database_dependency: DatabaseDependency) -> APIRouter:
    router = APIRouter(prefix="/teacher", tags=["teacher"])

    @router.get("/profile")
    def get_teacher_profile(
        claims: dict[str, Any] = Depends(_require_teacher),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        cursor = connection.cursor(dictionary=True)
        try:
            teacher = _get_teacher(cursor, _teacher_user_id(claims))
        except HTTPException:
            raise
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load the teacher profile.",
            ) from exc
        finally:
            cursor.close()

        return {
            **teacher,
            "name": f"{teacher['first_name']} {teacher['last_name']}".strip(),
            "base_salary": f"{Decimal(teacher['base_salary']):.2f}",
        }

    @router.get("/attendance")
    def get_teacher_attendance(
        month: Optional[str] = None,
        attendance_date: Optional[date] = None,
        claims: dict[str, Any] = Depends(_require_teacher),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        if month is not None and attendance_date is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Select either a month or a single attendance date.",
            )
        if attendance_date is None:
            month = month or date.today().strftime("%Y-%m")
            if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Month must use the YYYY-MM format.",
                )
            year_number, month_number = (int(value) for value in month.split("-"))
            start_date = date(year_number, month_number, 1)
            end_date = (
                date(year_number + 1, 1, 1)
                if month_number == 12
                else date(year_number, month_number + 1, 1)
            )
        cursor = connection.cursor(dictionary=True)
        try:
            teacher = _get_teacher(cursor, _teacher_user_id(claims))
            date_filter = (
                "AND attendance_date = %s"
                if attendance_date is not None
                else "AND attendance_date >= %s AND attendance_date < %s"
            )
            parameters: tuple[Any, ...] = (
                (teacher["staff_id"], attendance_date)
                if attendance_date is not None
                else (teacher["staff_id"], start_date, end_date)
            )
            cursor.execute(
                f"""
                SELECT
                    attendance_date,
                    status,
                    TIME_FORMAT(check_in, '%H:%i') AS check_in,
                    TIME_FORMAT(check_out, '%H:%i') AS check_out,
                    notes,
                    recorded_at
                FROM staff_attendance
                WHERE staff_id = %s
                  {date_filter}
                ORDER BY attendance_date DESC
                """,
                parameters,
            )
            records = cursor.fetchall()
        except HTTPException:
            raise
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load teacher attendance.",
            ) from exc
        finally:
            cursor.close()

        counts = {
            "present_days": sum(record["status"] == "present" for record in records),
            "absent_days": sum(record["status"] == "absent" for record in records),
            "late_days": sum(record["status"] == "late" for record in records),
            "leave_days": sum(record["status"] == "on_leave" for record in records),
        }
        working_days = (
            counts["present_days"] + counts["absent_days"] + counts["late_days"]
        )
        return {
            "month": month,
            "attendance_date": attendance_date,
            "records": records,
            "summary": {
                **counts,
                "total_days": len(records),
                "percentage": (
                    round(
                        (
                            (counts["present_days"] + counts["late_days"])
                            / working_days
                        )
                        * 100,
                        1,
                    )
                    if working_days
                    else 0
                ),
            },
        }

    @router.get("/salary")
    def get_teacher_salary(
        claims: dict[str, Any] = Depends(_require_teacher),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        cursor = connection.cursor(dictionary=True)
        try:
            teacher = _get_teacher(cursor, _teacher_user_id(claims))
            cursor.execute(
                """
                SELECT
                    id,
                    pay_period,
                    gross_amount,
                    allowances,
                    deductions,
                    net_amount,
                    status,
                    paid_at,
                    notes
                FROM salary_payments
                WHERE staff_id = %s
                ORDER BY pay_period DESC, id DESC
                """,
                (teacher["staff_id"],),
            )
            payments = cursor.fetchall()
        except HTTPException:
            raise
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load teacher salary records.",
            ) from exc
        finally:
            cursor.close()

        return {
            "base_salary": f"{Decimal(teacher['base_salary']):.2f}",
            "payments": [
                {
                    **payment,
                    "gross_amount": f"{Decimal(payment['gross_amount']):.2f}",
                    "allowances": f"{Decimal(payment['allowances']):.2f}",
                    "deductions": f"{Decimal(payment['deductions']):.2f}",
                    "net_amount": f"{Decimal(payment['net_amount']):.2f}",
                }
                for payment in payments
            ],
        }

    @router.get("/courses")
    def get_teacher_courses(
        claims: dict[str, Any] = Depends(_require_teacher),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> list[dict[str, Any]]:
        cursor = connection.cursor(dictionary=True)
        try:
            teacher = _get_teacher(cursor, _teacher_user_id(claims))
            cursor.execute(
                """
                SELECT id, course_code, name, description
                FROM courses
                WHERE teacher_id = %s
                ORDER BY course_code
                """,
                (teacher["staff_id"],),
            )
            return cursor.fetchall()
        except HTTPException:
            raise
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load assigned courses.",
            ) from exc
        finally:
            cursor.close()

    @router.get("/dashboard")
    def get_teacher_dashboard(
        claims: dict[str, Any] = Depends(_require_teacher),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        today = date.today()
        month_start = today.replace(day=1)
        next_month = (
            today.replace(year=today.year + 1, month=1, day=1)
            if today.month == 12
            else today.replace(month=today.month + 1, day=1)
        )
        cursor = connection.cursor(dictionary=True)
        try:
            user_id = _teacher_user_id(claims)
            teacher = _get_teacher(cursor, user_id)
            academic_year = _current_academic_year(cursor)
            cursor.execute(
                """
                SELECT id, course_code, name, description
                FROM courses
                WHERE teacher_id = %s
                ORDER BY course_code
                """,
                (teacher["staff_id"],),
            )
            courses = cursor.fetchall()
            cursor.execute(
                """
                SELECT COUNT(DISTINCT sc.student_id) AS total_students
                FROM student_courses AS sc
                JOIN courses AS c ON c.id = sc.course_id
                JOIN students AS s ON s.id = sc.student_id
                WHERE c.teacher_id = %s
                  AND sc.academic_year_id = %s
                  AND sc.status = 'enrolled'
                  AND s.status = 'active'
                """,
                (teacher["staff_id"], academic_year["id"]),
            )
            total_students = cursor.fetchone()["total_students"]
            cursor.execute(
                """
                SELECT
                    sc.id,
                    c.course_code,
                    c.name AS course_name,
                    TIME_FORMAT(sc.start_time, '%H:%i') AS start_time,
                    TIME_FORMAT(sc.end_time, '%H:%i') AS end_time,
                    sc.class_name,
                    sc.room
                FROM teacher_course_schedules AS sc
                JOIN courses AS c ON c.id = sc.course_id
                WHERE c.teacher_id = %s AND sc.day_of_week = %s
                ORDER BY sc.start_time, c.course_code
                """,
                (teacher["staff_id"], today.weekday()),
            )
            todays_classes = cursor.fetchall()
            cursor.execute(
                """
                SELECT COUNT(*) AS attendance_taken
                FROM attendance_sessions AS a
                JOIN courses AS c ON c.id = a.course_id
                WHERE c.teacher_id = %s
                  AND a.academic_year_id = %s
                  AND a.attendance_date = %s
                  AND a.recorded_by = %s
                """,
                (teacher["staff_id"], academic_year["id"], today, user_id),
            )
            attendance_taken = cursor.fetchone()["attendance_taken"]
            cursor.execute(
                """
                SELECT
                    COALESCE(SUM(status = 'present'), 0) AS present_days,
                    COALESCE(SUM(status = 'absent'), 0) AS absent_days,
                    COALESCE(SUM(status = 'late'), 0) AS late_days,
                    COALESCE(SUM(status = 'on_leave'), 0) AS leave_days
                FROM staff_attendance
                WHERE staff_id = %s
                  AND attendance_date >= %s
                  AND attendance_date < %s
                """,
                (teacher["staff_id"], month_start, next_month),
            )
            attendance = cursor.fetchone()
            cursor.execute(
                """
                SELECT status, pay_period, net_amount
                FROM salary_payments
                WHERE staff_id = %s
                ORDER BY pay_period DESC, id DESC
                LIMIT 1
                """,
                (teacher["staff_id"],),
            )
            latest_salary = cursor.fetchone()
            cursor.execute(
                """
                SELECT activity_type, title, activity_date
                FROM (
                    SELECT
                        'Student attendance' AS activity_type,
                        CONCAT('Attendance recorded for ', c.course_code) AS title,
                        a.created_at AS activity_date
                    FROM attendance_sessions AS a
                    JOIN courses AS c ON c.id = a.course_id
                    WHERE c.teacher_id = %s AND a.recorded_by = %s
                    UNION ALL
                    SELECT
                        'Course notes' AS activity_type,
                        CONCAT('Uploaded ', n.title, ' to ', c.course_code) AS title,
                        n.uploaded_at AS activity_date
                    FROM course_notes AS n
                    JOIN courses AS c ON c.id = n.course_id
                    WHERE c.teacher_id = %s AND n.uploaded_by = %s
                ) AS recent_activities
                ORDER BY activity_date DESC
                LIMIT 8
                """,
                (teacher["staff_id"], user_id, teacher["staff_id"], teacher["staff_id"]),
            )
            recent_activities = cursor.fetchall()
        except HTTPException:
            raise
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load the teacher dashboard.",
            ) from exc
        finally:
            cursor.close()

        present_days = int(attendance["present_days"] or 0)
        absent_days = int(attendance["absent_days"] or 0)
        late_days = int(attendance["late_days"] or 0)
        leave_days = int(attendance["leave_days"] or 0)
        working_days = present_days + absent_days + late_days
        attendance_percentage = (
            round(((present_days + late_days) / working_days) * 100, 1)
            if working_days
            else 0
        )
        return {
            "profile": {
                **teacher,
                "name": f"{teacher['first_name']} {teacher['last_name']}".strip(),
                "base_salary": f"{Decimal(teacher['base_salary']):.2f}",
            },
            "assigned_courses": courses,
            "total_students": total_students,
            "todays_classes": todays_classes,
            "attendance_taken": attendance_taken,
            "monthly_attendance": {
                "month": today.strftime("%Y-%m"),
                "present_days": present_days,
                "absent_days": absent_days,
                "late_days": late_days,
                "leave_days": leave_days,
                "percentage": attendance_percentage,
            },
            "salary_status": (
                {
                    "status": latest_salary["status"],
                    "pay_period": latest_salary["pay_period"],
                    "net_amount": f"{Decimal(latest_salary['net_amount']):.2f}",
                }
                if latest_salary
                else {"status": "not_recorded", "pay_period": None, "net_amount": None}
            ),
            "recent_activities": recent_activities,
        }

    @router.get("/courses/{course_id}/students")
    def get_course_students(
        course_id: int,
        attendance_date: date,
        claims: dict[str, Any] = Depends(_require_teacher),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        cursor = connection.cursor(dictionary=True)
        try:
            user_id = _teacher_user_id(claims)
            course = _get_assigned_course(cursor, user_id, course_id)
            academic_year = _current_academic_year(cursor)
            _validate_attendance_date(attendance_date, academic_year)
            cursor.execute(
                """
                SELECT
                    s.id AS student_id,
                    s.admission_number,
                    s.class_name,
                    u.username,
                    u.first_name,
                    u.last_name,
                    r.status AS attendance_status,
                    r.notes AS attendance_notes
                FROM student_courses AS sc
                JOIN students AS s ON s.id = sc.student_id
                JOIN users AS u ON u.id = s.user_id
                LEFT JOIN attendance_sessions AS a
                    ON a.course_id = sc.course_id
                    AND a.academic_year_id = sc.academic_year_id
                    AND a.attendance_date = %s
                LEFT JOIN attendance_records AS r
                    ON r.session_id = a.id AND r.student_id = s.id
                WHERE sc.course_id = %s
                  AND sc.academic_year_id = %s
                  AND sc.status = 'enrolled'
                  AND s.status = 'active'
                ORDER BY u.last_name, u.first_name, s.admission_number
                """,
                (attendance_date, course_id, academic_year["id"]),
            )
            students = [
                {
                    **row,
                    "name": f"{row['first_name']} {row['last_name']}".strip(),
                }
                for row in cursor.fetchall()
            ]
        except HTTPException:
            raise
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load students for this course.",
            ) from exc
        finally:
            cursor.close()

        return {
            "course": course,
            "academic_year": academic_year,
            "attendance_date": attendance_date,
            "students": students,
        }

    @router.post("/courses/{course_id}/attendance")
    def record_course_attendance(
        course_id: int,
        request: CourseAttendanceRequest,
        claims: dict[str, Any] = Depends(_require_teacher),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        student_ids = [record.student_id for record in request.records]
        if len(student_ids) != len(set(student_ids)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Each student can appear only once in an attendance submission.",
            )

        cursor = connection.cursor(dictionary=True)
        try:
            user_id = _teacher_user_id(claims)
            _get_teacher(cursor, user_id)
            course = _get_assigned_course(cursor, user_id, course_id)
            academic_year = _current_academic_year(cursor)
            _validate_attendance_date(request.attendance_date, academic_year)

            placeholders = ", ".join(["%s"] * len(student_ids))
            cursor.execute(
                f"""
                SELECT sc.student_id
                FROM student_courses AS sc
                JOIN students AS s ON s.id = sc.student_id
                WHERE sc.course_id = %s
                  AND sc.academic_year_id = %s
                  AND sc.status = 'enrolled'
                  AND s.status = 'active'
                  AND sc.student_id IN ({placeholders})
                """,
                (course_id, academic_year["id"], *student_ids),
            )
            enrolled_ids = {row["student_id"] for row in cursor.fetchall()}
            if enrolled_ids != set(student_ids):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Attendance includes a student not enrolled in this course for the current academic year.",
                )

            cursor.execute(
                """
                INSERT INTO attendance_sessions (
                    course_id, academic_year_id, attendance_date, recorded_by
                )
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    id = LAST_INSERT_ID(id),
                    recorded_by = VALUES(recorded_by)
                """,
                (course_id, academic_year["id"], request.attendance_date, user_id),
            )
            session_id = cursor.lastrowid
            for record in request.records:
                cursor.execute(
                    """
                    INSERT INTO attendance_records (
                        session_id, course_id, academic_year_id,
                        student_id, status, notes
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        status = VALUES(status),
                        notes = VALUES(notes)
                    """,
                    (
                        session_id,
                        course_id,
                        academic_year["id"],
                        record.student_id,
                        record.status,
                        record.notes.strip() if record.notes else None,
                    ),
                )
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to save course attendance.",
            ) from exc
        finally:
            cursor.close()

        return {
            "course_id": course["id"],
            "course_code": course["course_code"],
            "attendance_date": request.attendance_date,
            "students_recorded": len(request.records),
        }

    @router.get("/courses/{course_id}/attendance/history")
    def get_course_attendance_history(
        course_id: int,
        month: Optional[str] = None,
        claims: dict[str, Any] = Depends(_require_teacher),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        month = month or date.today().strftime("%Y-%m")
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Month must use the YYYY-MM format.",
            )
        year_number, month_number = (int(value) for value in month.split("-"))
        start_date = date(year_number, month_number, 1)
        end_date = (
            date(year_number + 1, 1, 1)
            if month_number == 12
            else date(year_number, month_number + 1, 1)
        )
        cursor = connection.cursor(dictionary=True)
        try:
            user_id = _teacher_user_id(claims)
            course = _get_assigned_course(cursor, user_id, course_id)
            academic_year = _current_academic_year(cursor)
            cursor.execute(
                """
                SELECT
                    a.attendance_date,
                    s.id AS student_id,
                    s.admission_number,
                    s.class_name,
                    u.first_name,
                    u.last_name,
                    r.status,
                    r.notes
                FROM attendance_sessions AS a
                JOIN attendance_records AS r ON r.session_id = a.id
                JOIN students AS s ON s.id = r.student_id
                JOIN users AS u ON u.id = s.user_id
                WHERE a.course_id = %s
                  AND a.academic_year_id = %s
                  AND a.attendance_date >= %s
                  AND a.attendance_date < %s
                ORDER BY a.attendance_date DESC, u.last_name, u.first_name
                """,
                (course_id, academic_year["id"], start_date, end_date),
            )
            records = [
                {
                    **row,
                    "name": f"{row['first_name']} {row['last_name']}".strip(),
                }
                for row in cursor.fetchall()
            ]
        except HTTPException:
            raise
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load attendance history.",
            ) from exc
        finally:
            cursor.close()

        return {
            "course": course,
            "month": month,
            "records": records,
        }

    @router.get("/courses/{course_id}/notes")
    def list_course_notes(
        course_id: int,
        claims: dict[str, Any] = Depends(_require_teacher),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> list[dict[str, Any]]:
        cursor = connection.cursor(dictionary=True)
        try:
            _get_assigned_course(cursor, _teacher_user_id(claims), course_id)
            cursor.execute(
                """
                SELECT
                    id,
                    title,
                    description,
                    original_filename,
                    file_size,
                    uploaded_at,
                    download_count
                FROM course_notes
                WHERE course_id = %s
                ORDER BY uploaded_at DESC, id DESC
                """,
                (course_id,),
            )
            return cursor.fetchall()
        except HTTPException:
            raise
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load course notes.",
            ) from exc
        finally:
            cursor.close()

    @router.post("/courses/{course_id}/notes", status_code=status.HTTP_201_CREATED)
    def upload_course_note(
        course_id: int,
        title: str = Form(min_length=1, max_length=150),
        description: str = Form(default="", max_length=2000),
        file: UploadFile = File(...),
        claims: dict[str, Any] = Depends(_require_teacher),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        note_title = title.strip()
        note_description = description.strip() or None
        original_filename = Path(file.filename or "").name
        original_filename = "".join(
            character for character in original_filename if character.isprintable()
        )[:255]
        extension = Path(original_filename).suffix.lower()
        if not note_title or not original_filename:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A title and filename are required.",
            )
        if extension not in ALLOWED_NOTE_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Upload a PDF, DOC, DOCX, PPT, or PPTX file.",
            )

        stored_filename = f"{uuid4().hex}{extension}"
        stored_path = NOTE_STORAGE_DIR / stored_filename
        file_saved = False
        cursor = connection.cursor(dictionary=True)
        try:
            user_id = _teacher_user_id(claims)
            teacher = _get_teacher(cursor, user_id)
            _get_assigned_course(cursor, user_id, course_id)

            NOTE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            file_size = 0
            with stored_path.open("xb") as output:
                while True:
                    chunk = file.file.read(64 * 1024)
                    if not chunk:
                        break
                    file_size += len(chunk)
                    if file_size > MAX_NOTE_SIZE:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="Course notes must be 15 MB or smaller.",
                        )
                    output.write(chunk)
            if file_size == 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="The uploaded file is empty.",
                )

            content_type = mimetypes.guess_type(original_filename)[0]
            cursor.execute(
                """
                INSERT INTO course_notes (
                    course_id, uploaded_by, title, description,
                    original_filename, stored_filename, content_type, file_size
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    course_id,
                    teacher["staff_id"],
                    note_title,
                    note_description,
                    original_filename,
                    stored_filename,
                    content_type or "application/octet-stream",
                    file_size,
                ),
            )
            note_id = cursor.lastrowid
            cursor.execute(
                """
                SELECT uploaded_at, download_count
                FROM course_notes
                WHERE id = %s
                """,
                (note_id,),
            )
            note_metadata = cursor.fetchone()
            if note_metadata is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to confirm saved course note details.",
                )
            connection.commit()
            file_saved = True
        except HTTPException:
            connection.rollback()
            raise
        except OSError as exc:
            connection.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to store the uploaded course note.",
            ) from exc
        except MySQLError as exc:
            connection.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to save course note details.",
            ) from exc
        finally:
            cursor.close()
            if not file_saved:
                stored_path.unlink(missing_ok=True)

        return {
            "id": note_id,
            "course_id": course_id,
            "title": note_title,
            "description": note_description,
            "original_filename": original_filename,
            "file_size": file_size,
            "uploaded_at": note_metadata["uploaded_at"],
            "download_count": note_metadata["download_count"],
        }

    @router.patch("/notes/{note_id}")
    def update_course_note(
        note_id: int,
        request: CourseNoteUpdateRequest,
        claims: dict[str, Any] = Depends(_require_teacher),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        title = request.title.strip()
        description = request.description.strip() if request.description else None
        if not title:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Note title cannot be empty.",
            )
        cursor = connection.cursor(dictionary=True)
        try:
            _get_assigned_note(cursor, _teacher_user_id(claims), note_id)
            cursor.execute(
                """
                UPDATE course_notes
                SET title = %s, description = %s
                WHERE id = %s
                """,
                (title, description, note_id),
            )
            cursor.execute(
                """
                SELECT id, title, description, original_filename,
                       file_size, uploaded_at, download_count
                FROM course_notes
                WHERE id = %s
                """,
                (note_id,),
            )
            updated_note = cursor.fetchone()
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to update course note.",
            ) from exc
        finally:
            cursor.close()
        if updated_note is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Updated course note could not be loaded.",
            )
        return updated_note

    @router.delete("/notes/{note_id}")
    def delete_course_note(
        note_id: int,
        claims: dict[str, Any] = Depends(_require_teacher),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, str]:
        cursor = connection.cursor(dictionary=True)
        try:
            note = _get_assigned_note(cursor, _teacher_user_id(claims), note_id)
            cursor.execute("DELETE FROM course_notes WHERE id = %s", (note_id,))
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to delete course note.",
            ) from exc
        finally:
            cursor.close()

        stored_path = NOTE_STORAGE_DIR / Path(note["stored_filename"]).name
        try:
            stored_path.unlink(missing_ok=True)
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The note record was deleted but its file could not be removed.",
            ) from exc
        return {"message": "Course note deleted."}

    @router.get("/notes/{note_id}/download")
    def download_course_note(
        note_id: int,
        claims: dict[str, Any] = Depends(_require_teacher),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> FileResponse:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT
                    n.stored_filename,
                    n.original_filename,
                    n.content_type
                FROM course_notes AS n
                JOIN courses AS c ON c.id = n.course_id
                JOIN staff AS s ON s.id = c.teacher_id
                WHERE n.id = %s AND s.user_id = %s
                  AND s.staff_type = 'teacher'
                """,
                (note_id, _teacher_user_id(claims)),
            )
            note = cursor.fetchone()
            if note is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Course note not found.",
                )
            stored_filename = Path(note["stored_filename"]).name
            stored_path = NOTE_STORAGE_DIR / stored_filename
            if not stored_path.is_file():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Course note file is no longer available.",
                )
            cursor.execute(
                "UPDATE course_notes SET download_count = download_count + 1 WHERE id = %s",
                (note_id,),
            )
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load the course note.",
            ) from exc
        finally:
            cursor.close()

        return FileResponse(
            stored_path,
            media_type=note["content_type"],
            filename=note["original_filename"],
        )

    return router