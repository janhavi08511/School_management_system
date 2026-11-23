from datetime import date, datetime, time
from decimal import Decimal
import logging
from pathlib import Path
import re
from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from mysql.connector import Error as MySQLError
from mysql.connector import MySQLConnection
from pydantic import BaseModel, Field

from Auth import ADMIN_USERNAME, DatabaseDependency, _require_admin, hash_password

PROFILE_PHOTO_DIR = Path(__file__).resolve().parent / "uploads" / "profile_photos"
MAX_PROFILE_PHOTO_SIZE = 5 * 1024 * 1024
ALLOWED_PROFILE_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
logger = logging.getLogger(__name__)


class AdminUserUpdate(BaseModel):
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    email: Optional[str] = Field(default=None, min_length=3, max_length=254)
    phone: Optional[str] = Field(default=None, max_length=30)
    is_active: Optional[bool] = None


class AdminPasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class AdminRoleUpdate(BaseModel):
    role: Literal["student", "teacher", "non_teaching_staff"]


class AdminStudentUpdate(BaseModel):
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    email: Optional[str] = Field(default=None, min_length=3, max_length=254)
    phone: Optional[str] = Field(default=None, max_length=30)
    date_of_birth: Optional[date] = None
    gender: Optional[str] = Field(default=None, max_length=30)
    address: Optional[str] = Field(default=None, max_length=500)
    class_name: Optional[str] = Field(default=None, max_length=80)
    admission_date: Optional[date] = None
    parent_guardian_name: Optional[str] = Field(default=None, max_length=160)
    parent_contact: Optional[str] = Field(default=None, max_length=30)
    status: Optional[Literal["active", "inactive", "graduated", "withdrawn"]] = None


class AdminStaffUpdate(BaseModel):
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    email: Optional[str] = Field(default=None, min_length=3, max_length=254)
    phone: Optional[str] = Field(default=None, max_length=30)
    designation: Optional[str] = Field(default=None, min_length=1, max_length=120)
    hire_date: Optional[date] = None
    education: Optional[str] = Field(default=None, max_length=500)
    experience_years: Optional[Decimal] = Field(default=None, ge=0, max_digits=4, decimal_places=1)
    department: Optional[str] = Field(default=None, max_length=120)
    address: Optional[str] = Field(default=None, max_length=500)
    base_salary: Optional[Decimal] = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    shift: Optional[str] = Field(default=None, max_length=80)
    status: Optional[Literal["active", "inactive", "on_leave", "terminated"]] = None


class AdminCourseUpdate(BaseModel):
    course_code: Optional[str] = Field(default=None, min_length=2, max_length=40)
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    description: Optional[str] = Field(default=None, max_length=5000)
    class_name: Optional[str] = Field(default=None, max_length=80)
    duration_months: Optional[int] = Field(default=None, ge=1, le=120)
    academic_year_id: Optional[int] = Field(default=None, gt=0)
    teacher_id: Optional[int] = Field(default=None, gt=0)


class FeeTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=255)
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    class_name: Optional[str] = Field(default=None, max_length=80)
    academic_year_id: Optional[int] = Field(default=None, gt=0)


class FeeInvoiceCreate(BaseModel):
    student_id: int = Field(gt=0)
    fee_type_id: int = Field(gt=0)
    academic_year_id: int = Field(gt=0)
    amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    due_date: date


class FeeClassInvoiceCreate(BaseModel):
    class_name: str = Field(min_length=1, max_length=80)
    fee_type_id: int = Field(gt=0)
    academic_year_id: int = Field(gt=0)
    amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    due_date: date


class InvoicePaymentRequest(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_method: Literal["cash", "card", "bank_transfer", "online", "other"]
    transaction_reference: Optional[str] = Field(default=None, max_length=120)
    notes: Optional[str] = Field(default=None, max_length=500)


class StudentInvoicePaymentRequest(InvoicePaymentRequest):
    student_id: int = Field(gt=0)
    fee_type_id: int = Field(gt=0)
    academic_year_id: int = Field(gt=0)
    invoice_due_date: Optional[date] = None


class PayrollUpdate(BaseModel):
    allowances: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    deductions: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class AssessmentCreate(BaseModel):
    student_id: int = Field(gt=0)
    course_id: int = Field(gt=0)
    academic_year_id: int = Field(gt=0)
    exam_name: str = Field(min_length=1, max_length=150)
    marks_obtained: Decimal = Field(ge=0, max_digits=7, decimal_places=2)
    total_marks: Decimal = Field(gt=0, max_digits=7, decimal_places=2)


class SchoolEventRequest(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    description: Optional[str] = Field(default=None, max_length=2000)
    starts_at: datetime
    ends_at: Optional[datetime] = None


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _admin_user_id(admin: dict[str, Any]) -> Optional[int]:
    subject = admin.get("sub")
    if subject == ADMIN_USERNAME:
        return None
    try:
        user_id = int(subject)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrator account is not valid.",
        ) from exc
    if user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrator account is not valid.",
        )
    return user_id


def _grade(percentage: float) -> str:
    if percentage >= 90:
        return "A"
    if percentage >= 80:
        return "B"
    if percentage >= 70:
        return "C"
    if percentage >= 60:
        return "D"
    return "F"


def _not_found(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)


def create_admin_modules_router(database_dependency: DatabaseDependency) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin management"])

    @router.get("/dashboard")
    def get_dashboard(
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        today = date.today()
        month_start = today.replace(day=1)
        next_month = (
            month_start.replace(year=month_start.year + 1, month=1)
            if month_start.month == 12
            else month_start.replace(month=month_start.month + 1)
        )
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM students WHERE status = 'active') AS total_students,
                    (SELECT COUNT(*) FROM students AS sx LEFT JOIN (SELECT student_id, SUM(amount) AS paid_amount FROM student_fee_payments GROUP BY student_id) AS px ON px.student_id = sx.id WHERE sx.status = 'active' AND sx.fee_amount > COALESCE(px.paid_amount, 0)) AS students_with_balance,
                    (SELECT COUNT(*) FROM staff WHERE staff_type = 'teacher' AND status = 'active') AS total_teachers,
                    (SELECT COUNT(*) FROM staff WHERE staff_type = 'non_teaching' AND status = 'active') AS total_non_teaching_staff,
                    (SELECT COUNT(*) FROM courses) AS total_courses,
                    (SELECT COALESCE(SUM(fee_amount), 0) FROM students WHERE status = 'active')
                      + (SELECT COALESCE(SUM(amount), 0) FROM fee_invoices WHERE status != 'waived') AS total_fees,
                    (SELECT COALESCE(SUM(amount), 0) FROM student_fee_payments)
                      + (SELECT COALESCE(SUM(amount), 0) FROM fee_payments) AS fees_collected,
                    (SELECT COALESCE(SUM(net_amount), 0) FROM salary_payments
                     WHERE status = 'paid' AND pay_period >= %s AND pay_period < %s) AS salary_expenses,
                    (SELECT COUNT(*) FROM staff_attendance WHERE attendance_date = %s AND status = 'present') AS staff_present_today,
                    (SELECT COUNT(*) FROM staff_attendance WHERE attendance_date = %s AND status = 'absent') AS staff_absent_today,
                    (SELECT COUNT(*) FROM staff_attendance WHERE attendance_date = %s AND status = 'late') AS staff_late_today,
                    (SELECT COUNT(*) FROM staff_attendance WHERE attendance_date = %s AND status = 'half_day') AS staff_half_day_today,
                    (SELECT COUNT(*) FROM staff_attendance WHERE attendance_date = %s AND status = 'on_leave') AS staff_leave_today
                """,
                (month_start, next_month, today, today, today, today, today),
            )
            metrics = cursor.fetchone()
            cursor.execute(
                """
                SELECT class_name, COUNT(*) AS student_count
                FROM students
                WHERE status = 'active'
                GROUP BY class_name
                ORDER BY class_name
                """
            )
            enrollment = cursor.fetchall()
            cursor.execute(
                """
                SELECT DATE_FORMAT(paid_at, '%Y-%m') AS month, SUM(amount) AS amount
                FROM (
                    SELECT paid_at, amount FROM student_fee_payments
                    UNION ALL
                    SELECT paid_at, amount FROM fee_payments
                ) AS all_payments
                WHERE paid_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 5 MONTH)
                GROUP BY DATE_FORMAT(paid_at, '%Y-%m')
                ORDER BY month
                """
            )
            fee_statistics = cursor.fetchall()
            cursor.execute(
                """
                SELECT DATE_FORMAT(attendance_date, '%Y-%m') AS month, status, COUNT(*) AS count
                FROM staff_attendance
                WHERE attendance_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 5 MONTH)
                GROUP BY DATE_FORMAT(attendance_date, '%Y-%m'), status
                ORDER BY month
                """
            )
            staff_attendance = cursor.fetchall()
            cursor.execute(
                """
                SELECT DATE_FORMAT(pay_period, '%Y-%m') AS month, SUM(net_amount) AS amount
                FROM salary_payments
                WHERE status = 'paid'
                  AND pay_period >= DATE_SUB(CURRENT_DATE(), INTERVAL 5 MONTH)
                GROUP BY DATE_FORMAT(pay_period, '%Y-%m')
                ORDER BY month
                """
            )
            salary_statistics = cursor.fetchall()
            cursor.execute(
                """
                SELECT c.course_code, AVG(a.marks_obtained / a.total_marks * 100) AS average_percentage
                FROM student_assessments AS a
                JOIN courses AS c ON c.id = a.course_id
                WHERE a.created_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 12 MONTH)
                GROUP BY c.id, c.course_code
                ORDER BY c.course_code
                """
            )
            course_performance = cursor.fetchall()
            cursor.execute(
                """
                SELECT s.class_name, AVG(a.marks_obtained / a.total_marks * 100) AS average_percentage
                FROM student_assessments AS a
                JOIN students AS s ON s.id = a.student_id
                WHERE a.created_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 12 MONTH)
                GROUP BY s.class_name
                ORDER BY s.class_name
                """
            )
            class_performance = cursor.fetchall()
            cursor.execute(
                """
                SELECT DATE_FORMAT(a.created_at, '%Y-%m') AS month,
                       AVG(a.marks_obtained / a.total_marks * 100) AS average_percentage
                FROM student_assessments AS a
                WHERE a.created_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 11 MONTH)
                GROUP BY DATE_FORMAT(a.created_at, '%Y-%m')
                ORDER BY month
                """
            )
            performance_trends = cursor.fetchall()
            cursor.execute(
                """
                SELECT *
                FROM (
                    (SELECT p.id, p.amount, p.paid_at, p.payment_method,
                            s.admission_number, u.first_name, u.last_name,
                            'legacy' AS source
                     FROM student_fee_payments AS p
                     JOIN students AS s ON s.id = p.student_id
                     JOIN users AS u ON u.id = s.user_id
                     ORDER BY p.paid_at DESC, p.id DESC LIMIT 8)
                    UNION ALL
                    (SELECT p.id, p.amount, p.paid_at, p.payment_method,
                            s.admission_number, u.first_name, u.last_name,
                            'invoice' AS source
                     FROM fee_payments AS p
                     JOIN fee_invoices AS i ON i.id = p.invoice_id
                     JOIN students AS s ON s.id = i.student_id
                     JOIN users AS u ON u.id = s.user_id
                     ORDER BY p.paid_at DESC, p.id DESC LIMIT 8)
                ) AS payments
                ORDER BY paid_at DESC, id DESC LIMIT 8
                """
            )
            recent_payments = cursor.fetchall()
            cursor.execute(
                """
                SELECT s.id AS student_id, s.admission_number, s.class_name,
                       CONCAT(u.first_name, ' ', u.last_name) AS student_name,
                       AVG(a.marks_obtained / a.total_marks * 100) AS percentage
                FROM student_assessments AS a
                JOIN students AS s ON s.id = a.student_id
                JOIN users AS u ON u.id = s.user_id
                WHERE a.created_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 12 MONTH)
                GROUP BY s.id
                ORDER BY percentage DESC, student_name LIMIT 5
                """
            )
            top_students = cursor.fetchall()
            cursor.execute(
                """
                SELECT id, title, description, starts_at, ends_at
                FROM school_events
                WHERE starts_at >= NOW()
                ORDER BY starts_at LIMIT 6
                """
            )
            upcoming_events = cursor.fetchall()
            cursor.execute(
                """
                SELECT recent_users.id, recent_users.username,
                       recent_users.first_name, recent_users.last_name,
                       recent_users.created_at,
                       GROUP_CONCAT(r.code ORDER BY r.code SEPARATOR ', ') AS roles
                FROM (
                    SELECT id, username, first_name, last_name, created_at
                    FROM users
                    ORDER BY created_at DESC, id DESC
                    LIMIT 8
                ) AS recent_users
                LEFT JOIN user_roles AS ur ON ur.user_id = recent_users.id
                LEFT JOIN roles AS r ON r.id = ur.role_id
                GROUP BY recent_users.id, recent_users.username,
                         recent_users.first_name, recent_users.last_name,
                         recent_users.created_at
                ORDER BY recent_users.created_at DESC, recent_users.id DESC
                """
            )
            recent_users = cursor.fetchall()
        except MySQLError as exc:
            logger.exception("Admin dashboard database failure")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load the admin dashboard.",
            ) from exc
        finally:
            cursor.close()

        total_fees = _decimal(metrics["total_fees"])
        fees_collected = _decimal(metrics["fees_collected"])
        return {
            "metrics": {
                **metrics,
                "total_fees": f"{total_fees:.2f}",
                "fees_collected": f"{fees_collected:.2f}",
                "pending_fees": f"{max(total_fees - fees_collected, Decimal('0')):.2f}",
                "salary_expenses": f"{_decimal(metrics['salary_expenses']):.2f}",
                "staff_attendance_today": {
                    "present": metrics["staff_present_today"],
                    "absent": metrics["staff_absent_today"],
                    "late": metrics["staff_late_today"],
                    "half_day": metrics["staff_half_day_today"],
                    "leave": metrics["staff_leave_today"],
                },
            },
            "charts": {
                "student_enrollment": enrollment,
                "fee_collection": [
                    {**row, "amount": f"{_decimal(row['amount']):.2f}"}
                    for row in fee_statistics
                ],
                "staff_attendance": staff_attendance,
                "salary_expenses": [
                    {**row, "amount": f"{_decimal(row['amount']):.2f}"}
                    for row in salary_statistics
                ],
                "course_performance": [
                    {
                        **row,
                        "average_percentage": round(float(row["average_percentage"]), 1),
                    }
                    for row in course_performance
                ],
                "class_performance": [
                    {
                        **row,
                        "average_percentage": round(float(row["average_percentage"]), 1),
                    }
                    for row in class_performance
                ],
                "performance_trends": [
                    {
                        **row,
                        "average_percentage": round(float(row["average_percentage"]), 1),
                    }
                    for row in performance_trends
                ],
                "top_students": [
                    {**row, "percentage": round(float(row["percentage"]), 1)}
                    for row in top_students
                ],
            },
            "recent_payments": [
                {
                    **row,
                    "amount": f"{_decimal(row['amount']):.2f}",
                    "student_name": f"{row['first_name']} {row['last_name']}".strip(),
                }
                for row in recent_payments
            ],
            "recent_activities": recent_users,
            "upcoming_events": upcoming_events,
        }

    @router.get("/users")
    def list_users(
        search: Optional[str] = Query(default=None, max_length=120),
        role: Optional[str] = None,
        active: Optional[bool] = None,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        clauses: list[str] = []
        parameters: list[Any] = []
        search_term = search.strip() if search else ""
        if search_term:
            pattern = f"%{search_term}%"
            clauses.append("(u.username LIKE %s OR u.email LIKE %s OR u.first_name LIKE %s OR u.last_name LIKE %s OR CONCAT(u.first_name, ' ', u.last_name) LIKE %s)")
            parameters.extend([pattern] * 5)
        if role:
            clauses.append("EXISTS (SELECT 1 FROM user_roles AS fur JOIN roles AS fr ON fr.id = fur.role_id WHERE fur.user_id = u.id AND fr.code = %s)")
            parameters.append(role)
        if active is not None:
            clauses.append("u.is_active = %s")
            parameters.append(active)
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        offset = (page - 1) * page_size
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SELECT COUNT(*) AS total FROM users AS u" + where_sql, tuple(parameters))
            total = int(cursor.fetchone()["total"])
            query = """
                SELECT u.id, u.username, u.email, u.first_name, u.last_name, u.phone,
                       u.is_active, u.created_at, u.profile_photo_path,
                       role_list.roles,
                       s.id AS student_id, s.admission_number, s.class_name,
                       st.id AS staff_id, st.employee_number, st.staff_type, st.designation
                FROM users AS u
                LEFT JOIN (
                    SELECT ur.user_id, GROUP_CONCAT(DISTINCT r.code ORDER BY r.code SEPARATOR ',') AS roles
                    FROM user_roles AS ur JOIN roles AS r ON r.id = ur.role_id
                    GROUP BY ur.user_id
                ) AS role_list ON role_list.user_id = u.id
                LEFT JOIN students AS s ON s.user_id = u.id
                LEFT JOIN staff AS st ON st.user_id = u.id
            """ + where_sql + " ORDER BY u.created_at DESC, u.id DESC LIMIT %s OFFSET %s"
            cursor.execute(query, tuple(parameters + [page_size, offset]))
            rows = cursor.fetchall()
        except MySQLError as exc:
            logger.exception("Admin users endpoint database failure")
            raise HTTPException(status_code=503, detail="Unable to load system users.") from exc
        finally:
            cursor.close()
        data = [{**row, "name": f"{row['first_name']} {row['last_name']}".strip(), "roles": (row["roles"] or "").split(",") if row["roles"] else []} for row in rows]
        return {"data": data, "pagination": {"page": page, "page_size": page_size, "total_records": total, "total_pages": (total + page_size - 1) // page_size, "has_next": offset + page_size < total, "has_previous": page > 1}}

    @router.patch("/users/{user_id}")
    def update_user(
        user_id: int,
        request: AdminUserUpdate,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        values = request.model_dump(exclude_unset=True)
        if not values:
            raise HTTPException(status_code=422, detail="Provide at least one field to update.")
        if "email" in values and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", values["email"]):
            raise HTTPException(status_code=422, detail="Enter a valid email address.")
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            if cursor.fetchone() is None:
                raise _not_found("User not found.")
            updates = ", ".join(f"{field} = %s" for field in values)
            cursor.execute(
                f"UPDATE users SET {updates} WHERE id = %s",
                (*values.values(), user_id),
            )
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            if exc.errno == 1062:
                raise HTTPException(status_code=409, detail="That email is already in use.") from exc
            raise HTTPException(status_code=503, detail="Unable to update user details.") from exc
        finally:
            cursor.close()
        return {"id": user_id, **values}

    @router.post("/users/{user_id}/reset-password")
    def reset_user_password(
        user_id: int,
        request: AdminPasswordReset,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, str]:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (hash_password(request.password), user_id),
            )
            if cursor.rowcount == 0:
                raise _not_found("User not found.")
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            raise HTTPException(status_code=503, detail="Unable to reset the user password.") from exc
        finally:
            cursor.close()
        return {"message": "Password reset successfully."}

    @router.patch("/users/{user_id}/role")
    def update_user_role(
        user_id: int,
        request: AdminRoleUpdate,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT r.id AS role_id,
                    EXISTS(SELECT 1 FROM students WHERE user_id = %s) AS is_student,
                    EXISTS(SELECT 1 FROM staff WHERE user_id = %s AND staff_type = 'teacher') AS is_teacher,
                    EXISTS(SELECT 1 FROM staff WHERE user_id = %s AND staff_type = 'non_teaching') AS is_non_teaching,
                    EXISTS(
                        SELECT 1 FROM user_roles ur
                        JOIN roles existing_role ON existing_role.id = ur.role_id
                        WHERE ur.user_id = %s AND existing_role.code = 'admin'
                    ) AS is_admin
                FROM roles AS r WHERE r.code = %s
                """,
                (user_id, user_id, user_id, user_id, request.role),
            )
            eligible = cursor.fetchone()
            if eligible is None:
                raise _not_found("Requested role not found.")
            profile_exists = {
                "student": eligible["is_student"],
                "teacher": eligible["is_teacher"],
                "non_teaching_staff": eligible["is_non_teaching"],
            }[request.role]
            cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            if cursor.fetchone() is None:
                raise _not_found("User not found.")
            if eligible["is_admin"]:
                raise HTTPException(status_code=409, detail="Administrator roles cannot be reassigned.")
            if not profile_exists:
                raise HTTPException(
                    status_code=409,
                    detail="A matching student or staff profile is required before assigning this role.",
                )
            cursor.execute("DELETE FROM user_roles WHERE user_id = %s", (user_id,))
            cursor.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s)",
                (user_id, eligible["role_id"]),
            )
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            raise HTTPException(status_code=503, detail="Unable to assign the user role.") from exc
        finally:
            cursor.close()
        return {"user_id": user_id, "role": request.role}

    @router.delete("/users/{user_id}")
    def delete_user(
        user_id: int,
        claims: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, str]:
        if str(claims.get("sub")) == str(user_id):
            raise HTTPException(status_code=409, detail="You cannot delete the signed-in admin account.")
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT EXISTS(
                    SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
                    WHERE ur.user_id = %s AND r.code = 'admin'
                ) AS is_admin
                """,
                (user_id,),
            )
            user = cursor.fetchone()
            cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            exists = cursor.fetchone()
            if exists is None:
                raise _not_found("User not found.")
            if user and user["is_admin"]:
                raise HTTPException(status_code=409, detail="Administrator accounts cannot be deleted.")
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            if exc.errno == 1451:
                raise HTTPException(
                    status_code=409,
                    detail="This user has school records and cannot be deleted. Deactivate the account instead.",
                ) from exc
            raise HTTPException(status_code=503, detail="Unable to delete user.") from exc
        finally:
            cursor.close()
        return {"message": "User deleted."}

    @router.post("/users/{user_id}/photo")
    def upload_profile_photo(
        user_id: int,
        file: UploadFile = File(...),
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        extension = Path(file.filename or "").suffix.lower()
        if extension not in ALLOWED_PROFILE_PHOTO_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail="Upload a JPG, PNG, or WEBP profile photo.",
            )
        stored_filename = f"{uuid4().hex}{extension}"
        stored_path = PROFILE_PHOTO_DIR / stored_filename
        file_saved = False
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SELECT profile_photo_path FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            if user is None:
                raise _not_found("User not found.")
            PROFILE_PHOTO_DIR.mkdir(parents=True, exist_ok=True)
            file_size = 0
            with stored_path.open("xb") as output:
                while True:
                    chunk = file.file.read(64 * 1024)
                    if not chunk:
                        break
                    file_size += len(chunk)
                    if file_size > MAX_PROFILE_PHOTO_SIZE:
                        raise HTTPException(status_code=413, detail="Profile photos must be 5 MB or smaller.")
                    output.write(chunk)
            if file_size == 0:
                raise HTTPException(status_code=422, detail="The uploaded profile photo is empty.")
            cursor.execute(
                "UPDATE users SET profile_photo_path = %s WHERE id = %s",
                (stored_filename, user_id),
            )
            connection.commit()
            file_saved = True
        except HTTPException:
            connection.rollback()
            raise
        except OSError as exc:
            connection.rollback()
            raise HTTPException(status_code=503, detail="Unable to store the profile photo.") from exc
        except MySQLError as exc:
            connection.rollback()
            raise HTTPException(status_code=503, detail="Unable to save the profile photo.") from exc
        finally:
            cursor.close()
            if not file_saved:
                stored_path.unlink(missing_ok=True)

        old_filename = Path(user["profile_photo_path"]).name if user["profile_photo_path"] else None
        if old_filename and old_filename != stored_filename:
            try:
                (PROFILE_PHOTO_DIR / old_filename).unlink(missing_ok=True)
            except OSError as exc:
                raise HTTPException(
                    status_code=503,
                    detail="Profile photo was updated, but the previous file could not be removed.",
                ) from exc
        return {"user_id": user_id, "profile_photo_path": stored_filename}

    @router.get("/users/{user_id}/photo")
    def get_profile_photo(
        user_id: int,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> FileResponse:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SELECT profile_photo_path FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
        except MySQLError as exc:
            raise HTTPException(status_code=503, detail="Unable to load the profile photo.") from exc
        finally:
            cursor.close()
        if user is None or not user["profile_photo_path"]:
            raise _not_found("Profile photo not found.")
        stored_filename = Path(user["profile_photo_path"]).name
        stored_path = PROFILE_PHOTO_DIR / stored_filename
        if not stored_path.is_file():
            raise _not_found("Profile photo file is unavailable.")
        return FileResponse(stored_path)

    @router.patch("/students/{student_id}")
    def update_student(
        student_id: int,
        request: AdminStudentUpdate,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        values = request.model_dump(exclude_unset=True)
        if not values:
            raise HTTPException(status_code=422, detail="Provide at least one field to update.")
        user_values = {
            key: values.pop(key)
            for key in ("first_name", "last_name", "email", "phone")
            if key in values
        }
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SELECT user_id FROM students WHERE id = %s FOR UPDATE", (student_id,))
            student = cursor.fetchone()
            if student is None:
                raise _not_found("Student not found.")
            if user_values:
                cursor.execute(
                    "UPDATE users SET " + ", ".join(f"{key} = %s" for key in user_values) + " WHERE id = %s",
                    (*user_values.values(), student["user_id"]),
                )
            if values:
                cursor.execute(
                    "UPDATE students SET " + ", ".join(f"{key} = %s" for key in values) + " WHERE id = %s",
                    (*values.values(), student_id),
                )
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            if exc.errno == 1062:
                raise HTTPException(status_code=409, detail="That email is already in use.") from exc
            raise HTTPException(status_code=503, detail="Unable to update student details.") from exc
        finally:
            cursor.close()
        return {"id": student_id, **user_values, **values}

    @router.get("/students/{student_id}/profile")
    def get_student_profile(
        student_id: int,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT s.*, u.username, u.email, u.phone, u.first_name, u.last_name, u.is_active
                FROM students AS s JOIN users AS u ON u.id = s.user_id
                WHERE s.id = %s
                """,
                (student_id,),
            )
            student = cursor.fetchone()
            if student is None:
                raise _not_found("Student not found.")
            cursor.execute(
                """
                SELECT c.id, c.course_code, c.name, sc.academic_year_id, ay.name AS academic_year,
                       sc.status AS enrollment_status
                FROM student_courses AS sc
                JOIN courses AS c ON c.id = sc.course_id
                JOIN academic_years AS ay ON ay.id = sc.academic_year_id
                WHERE sc.student_id = %s ORDER BY ay.start_date DESC, c.course_code
                """,
                (student_id,),
            )
            courses = cursor.fetchall()
            cursor.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(r.status = 'present') AS present,
                       SUM(r.status = 'absent') AS absent,
                       SUM(r.status = 'late') AS late
                FROM attendance_records AS r WHERE r.student_id = %s
                """,
                (student_id,),
            )
            attendance = cursor.fetchone()
            cursor.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS invoice_total,
                       COALESCE(SUM(amount - paid_amount), 0) AS invoice_balance
                FROM (
                    SELECT i.amount, COALESCE(SUM(p.amount), 0) AS paid_amount
                    FROM fee_invoices AS i
                    LEFT JOIN fee_payments AS p ON p.invoice_id = i.id
                    WHERE i.student_id = %s AND i.status != 'waived'
                    GROUP BY i.id
                ) AS invoice_summary
                """,
                (student_id,),
            )
            invoice_fees = cursor.fetchone()
            cursor.execute(
                "SELECT COALESCE(SUM(amount), 0) AS amount FROM student_fee_payments WHERE student_id = %s",
                (student_id,),
            )
            legacy_paid = _decimal(cursor.fetchone()["amount"])
            cursor.execute(
                """
                SELECT a.exam_name, c.course_code, a.marks_obtained, a.total_marks,
                       ROUND(a.marks_obtained / a.total_marks * 100, 1) AS percentage
                FROM student_assessments AS a JOIN courses AS c ON c.id = a.course_id
                WHERE a.student_id = %s ORDER BY a.created_at DESC LIMIT 20
                """,
                (student_id,),
            )
            performance = cursor.fetchall()
        except HTTPException:
            raise
        except MySQLError as exc:
            raise HTTPException(status_code=503, detail="Unable to load the student profile.") from exc
        finally:
            cursor.close()
        balance = _decimal(invoice_fees["invoice_balance"]) + max(
            _decimal(student["fee_amount"]) - legacy_paid,
            Decimal("0"),
        )
        return {
            "student": {
                **student,
                "name": f"{student['first_name']} {student['last_name']}".strip(),
                "fee_amount": f"{_decimal(student['fee_amount']):.2f}",
            },
            "courses": courses,
            "attendance": attendance,
            "fee_status": {
                "invoice_total": f"{_decimal(invoice_fees['invoice_total']):.2f}",
                "legacy_paid": f"{legacy_paid:.2f}",
                "pending_balance": f"{balance:.2f}",
            },
            "performance": performance,
        }

    @router.patch("/staff/{staff_id}")
    def update_staff(
        staff_id: int,
        request: AdminStaffUpdate,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        values = request.model_dump(exclude_unset=True)
        if not values:
            raise HTTPException(status_code=422, detail="Provide at least one field to update.")
        user_values = {
            key: values.pop(key)
            for key in ("first_name", "last_name", "email", "phone")
            if key in values
        }
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SELECT user_id FROM staff WHERE id = %s FOR UPDATE", (staff_id,))
            staff = cursor.fetchone()
            if staff is None:
                raise _not_found("Staff profile not found.")
            if user_values:
                cursor.execute(
                    "UPDATE users SET " + ", ".join(f"{key} = %s" for key in user_values) + " WHERE id = %s",
                    (*user_values.values(), staff["user_id"]),
                )
            if values:
                cursor.execute(
                    "UPDATE staff SET " + ", ".join(f"{key} = %s" for key in values) + " WHERE id = %s",
                    (*values.values(), staff_id),
                )
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            if exc.errno == 1062:
                raise HTTPException(status_code=409, detail="That email is already in use.") from exc
            raise HTTPException(status_code=503, detail="Unable to update staff details.") from exc
        finally:
            cursor.close()
        return {"id": staff_id, **user_values, **values}

    @router.put("/courses/{course_id}")
    def update_course(
        course_id: int,
        request: AdminCourseUpdate,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        values = request.model_dump(exclude_unset=True)
        if not values:
            raise HTTPException(status_code=422, detail="Provide at least one field to update.")
        if "course_code" in values:
            values["course_code"] = values["course_code"].strip().upper()
            if not re.fullmatch(r"[A-Z0-9._-]{2,40}", values["course_code"]):
                raise HTTPException(status_code=422, detail="Invalid course code.")
        for key in ("name", "description", "class_name"):
            if key in values and isinstance(values[key], str):
                values[key] = values[key].strip() or None
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id FROM courses WHERE id = %s", (course_id,))
            if cursor.fetchone() is None:
                raise _not_found("Course not found.")
            if values.get("teacher_id") is not None:
                cursor.execute(
                    "SELECT id FROM staff WHERE id = %s AND staff_type = 'teacher'",
                    (values["teacher_id"],),
                )
                if cursor.fetchone() is None:
                    raise HTTPException(status_code=422, detail="Select an active teacher profile.")
            if values:
                cursor.execute(
                    "UPDATE courses SET " + ", ".join(f"{key} = %s" for key in values) + " WHERE id = %s",
                    (*values.values(), course_id),
                )
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            if exc.errno == 1062:
                raise HTTPException(status_code=409, detail="That course code is already in use.") from exc
            raise HTTPException(status_code=503, detail="Unable to update course details.") from exc
        finally:
            cursor.close()
        return {"id": course_id, **values}

    @router.delete("/courses/{course_id}")
    def delete_course(
        course_id: int,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, str]:
        cursor = connection.cursor()
        try:
            cursor.execute("DELETE FROM courses WHERE id = %s", (course_id,))
            if cursor.rowcount == 0:
                raise _not_found("Course not found.")
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            if exc.errno == 1451:
                raise HTTPException(
                    status_code=409,
                    detail="This course has enrollment or attendance history and cannot be deleted.",
                ) from exc
            raise HTTPException(status_code=503, detail="Unable to delete course.") from exc
        finally:
            cursor.close()
        return {"message": "Course deleted."}

    @router.post("/courses/{course_id}/enrollments", status_code=201)
    def enroll_student(
        course_id: int,
        student_id: int = Query(gt=0),
        academic_year_id: int = Query(gt=0),
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO student_courses (student_id, course_id, academic_year_id, enrolled_at)
                VALUES (%s, %s, %s, %s)
                """,
                (student_id, course_id, academic_year_id, date.today()),
            )
            connection.commit()
        except MySQLError as exc:
            connection.rollback()
            if exc.errno == 1062:
                raise HTTPException(status_code=409, detail="Student is already enrolled in this course.") from exc
            if exc.errno == 1452:
                raise HTTPException(status_code=404, detail="Student, course, or academic year not found.") from exc
            raise HTTPException(status_code=503, detail="Unable to enroll the student.") from exc
        finally:
            cursor.close()
        return {
            "student_id": student_id,
            "course_id": course_id,
            "academic_year_id": academic_year_id,
        }

    @router.get("/courses/{course_id}/enrollments")
    def list_course_enrollments(
        course_id: int,
        academic_year_id: Optional[int] = None,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> list[dict[str, Any]]:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id FROM courses WHERE id = %s", (course_id,))
            if cursor.fetchone() is None:
                raise _not_found("Course not found.")
            query = """
                SELECT s.id AS student_id, s.admission_number, s.class_name,
                       sc.academic_year_id, sc.status AS enrollment_status,
                       CONCAT(u.first_name, ' ', u.last_name) AS student_name
                FROM student_courses AS sc
                JOIN students AS s ON s.id = sc.student_id
                JOIN users AS u ON u.id = s.user_id
                WHERE sc.course_id = %s
            """
            parameters: tuple[Any, ...] = (course_id,)
            if academic_year_id is not None:
                query += " AND sc.academic_year_id = %s"
                parameters += (academic_year_id,)
            query += " ORDER BY s.class_name, u.last_name, u.first_name"
            cursor.execute(query, parameters)
            return cursor.fetchall()
        except HTTPException:
            raise
        except MySQLError as exc:
            raise HTTPException(status_code=503, detail="Unable to load course enrollments.") from exc
        finally:
            cursor.close()

    @router.delete("/courses/{course_id}/enrollments/{student_id}")
    def withdraw_student(
        course_id: int,
        student_id: int,
        academic_year_id: int = Query(gt=0),
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, str]:
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                UPDATE student_courses SET status = 'withdrawn'
                WHERE course_id = %s AND student_id = %s
                  AND academic_year_id = %s AND status = 'enrolled'
                """,
                (course_id, student_id, academic_year_id),
            )
            if cursor.rowcount == 0:
                raise _not_found("Active course enrollment not found.")
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            raise HTTPException(status_code=503, detail="Unable to withdraw student enrollment.") from exc
        finally:
            cursor.close()
        return {"message": "Student withdrawn from the course."}

    @router.get("/fee-students")
    def list_fee_students(
        search: Optional[str] = Query(default=None, max_length=120),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=50),
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        search_term = search.strip() if search else ""
        clauses: list[str] = []
        parameters: list[Any] = []
        if search_term:
            pattern = f"{search_term}%"
            clauses.append(
                "(u.first_name LIKE %s OR u.last_name LIKE %s "
                "OR s.admission_number LIKE %s)"
            )
            parameters.extend([pattern] * 3)
        where_clause = " WHERE " + " AND ".join(clauses) if clauses else ""
        offset = (page - 1) * page_size
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT s.id, s.admission_number, s.class_name, s.status,
                       CONCAT(u.first_name, ' ', u.last_name) AS name
                FROM students AS s
                JOIN users AS u ON u.id = s.user_id
                """ + where_clause + """
                ORDER BY u.last_name, u.first_name, s.admission_number
                LIMIT %s OFFSET %s
                """,
                tuple([*parameters, page_size + 1, offset]),
            )
            rows = cursor.fetchall()
        except MySQLError as exc:
            logger.exception("Fee student options endpoint database failure")
            raise HTTPException(status_code=503, detail="Unable to load fee student options.") from exc
        finally:
            cursor.close()
        has_next = len(rows) > page_size
        data = rows[:page_size]
        return {
            "data": data,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "has_next": has_next,
                "has_previous": page > 1,
            },
        }

    @router.get("/fee-classes")
    def list_fee_classes(
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> list[str]:
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT DISTINCT class_name
                FROM students
                WHERE class_name IS NOT NULL AND TRIM(class_name) <> ''
                ORDER BY class_name
                """
            )
            return [row[0] for row in cursor.fetchall()]
        except MySQLError as exc:
            logger.exception("Fee class options endpoint database failure")
            raise HTTPException(status_code=503, detail="Unable to load fee class options.") from exc
        finally:
            cursor.close()

    @router.get("/fee-types")
    def list_fee_types(
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> list[dict[str, Any]]:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT ft.id, ft.name, ft.description, ft.amount, ft.class_name,
                       ft.academic_year_id, ay.name AS academic_year
                FROM fee_types AS ft
                LEFT JOIN academic_years AS ay ON ay.id = ft.academic_year_id
                ORDER BY ft.name
                """
            )
            return cursor.fetchall()
        except MySQLError as exc:
            raise HTTPException(status_code=503, detail="Unable to load fee structures.") from exc
        finally:
            cursor.close()

    @router.post("/fee-types", status_code=201)
    def create_fee_type(
        request: FeeTypeCreate,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        name = request.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Fee structure name is required.")
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO fee_types (name, description, amount, class_name, academic_year_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    name,
                    request.description.strip() if request.description else None,
                    request.amount,
                    request.class_name.strip() if request.class_name else None,
                    request.academic_year_id,
                ),
            )
            fee_type_id = cursor.lastrowid
            connection.commit()
        except MySQLError as exc:
            connection.rollback()
            if exc.errno == 1062:
                raise HTTPException(status_code=409, detail="A fee structure with that name already exists.") from exc
            if exc.errno == 1452:
                raise HTTPException(status_code=404, detail="Academic year not found.") from exc
            raise HTTPException(status_code=503, detail="Unable to create fee structure.") from exc
        finally:
            cursor.close()
        return {"id": fee_type_id, **request.model_dump(), "name": name}

    @router.get("/fee-invoices")
    def list_fee_invoices(
        student_id: Optional[int] = None,
        class_name: Optional[str] = None,
        payment_status: Optional[str] = None,
        search: Optional[str] = Query(default=None, max_length=120),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        if payment_status and payment_status not in {
            "paid",
            "partially_paid",
            "pending",
            "overdue",
            "waived",
        }:
            raise HTTPException(status_code=422, detail="Unsupported payment status filter.")
        from_clause = """
            FROM fee_invoices AS i
            JOIN students AS s ON s.id = i.student_id
            JOIN users AS u ON u.id = s.user_id
            JOIN fee_types AS ft ON ft.id = i.fee_type_id
            LEFT JOIN (
                SELECT invoice_id, SUM(amount) AS paid_amount
                FROM fee_payments
                GROUP BY invoice_id
            ) AS payment_totals ON payment_totals.invoice_id = i.id
        """
        clauses: list[str] = []
        parameters: list[Any] = []
        if student_id is not None:
            clauses.append("i.student_id = %s")
            parameters.append(student_id)
        if class_name:
            clauses.append("s.class_name = %s")
            parameters.append(class_name)
        search_term = search.strip() if search else ""
        if search_term:
            pattern = f"%{search_term}%"
            clauses.append(
                """(
                    CONCAT(u.first_name, ' ', u.last_name) LIKE %s
                    OR u.first_name LIKE %s OR u.last_name LIKE %s
                    OR s.admission_number LIKE %s
                    OR CAST(i.id AS CHAR) LIKE %s
                )"""
            )
            parameters.extend([pattern] * 5)
        if payment_status == "overdue":
            clauses.extend(
                [
                    "i.due_date < CURRENT_DATE()",
                    "i.status != 'waived'",
                    "COALESCE(payment_totals.paid_amount, 0) < i.amount",
                ]
            )
        elif payment_status == "pending":
            clauses.extend(["i.status = %s", "i.due_date >= CURRENT_DATE()"])
            parameters.append("unpaid")
        elif payment_status in {"paid", "partially_paid", "waived"}:
            clauses.append("i.status = %s")
            parameters.append(
                {
                    "paid": "paid",
                    "partially_paid": "partially_paid",
                    "waived": "waived",
                }[payment_status]
            )
        if clauses:
            where_clause = " WHERE " + " AND ".join(clauses)
        else:
            where_clause = ""
        summary_query = """
            SELECT COUNT(*) AS total,
               COALESCE(SUM(i.amount), 0) AS amount,
               COALESCE(SUM(COALESCE(payment_totals.paid_amount, 0)), 0) AS paid_amount,
               COALESCE(
                   SUM(GREATEST(i.amount - COALESCE(payment_totals.paid_amount, 0), 0)),
                   0
               ) AS pending_amount
        """ + from_clause + where_clause
        query = """
            SELECT i.id, i.student_id, s.admission_number, s.class_name,
               CONCAT(u.first_name, ' ', u.last_name) AS student_name,
               ft.name AS fee_name, i.amount, i.due_date,
               COALESCE(payment_totals.paid_amount, 0) AS paid_amount,
               GREATEST(i.amount - COALESCE(payment_totals.paid_amount, 0), 0) AS pending_amount,
               CASE
                 WHEN i.status = 'waived' THEN 'waived'
                 WHEN COALESCE(payment_totals.paid_amount, 0) >= i.amount THEN 'paid'
                 WHEN COALESCE(payment_totals.paid_amount, 0) > 0 THEN 'partially_paid'
                 WHEN i.due_date < CURRENT_DATE() THEN 'overdue'
                 ELSE 'pending'
               END AS payment_status
        """ + from_clause + where_clause + " ORDER BY i.due_date, i.id LIMIT %s OFFSET %s"
        offset = (page - 1) * page_size
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(summary_query, tuple(parameters))
            summary = cursor.fetchone() or {
                "total": 0,
                "amount": 0,
                "paid_amount": 0,
                "pending_amount": 0,
            }
            total = int(summary["total"])
            cursor.execute(query, tuple(parameters + [page_size, offset]))
            rows = cursor.fetchall()
        except MySQLError as exc:
            logger.exception("Fee invoices endpoint database failure")
            raise HTTPException(status_code=503, detail="Unable to load fee invoices.") from exc
        finally:
            cursor.close()
        data = [{
            **row,
            "amount": f"{_decimal(row['amount']):.2f}",
            "paid_amount": f"{_decimal(row['paid_amount']):.2f}",
            "pending_amount": f"{_decimal(row['pending_amount']):.2f}",
        } for row in rows]
        return {
            "data": data,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_records": total,
                "total_pages": (total + page_size - 1) // page_size,
                "has_next": offset + page_size < total,
                "has_previous": page > 1,
            },
            "summary": {
                "amount": f"{_decimal(summary['amount']):.2f}",
                "paid_amount": f"{_decimal(summary['paid_amount']):.2f}",
                "pending_amount": f"{_decimal(summary['pending_amount']):.2f}",
            },
        }

    @router.post("/fee-invoices", status_code=201)
    def create_fee_invoice(
        request: FeeInvoiceCreate,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT amount FROM fee_types WHERE id = %s",
                (request.fee_type_id,),
            )
            fee_type = cursor.fetchone()
            if fee_type is None:
                raise _not_found("Fee structure not found.")
            amount = request.amount or _decimal(fee_type["amount"])
            if amount <= 0:
                raise HTTPException(status_code=422, detail="Invoice amount must be greater than zero.")
            cursor.execute(
                """
                INSERT INTO fee_invoices
                    (student_id, fee_type_id, academic_year_id, amount, due_date)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    request.student_id,
                    request.fee_type_id,
                    request.academic_year_id,
                    amount,
                    request.due_date,
                ),
            )
            invoice_id = cursor.lastrowid
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            if exc.errno == 1452:
                raise HTTPException(status_code=404, detail="Student, fee structure, or academic year not found.") from exc
            raise HTTPException(status_code=503, detail="Unable to assign the fee.") from exc
        finally:
            cursor.close()
        return {"id": invoice_id, **request.model_dump(), "amount": f"{amount:.2f}", "status": "unpaid"}

    @router.post("/fee-invoices/class", status_code=201)
    def create_class_fee_invoices(
        request: FeeClassInvoiceCreate,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        class_name = request.class_name.strip()
        if not class_name:
            raise HTTPException(status_code=422, detail="Class name is required.")

        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT amount, class_name, academic_year_id FROM fee_types WHERE id = %s",
                (request.fee_type_id,),
            )
            fee_type = cursor.fetchone()
            if fee_type is None:
                raise _not_found("Fee structure not found.")
            if fee_type["class_name"] and fee_type["class_name"] != class_name:
                raise HTTPException(
                    status_code=409,
                    detail="The selected fee structure is assigned to a different class.",
                )
            if (
                fee_type["academic_year_id"]
                and fee_type["academic_year_id"] != request.academic_year_id
            ):
                raise HTTPException(
                    status_code=409,
                    detail="The selected fee structure is assigned to a different academic year.",
                )

            amount = request.amount if request.amount is not None else _decimal(fee_type["amount"])
            if amount <= 0:
                raise HTTPException(status_code=422, detail="Invoice amount must be greater than zero.")

            cursor.execute(
                """
                SELECT s.id
                FROM students AS s
                LEFT JOIN fee_invoices AS existing
                  ON existing.student_id = s.id
                 AND existing.fee_type_id = %s
                 AND existing.academic_year_id = %s
                WHERE s.class_name = %s
                  AND s.status = 'active'
                  AND existing.id IS NULL
                ORDER BY s.id
                """,
                (request.fee_type_id, request.academic_year_id, class_name),
            )
            students = cursor.fetchall()
            if students:
                cursor.executemany(
                    """
                    INSERT INTO fee_invoices
                        (student_id, fee_type_id, academic_year_id, amount, due_date)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            student["id"],
                            request.fee_type_id,
                            request.academic_year_id,
                            amount,
                            request.due_date,
                        )
                        for student in students
                    ],
                )
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            if exc.errno == 1452:
                raise HTTPException(
                    status_code=404,
                    detail="Fee structure or academic year not found.",
                ) from exc
            raise HTTPException(status_code=503, detail="Unable to assign fees to the class.") from exc
        finally:
            cursor.close()

        return {
            "class_name": class_name,
            "fee_type_id": request.fee_type_id,
            "academic_year_id": request.academic_year_id,
            "amount": f"{amount:.2f}",
            "created_count": len(students),
        }

    @router.post("/fee-invoices/{invoice_id}/payments", status_code=201)
    def record_invoice_payment(
        invoice_id: int,
        request: InvoicePaymentRequest,
        admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        reference = request.transaction_reference.strip() if request.transaction_reference else None
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT amount, status FROM fee_invoices WHERE id = %s FOR UPDATE",
                (invoice_id,),
            )
            invoice = cursor.fetchone()
            if invoice is None:
                raise _not_found("Fee invoice not found.")
            cursor.execute(
                "SELECT COALESCE(SUM(amount), 0) AS paid_amount FROM fee_payments WHERE invoice_id = %s",
                (invoice_id,),
            )
            paid_amount = cursor.fetchone()["paid_amount"]
            balance = _decimal(invoice["amount"]) - _decimal(paid_amount)
            if request.amount > balance or invoice["status"] == "waived":
                raise HTTPException(status_code=409, detail="Payment exceeds the invoice balance.")
            cursor.execute(
                """
                INSERT INTO fee_payments
                    (invoice_id, amount, payment_method, transaction_reference, received_by, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    invoice_id,
                    request.amount,
                    request.payment_method,
                    reference,
                    _admin_user_id(admin),
                    request.notes.strip() if request.notes else None,
                ),
            )
            payment_id = cursor.lastrowid
            new_balance = balance - request.amount
            new_status = "paid" if new_balance == 0 else "partially_paid"
            cursor.execute("UPDATE fee_invoices SET status = %s WHERE id = %s", (new_status, invoice_id))
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            if exc.errno == 1062:
                raise HTTPException(status_code=409, detail="That transaction reference is already used.") from exc
            raise HTTPException(status_code=503, detail="Unable to record invoice payment.") from exc
        finally:
            cursor.close()
        return {
            "id": payment_id,
            "invoice_id": invoice_id,
            "amount": f"{request.amount:.2f}",
            "remaining_balance": f"{new_balance:.2f}",
            "status": new_status,
        }

    @router.post("/fee-invoices/student-payment", status_code=201)
    def record_student_invoice_payment(
        request: StudentInvoicePaymentRequest,
        admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        invoice_created = False
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT id, class_name FROM students WHERE id = %s FOR UPDATE",
                (request.student_id,),
            )
            student = cursor.fetchone()
            if student is None:
                raise _not_found("Student not found.")
            cursor.execute(
                """
                SELECT amount, class_name, academic_year_id
                FROM fee_types
                WHERE id = %s
                FOR UPDATE
                """,
                (request.fee_type_id,),
            )
            fee_type = cursor.fetchone()
            if fee_type is None:
                raise _not_found("Fee structure not found.")
            if fee_type["class_name"] and fee_type["class_name"] != student["class_name"]:
                raise HTTPException(
                    status_code=409,
                    detail="The selected fee structure is assigned to a different class.",
                )
            if (
                fee_type["academic_year_id"]
                and fee_type["academic_year_id"] != request.academic_year_id
            ):
                raise HTTPException(
                    status_code=409,
                    detail="The selected fee structure is assigned to a different academic year.",
                )
            cursor.execute(
                """
                SELECT id
                FROM fee_invoices
                WHERE student_id = %s
                  AND fee_type_id = %s
                  AND academic_year_id = %s
                ORDER BY id
                LIMIT 2
                FOR UPDATE
                """,
                (request.student_id, request.fee_type_id, request.academic_year_id),
            )
            matching_invoices = cursor.fetchall()
            if len(matching_invoices) > 1:
                raise HTTPException(
                    status_code=409,
                    detail="Multiple matching invoices exist. Record payment from the fee ledger.",
                )
            if matching_invoices:
                invoice_id = matching_invoices[0]["id"]
            else:
                invoice_amount = _decimal(fee_type["amount"])
                if invoice_amount <= 0:
                    raise HTTPException(
                        status_code=422,
                        detail="The fee structure amount must be greater than zero.",
                    )
                cursor.execute(
                    """
                    INSERT INTO fee_invoices
                        (student_id, fee_type_id, academic_year_id, amount, due_date)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        request.student_id,
                        request.fee_type_id,
                        request.academic_year_id,
                        invoice_amount,
                        request.invoice_due_date or date.today(),
                    ),
                )
                invoice_id = cursor.lastrowid
                invoice_created = True
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            logger.exception("Student fee payment lookup database failure")
            raise HTTPException(status_code=503, detail="Unable to prepare the student fee invoice.") from exc
        finally:
            cursor.close()

        payment = record_invoice_payment(
            invoice_id,
            InvoicePaymentRequest(
                amount=request.amount,
                payment_method=request.payment_method,
                transaction_reference=request.transaction_reference,
                notes=request.notes,
            ),
            admin,
            connection,
        )
        return {**payment, "invoice_created": invoice_created}

    @router.get("/fee-invoices/{invoice_id}/payments")
    def list_invoice_payments(
        invoice_id: int,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> list[dict[str, Any]]:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id FROM fee_invoices WHERE id = %s", (invoice_id,))
            if cursor.fetchone() is None:
                raise _not_found("Fee invoice not found.")
            cursor.execute(
                """
                SELECT p.id, p.amount, p.paid_at, p.payment_method,
                       p.transaction_reference, p.notes,
                       COALESCE(u.username, 'admin') AS received_by_username
                FROM fee_payments AS p
                LEFT JOIN users AS u ON u.id = p.received_by
                WHERE p.invoice_id = %s
                ORDER BY p.paid_at DESC, p.id DESC
                """,
                (invoice_id,),
            )
            payments = cursor.fetchall()
        except HTTPException:
            raise
        except MySQLError as exc:
            raise HTTPException(status_code=503, detail="Unable to load invoice payment history.") from exc
        finally:
            cursor.close()
        return [
            {**payment, "amount": f"{_decimal(payment['amount']):.2f}"}
            for payment in payments
        ]

    @router.get("/fee-payments/{payment_id}/receipt")
    def get_fee_receipt(
        payment_id: int,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT p.id, p.amount, p.paid_at, p.payment_method, p.transaction_reference,
                       i.id AS invoice_id, ft.name AS fee_name, s.admission_number,
                       s.class_name, CONCAT(u.first_name, ' ', u.last_name) AS student_name,
                       i.amount AS invoice_amount,
                       COALESCE(payment_totals.paid_amount, 0) AS paid_amount,
                       GREATEST(i.amount - COALESCE(payment_totals.paid_amount, 0), 0) AS balance
                FROM fee_payments AS p
                JOIN fee_invoices AS i ON i.id = p.invoice_id
                JOIN fee_types AS ft ON ft.id = i.fee_type_id
                JOIN students AS s ON s.id = i.student_id
                JOIN users AS u ON u.id = s.user_id
                LEFT JOIN (
                    SELECT invoice_id, SUM(amount) AS paid_amount
                    FROM fee_payments
                    GROUP BY invoice_id
                ) AS payment_totals ON payment_totals.invoice_id = i.id
                WHERE p.id = %s
                """,
                (payment_id,),
            )
            receipt = cursor.fetchone()
        except MySQLError as exc:
            raise HTTPException(status_code=503, detail="Unable to load fee receipt.") from exc
        finally:
            cursor.close()
        if receipt is None:
            raise _not_found("Fee receipt not found.")
        return {
            **receipt,
            "amount": f"{_decimal(receipt['amount']):.2f}",
            "invoice_amount": f"{_decimal(receipt['invoice_amount']):.2f}",
            "paid_amount": f"{_decimal(receipt['paid_amount']):.2f}",
            "balance": f"{_decimal(receipt['balance']):.2f}",
        }

    @router.get("/payroll")
    def list_payroll(
        month: str,
        staff_type: Optional[Literal["teacher", "non_teaching"]] = None,
        search: Optional[str] = Query(default=None, max_length=120),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise HTTPException(status_code=422, detail="Month must use YYYY-MM format.")
        period = date.fromisoformat(f"{month}-01")
        clauses = ["sp.pay_period = %s"]
        parameters: list[Any] = [period]
        if staff_type:
            clauses.append("s.staff_type = %s")
            parameters.append(staff_type)
        search_term = search.strip() if search else ""
        if search_term:
            pattern = f"%{search_term}%"
            clauses.append("(CONCAT(u.first_name, ' ', u.last_name) LIKE %s OR u.first_name LIKE %s OR u.last_name LIKE %s OR s.employee_number LIKE %s OR s.designation LIKE %s OR s.department LIKE %s)")
            parameters.extend([pattern] * 6)
        where_sql = " WHERE " + " AND ".join(clauses)
        offset = (page - 1) * page_size
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT COUNT(*) AS total,
                       COALESCE(SUM(sp.net_amount), 0) AS net_amount,
                       SUM(CASE WHEN sp.status = 'paid' THEN 1 ELSE 0 END) AS paid_count,
                       SUM(CASE WHEN sp.status = 'pending' THEN 1 ELSE 0 END) AS pending_count
                FROM salary_payments AS sp
                JOIN staff AS s ON s.id = sp.staff_id
                JOIN users AS u ON u.id = s.user_id
            """ + where_sql, tuple(parameters))
            summary_row = cursor.fetchone() or {}
            total = int(summary_row.get("total") or 0)
            cursor.execute("""
                SELECT sp.id, sp.staff_id, sp.pay_period, sp.gross_amount, sp.allowances,
                       sp.deductions, sp.net_amount, sp.status, sp.paid_at,
                       s.employee_number, s.staff_type, s.base_salary,
                       CONCAT(u.first_name, ' ', u.last_name) AS employee_name
                FROM salary_payments AS sp
                JOIN staff AS s ON s.id = sp.staff_id
                JOIN users AS u ON u.id = s.user_id
            """ + where_sql + " ORDER BY s.staff_type, u.last_name, u.first_name, sp.id LIMIT %s OFFSET %s", tuple(parameters + [page_size, offset]))
            rows = cursor.fetchall()
        except MySQLError as exc:
            logger.exception("Payroll endpoint database failure")
            raise HTTPException(status_code=503, detail="Unable to load payroll records.") from exc
        finally:
            cursor.close()
        data = [{**row, "gross_amount": f"{_decimal(row['gross_amount']):.2f}", "allowances": f"{_decimal(row['allowances']):.2f}", "deductions": f"{_decimal(row['deductions']):.2f}", "net_amount": f"{_decimal(row['net_amount']):.2f}", "base_salary": f"{_decimal(row['base_salary']):.2f}"} for row in rows]
        return {
            "data": data,
            "summary": {"net_amount": f"{_decimal(summary_row.get('net_amount')):.2f}", "paid_count": int(summary_row.get("paid_count") or 0), "pending_count": int(summary_row.get("pending_count") or 0)},
            "pagination": {"page": page, "page_size": page_size, "total_records": total, "total_pages": (total + page_size - 1) // page_size, "has_next": offset + page_size < total, "has_previous": page > 1},
        }

    @router.post("/payroll/generate")
    def generate_payroll(
        month: str,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise HTTPException(status_code=422, detail="Month must use YYYY-MM format.")
        period = date.fromisoformat(f"{month}-01")
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT IGNORE INTO salary_payments
                    (staff_id, pay_period, gross_amount, allowances, deductions, net_amount, status)
                SELECT id, %s, base_salary, 0, 0, base_salary, 'pending'
                FROM staff WHERE status IN ('active', 'on_leave')
                """,
                (period,),
            )
            created = cursor.rowcount
            connection.commit()
        except MySQLError as exc:
            connection.rollback()
            raise HTTPException(status_code=503, detail="Unable to generate payroll.") from exc
        finally:
            cursor.close()
        return {"month": month, "records_created": created}

    @router.patch("/payroll/{payment_id}")
    def update_payroll(
        payment_id: int,
        request: PayrollUpdate,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT gross_amount, status FROM salary_payments WHERE id = %s FOR UPDATE",
                (payment_id,),
            )
            payment = cursor.fetchone()
            if payment is None:
                raise _not_found("Payroll record not found.")
            if payment["status"] == "paid":
                raise HTTPException(status_code=409, detail="Paid payroll records cannot be changed.")
            net = _decimal(payment["gross_amount"]) + request.allowances - request.deductions
            if net < 0:
                raise HTTPException(status_code=422, detail="Deductions cannot exceed gross pay plus allowances.")
            cursor.execute(
                """
                UPDATE salary_payments
                SET allowances = %s, deductions = %s, net_amount = %s
                WHERE id = %s
                """,
                (request.allowances, request.deductions, net, payment_id),
            )
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            raise HTTPException(status_code=503, detail="Unable to update payroll record.") from exc
        finally:
            cursor.close()
        return {
            "id": payment_id,
            "allowances": f"{request.allowances:.2f}",
            "deductions": f"{request.deductions:.2f}",
            "net_amount": f"{net:.2f}",
        }

    @router.post("/payroll/{payment_id}/pay")
    def mark_payroll_paid(
        payment_id: int,
        admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, str]:
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                UPDATE salary_payments
                SET status = 'paid', paid_at = NOW(), processed_by = %s
                WHERE id = %s AND status = 'pending'
                """,
                (_admin_user_id(admin), payment_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=409, detail="Payroll record is missing or already paid.")
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            raise HTTPException(status_code=503, detail="Unable to record salary payment.") from exc
        finally:
            cursor.close()
        return {"message": "Salary payment recorded."}

    @router.get("/performance")
    def list_performance(
        class_name: Optional[str] = None,
        course_id: Optional[int] = None,
        student_id: Optional[int] = None,
        search: Optional[str] = Query(default=None, max_length=120),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        query = """
            SELECT a.id, a.student_id, s.admission_number, s.class_name,
                   CONCAT(u.first_name, ' ', u.last_name) AS student_name,
                   a.course_id, c.course_code, c.name AS course_name,
                   a.exam_name, a.marks_obtained, a.total_marks,
                   ROUND(a.marks_obtained / a.total_marks * 100, 1) AS percentage
            FROM student_assessments AS a
            JOIN students AS s ON s.id = a.student_id
            JOIN users AS u ON u.id = s.user_id
            JOIN courses AS c ON c.id = a.course_id
        """
        filters: list[str] = []
        parameters: list[Any] = []
        for field, value in (("s.class_name", class_name), ("a.course_id", course_id), ("a.student_id", student_id)):
            if value is not None:
                filters.append(f"{field} = %s")
                parameters.append(value)
        search_term = search.strip() if search else ""
        if search_term:
            pattern = f"%{search_term}%"
            filters.append(
                """(
                    CONCAT(u.first_name, ' ', u.last_name) LIKE %s
                    OR u.first_name LIKE %s OR u.last_name LIKE %s
                    OR s.admission_number LIKE %s OR s.class_name LIKE %s
                    OR c.course_code LIKE %s OR c.name LIKE %s OR a.exam_name LIKE %s
                )"""
            )
            parameters.extend([pattern] * 8)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY a.created_at DESC, student_name"
        offset = (page - 1) * page_size
        query += " LIMIT %s OFFSET %s"
        count_query = """
            SELECT COUNT(*) AS total
            FROM student_assessments AS a
            JOIN students AS s ON s.id = a.student_id
            JOIN users AS u ON u.id = s.user_id
            JOIN courses AS c ON c.id = a.course_id
        """
        if filters:
            count_query += " WHERE " + " AND ".join(filters)
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(count_query, tuple(parameters))
            total = int((cursor.fetchone() or {"total": 0})["total"])
            cursor.execute(query, tuple([*parameters, page_size, offset]))
            rows = cursor.fetchall()
        except MySQLError as exc:
            logger.exception("Performance endpoint database failure")
            raise HTTPException(status_code=503, detail="Unable to load student performance.") from exc
        finally:
            cursor.close()
        data = [{
            **row,
            "marks_obtained": f"{_decimal(row['marks_obtained']):.2f}",
            "total_marks": f"{_decimal(row['total_marks']):.2f}",
            "percentage": float(row["percentage"]),
            "grade": _grade(float(row["percentage"])),
        } for row in rows]
        return {
            "data": data,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_records": total,
                "total_pages": (total + page_size - 1) // page_size,
                "has_next": offset + page_size < total,
                "has_previous": page > 1,
            },
        }

    @router.post("/performance", status_code=201)
    def create_assessment(
        request: AssessmentCreate,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        if request.marks_obtained > request.total_marks:
            raise HTTPException(status_code=422, detail="Marks obtained cannot exceed total marks.")
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO student_assessments
                    (student_id, course_id, academic_year_id, exam_name, marks_obtained, total_marks)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    marks_obtained = VALUES(marks_obtained),
                    total_marks = VALUES(total_marks)
                """,
                (
                    request.student_id,
                    request.course_id,
                    request.academic_year_id,
                    request.exam_name.strip(),
                    request.marks_obtained,
                    request.total_marks,
                ),
            )
            assessment_id = cursor.lastrowid
            connection.commit()
        except MySQLError as exc:
            connection.rollback()
            if exc.errno == 1452:
                raise HTTPException(status_code=404, detail="Student enrollment or academic year not found.") from exc
            raise HTTPException(status_code=503, detail="Unable to save student marks.") from exc
        finally:
            cursor.close()
        percentage = float(request.marks_obtained / request.total_marks * 100)
        return {
            "id": assessment_id,
            "percentage": round(percentage, 1),
            "grade": _grade(percentage),
        }

    @router.delete("/performance/{assessment_id}")
    def delete_assessment(
        assessment_id: int,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, str]:
        cursor = connection.cursor()
        try:
            cursor.execute("DELETE FROM student_assessments WHERE id = %s", (assessment_id,))
            if cursor.rowcount == 0:
                raise _not_found("Assessment not found.")
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            raise HTTPException(status_code=503, detail="Unable to delete assessment.") from exc
        finally:
            cursor.close()
        return {"message": "Assessment deleted."}

    @router.get("/events")
    def list_events(
        upcoming_only: bool = False,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> list[dict[str, Any]]:
        cursor = connection.cursor(dictionary=True)
        try:
            query = "SELECT id, title, description, starts_at, ends_at, created_at FROM school_events"
            if upcoming_only:
                query += " WHERE starts_at >= NOW()"
            query += " ORDER BY starts_at"
            cursor.execute(query)
            return cursor.fetchall()
        except MySQLError as exc:
            raise HTTPException(status_code=503, detail="Unable to load school events.") from exc
        finally:
            cursor.close()

    @router.post("/events", status_code=201)
    def create_event(
        request: SchoolEventRequest,
        admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        if request.ends_at and request.ends_at < request.starts_at:
            raise HTTPException(status_code=422, detail="Event end must be after its start.")
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO school_events (title, description, starts_at, ends_at, created_by)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    request.title.strip(),
                    request.description.strip() if request.description else None,
                    request.starts_at,
                    request.ends_at,
                    _admin_user_id(admin),
                ),
            )
            event_id = cursor.lastrowid
            connection.commit()
        except MySQLError as exc:
            connection.rollback()
            raise HTTPException(status_code=503, detail="Unable to create school event.") from exc
        finally:
            cursor.close()
        return {"id": event_id, **request.model_dump()}

    @router.patch("/events/{event_id}")
    def update_event(
        event_id: int,
        request: SchoolEventRequest,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        if request.ends_at and request.ends_at < request.starts_at:
            raise HTTPException(status_code=422, detail="Event end must be after its start.")
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT id FROM school_events WHERE id = %s", (event_id,))
            if cursor.fetchone() is None:
                raise _not_found("Event not found.")
            cursor.execute(
                """
                UPDATE school_events SET title = %s, description = %s, starts_at = %s, ends_at = %s
                WHERE id = %s
                """,
                (
                    request.title.strip(),
                    request.description.strip() if request.description else None,
                    request.starts_at,
                    request.ends_at,
                    event_id,
                ),
            )
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            raise HTTPException(status_code=503, detail="Unable to update school event.") from exc
        finally:
            cursor.close()
        return {"id": event_id, **request.model_dump()}

    @router.delete("/events/{event_id}")
    def delete_event(
        event_id: int,
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, str]:
        cursor = connection.cursor()
        try:
            cursor.execute("DELETE FROM school_events WHERE id = %s", (event_id,))
            if cursor.rowcount == 0:
                raise _not_found("Event not found.")
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            raise HTTPException(status_code=503, detail="Unable to delete school event.") from exc
        finally:
            cursor.close()
        return {"message": "Event deleted."}

    @router.get("/staff-attendance/report")
    def staff_attendance_report(
        month: str,
        staff_type: Optional[Literal["teacher", "non_teaching"]] = None,
        staff_id: Optional[int] = None,
        search: Optional[str] = Query(default=None, max_length=120),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
        _admin: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise HTTPException(status_code=422, detail="Month must use YYYY-MM format.")

        start = date.fromisoformat(f"{month}-01")
        end = (
            date(start.year + 1, 1, 1)
            if start.month == 12
            else date(start.year, start.month + 1, 1)
        )
        base_clauses = ["a.attendance_date >= %s", "a.attendance_date < %s"]
        base_parameters: list[Any] = [start, end]
        if staff_type:
            base_clauses.append("s.staff_type = %s")
            base_parameters.append(staff_type)
        if staff_id:
            base_clauses.append("s.id = %s")
            base_parameters.append(staff_id)

        search_clauses = list(base_clauses)
        search_parameters = list(base_parameters)
        search_term = search.strip() if search else ""
        if search_term:
            pattern = f"%{search_term}%"
            search_clauses.append(
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
            search_parameters.extend([pattern] * 9)

        offset = (page - 1) * page_size
        cursor = connection.cursor(dictionary=True)
        try:
            # Summary is kept independent of the text search so it remains a
            # complete monthly summary for the selected staff role.
            cursor.execute(
                """
                SELECT a.attendance_date, a.status, COUNT(*) AS count
                FROM staff_attendance AS a
                JOIN staff AS s ON s.id = a.staff_id
                WHERE """ + " AND ".join(base_clauses) + """
                GROUP BY a.attendance_date, a.status
                ORDER BY a.attendance_date
                """,
                tuple(base_parameters),
            )
            daily = cursor.fetchall()

            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM staff_attendance AS a
                JOIN staff AS s ON s.id = a.staff_id
                JOIN users AS u ON u.id = s.user_id
                WHERE """ + " AND ".join(search_clauses),
                tuple(search_parameters),
            )
            total = int(cursor.fetchone()["total"])

            cursor.execute(
                """
                SELECT s.id AS staff_id, s.employee_number, s.staff_type,
                       s.designation, s.department,
                       CONCAT(u.first_name, ' ', u.last_name) AS name,
                       a.attendance_date, a.status, a.check_in, a.check_out, a.notes
                FROM staff_attendance AS a
                JOIN staff AS s ON s.id = a.staff_id
                JOIN users AS u ON u.id = s.user_id
                WHERE """ + " AND ".join(search_clauses) + """
                ORDER BY a.attendance_date DESC, u.last_name, u.first_name, s.id DESC
                LIMIT %s OFFSET %s
                """,
                tuple([*search_parameters, page_size, offset]),
            )
            records = cursor.fetchall()
        except MySQLError as exc:
            raise HTTPException(status_code=503, detail="Unable to load staff attendance report.") from exc
        finally:
            cursor.close()

        summary: dict[str, int] = {
            "present": 0, "absent": 0, "late": 0, "half_day": 0, "on_leave": 0
        }
        for row in daily:
            summary[row["status"]] = summary.get(row["status"], 0) + int(row["count"])

        return {
            "month": month,
            "summary": summary,
            "daily": daily,
            "records": records,
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
