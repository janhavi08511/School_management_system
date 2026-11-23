from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from mysql.connector import Error as MySQLError
from mysql.connector import MySQLConnection

from Auth import DatabaseDependency, _require_student
from Teacher import NOTE_STORAGE_DIR


def _student_user_id(claims: dict[str, Any]) -> int:
    try:
        return int(claims["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Student account is not valid.",
        ) from exc


def _get_student(cursor: Any, user_id: int) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT s.id AS student_id, s.admission_number, s.date_of_birth,
               s.gender, s.admission_date, s.address, s.parent_guardian_name,
               s.parent_contact, s.status, s.class_name, s.fee_amount,
               u.username, u.email, u.phone, u.first_name, u.last_name
        FROM students AS s
        JOIN users AS u ON u.id = s.user_id
        WHERE s.user_id = %s
        """,
        (user_id,),
    )
    student = cursor.fetchone()
    if student is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found.",
        )
    return student


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


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


def create_student_router(database_dependency: DatabaseDependency) -> APIRouter:
    router = APIRouter(prefix="/student", tags=["student"])

    @router.get("/profile")
    def get_student_profile(
        claims: dict[str, Any] = Depends(_require_student),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        cursor = connection.cursor(dictionary=True)
        try:
            student = _get_student(cursor, _student_user_id(claims))
            cursor.execute(
                """
                SELECT c.id AS course_id, c.course_code, c.name AS course_name,
                       sc.academic_year_id, ay.name AS academic_year,
                       sc.status AS enrollment_status
                FROM student_courses AS sc
                JOIN courses AS c ON c.id = sc.course_id
                JOIN academic_years AS ay ON ay.id = sc.academic_year_id
                WHERE sc.student_id = %s
                ORDER BY ay.start_date DESC, c.course_code
                """,
                (student["student_id"],),
            )
            courses = cursor.fetchall()
        except HTTPException:
            raise
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load the student profile.",
            ) from exc
        finally:
            cursor.close()

        return {
            "student": {
                **student,
                "name": f"{student['first_name']} {student['last_name']}".strip(),
                "fee_amount": f"{_decimal(student['fee_amount']):.2f}",
            },
            "courses": courses,
        }

    @router.get("/notes")
    def list_student_notes(
        course_id: Optional[int] = Query(default=None, gt=0),
        search: Optional[str] = Query(default=None, max_length=100),
        claims: dict[str, Any] = Depends(_require_student),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> list[dict[str, Any]]:
        query = """
            SELECT n.id, n.course_id, n.title, n.description,
                   n.original_filename,
                   UPPER(SUBSTRING_INDEX(n.original_filename, '.', -1)) AS file_type,
                   n.uploaded_at, n.file_size, n.download_count,
                   c.course_code, c.name AS course_name,
                   CONCAT(u.first_name, ' ', u.last_name) AS teacher_name
            FROM course_notes AS n
            JOIN courses AS c ON c.id = n.course_id
            JOIN staff AS st ON st.id = n.uploaded_by
            JOIN users AS u ON u.id = st.user_id
            WHERE EXISTS (
                SELECT 1
                FROM students AS own_student
                JOIN student_courses AS sc ON sc.student_id = own_student.id
                WHERE own_student.user_id = %s
                  AND sc.course_id = c.id
                  AND sc.status IN ('enrolled', 'completed')
            )
        """
        parameters: list[Any] = [_student_user_id(claims)]
        if course_id is not None:
            query += " AND c.id = %s"
            parameters.append(course_id)
        if search and search.strip():
            query += """
                AND (
                    n.title LIKE %s OR n.description LIKE %s
                    OR c.course_code LIKE %s OR c.name LIKE %s
                    OR CONCAT(u.first_name, ' ', u.last_name) LIKE %s
                )
            """
            search_term = f"%{search.strip()}%"
            parameters.extend([search_term] * 5)
        query += " ORDER BY n.uploaded_at DESC, n.id DESC"

        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(query, tuple(parameters))
            return cursor.fetchall()
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load course notes.",
            ) from exc
        finally:
            cursor.close()

    @router.get("/notes/{note_id}/download")
    def download_student_note(
        note_id: int,
        claims: dict[str, Any] = Depends(_require_student),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> FileResponse:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT n.stored_filename, n.original_filename, n.content_type
                FROM course_notes AS n
                JOIN courses AS c ON c.id = n.course_id
                WHERE n.id = %s
                  AND EXISTS (
                      SELECT 1
                      FROM students AS own_student
                      JOIN student_courses AS sc ON sc.student_id = own_student.id
                      WHERE own_student.user_id = %s
                        AND sc.course_id = c.id
                        AND sc.status IN ('enrolled', 'completed')
                  )
                """,
                (note_id, _student_user_id(claims)),
            )
            note = cursor.fetchone()
            if note is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Course note not found.",
                )
            stored_path = NOTE_STORAGE_DIR / Path(note["stored_filename"]).name
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
            connection.rollback()
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

    @router.get("/fees")
    def get_student_fees(
        claims: dict[str, Any] = Depends(_require_student),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        cursor = connection.cursor(dictionary=True)
        try:
            student = _get_student(cursor, _student_user_id(claims))
            student_id = student["student_id"]
            cursor.execute(
                """
                SELECT i.id, i.amount, i.due_date, i.status,
                       ay.name AS academic_year, ft.name AS fee_name,
                       COALESCE((
                           SELECT SUM(p.amount)
                           FROM fee_payments AS p
                           WHERE p.invoice_id = i.id
                       ), 0) AS paid_amount
                FROM fee_invoices AS i
                JOIN fee_types AS ft ON ft.id = i.fee_type_id
                JOIN academic_years AS ay ON ay.id = i.academic_year_id
                WHERE i.student_id = %s
                ORDER BY i.due_date, i.id
                """,
                (student_id,),
            )
            invoice_rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT id, amount, paid_at, payment_method,
                       transaction_reference, notes, received_by_username
                FROM student_fee_payments
                WHERE student_id = %s
                ORDER BY paid_at DESC, id DESC
                """,
                (student_id,),
            )
            legacy_payments = cursor.fetchall()
            cursor.execute(
                """
                SELECT p.id, p.amount, p.paid_at, p.payment_method,
                       p.transaction_reference, p.notes,
                       u.username AS received_by_username,
                       i.id AS invoice_id, ft.name AS fee_name,
                       ay.name AS academic_year
                FROM fee_payments AS p
                JOIN fee_invoices AS i ON i.id = p.invoice_id
                JOIN fee_types AS ft ON ft.id = i.fee_type_id
                JOIN academic_years AS ay ON ay.id = i.academic_year_id
                JOIN users AS u ON u.id = p.received_by
                WHERE i.student_id = %s
                ORDER BY p.paid_at DESC, p.id DESC
                """,
                (student_id,),
            )
            invoice_payments = cursor.fetchall()
        except HTTPException:
            raise
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load student fee information.",
            ) from exc
        finally:
            cursor.close()

        legacy_total = _decimal(student["fee_amount"])
        legacy_paid = sum(
            (_decimal(payment["amount"]) for payment in legacy_payments),
            Decimal("0"),
        )
        fee_items = [
            {
                "id": None,
                "fee_name": "Student fee balance",
                "academic_year": None,
                "total_fees": f"{legacy_total:.2f}",
                "paid_amount": f"{legacy_paid:.2f}",
                "pending_amount": f"{max(legacy_total - legacy_paid, Decimal('0')):.2f}",
                "due_date": None,
                "payment_status": "paid" if legacy_paid >= legacy_total else "pending",
                "source": "legacy",
            }
        ]
        invoice_total = Decimal("0")
        invoice_paid = Decimal("0")
        invoice_pending = Decimal("0")
        for invoice in invoice_rows:
            amount = _decimal(invoice["amount"])
            paid = _decimal(invoice["paid_amount"])
            pending = max(amount - paid, Decimal("0"))
            if invoice["status"] == "waived":
                payment_status = "waived"
                pending = Decimal("0")
            elif paid >= amount:
                payment_status = "paid"
            elif paid > 0:
                payment_status = "partially_paid"
            elif invoice["due_date"] < date.today():
                payment_status = "overdue"
            else:
                payment_status = "pending"
            if payment_status != "waived":
                invoice_total += amount
                invoice_paid += paid
                invoice_pending += pending
            fee_items.append(
                {
                    "id": invoice["id"],
                    "fee_name": invoice["fee_name"],
                    "academic_year": invoice["academic_year"],
                    "total_fees": f"{amount:.2f}",
                    "paid_amount": f"{paid:.2f}",
                    "pending_amount": f"{pending:.2f}",
                    "due_date": invoice["due_date"],
                    "payment_status": payment_status,
                    "source": "invoice",
                }
            )

        payment_history = [
            {
                **payment,
                "source": "legacy",
                "fee_name": "Student fee balance",
                "academic_year": None,
                "amount": f"{_decimal(payment['amount']):.2f}",
            }
            for payment in legacy_payments
        ] + [
            {
                **payment,
                "source": "invoice",
                "amount": f"{_decimal(payment['amount']):.2f}",
            }
            for payment in invoice_payments
        ]
        payment_history.sort(key=lambda payment: str(payment["paid_at"]), reverse=True)

        return {
            "total_fees": f"{legacy_total + invoice_total:.2f}",
            "paid_fees": f"{legacy_paid + invoice_paid:.2f}",
            "pending_fees": f"{max(legacy_total - legacy_paid, Decimal('0')) + invoice_pending:.2f}",
            "items": fee_items,
            "payment_history": payment_history,
        }

    @router.get("/fees/payments/{payment_id}/receipt")
    def get_student_fee_receipt(
        payment_id: int,
        source: Literal["invoice", "legacy"],
        claims: dict[str, Any] = Depends(_require_student),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        user_id = _student_user_id(claims)
        cursor = connection.cursor(dictionary=True)
        try:
            if source == "invoice":
                cursor.execute(
                    """
                    SELECT p.id, p.amount, p.paid_at, p.payment_method,
                           p.transaction_reference, p.notes,
                           i.id AS invoice_id, ft.name AS fee_name,
                           ay.name AS academic_year, s.admission_number,
                           s.class_name,
                           CONCAT(u.first_name, ' ', u.last_name) AS student_name
                    FROM fee_payments AS p
                    JOIN fee_invoices AS i ON i.id = p.invoice_id
                    JOIN fee_types AS ft ON ft.id = i.fee_type_id
                    JOIN academic_years AS ay ON ay.id = i.academic_year_id
                    JOIN students AS s ON s.id = i.student_id
                    JOIN users AS u ON u.id = s.user_id
                    WHERE p.id = %s AND s.user_id = %s
                    """,
                    (payment_id, user_id),
                )
            else:
                cursor.execute(
                    """
                    SELECT p.id, p.amount, p.paid_at, p.payment_method,
                           p.transaction_reference, p.notes,
                           NULL AS invoice_id, 'Student fee balance' AS fee_name,
                           NULL AS academic_year, s.admission_number, s.class_name,
                           CONCAT(u.first_name, ' ', u.last_name) AS student_name
                    FROM student_fee_payments AS p
                    JOIN students AS s ON s.id = p.student_id
                    JOIN users AS u ON u.id = s.user_id
                    WHERE p.id = %s AND s.user_id = %s
                    """,
                    (payment_id, user_id),
                )
            receipt = cursor.fetchone()
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load fee receipt.",
            ) from exc
        finally:
            cursor.close()
        if receipt is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fee receipt not found.",
            )
        return {**receipt, "amount": f"{_decimal(receipt['amount']):.2f}"}

    @router.get("/performance")
    def get_student_performance(
        claims: dict[str, Any] = Depends(_require_student),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        cursor = connection.cursor(dictionary=True)
        try:
            student = _get_student(cursor, _student_user_id(claims))
            cursor.execute(
                """
                SELECT a.id, a.course_id, c.course_code, c.name AS course_name,
                       ay.name AS academic_year, a.exam_name,
                       a.marks_obtained, a.total_marks, a.created_at
                FROM student_assessments AS a
                JOIN courses AS c ON c.id = a.course_id
                JOIN academic_years AS ay ON ay.id = a.academic_year_id
                WHERE a.student_id = %s
                ORDER BY a.created_at DESC, c.course_code, a.exam_name
                """,
                (student["student_id"],),
            )
            records = cursor.fetchall()
            cursor.execute(
                """
                SELECT DATE_FORMAT(a.created_at, '%Y-%m') AS month,
                       AVG(a.marks_obtained / a.total_marks * 100) AS average_percentage,
                       COUNT(*) AS assessment_count
                FROM student_assessments AS a
                WHERE a.student_id = %s
                GROUP BY DATE_FORMAT(a.created_at, '%Y-%m')
                ORDER BY month
                """,
                (student["student_id"],),
            )
            trends = cursor.fetchall()
        except HTTPException:
            raise
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load student performance.",
            ) from exc
        finally:
            cursor.close()

        course_summaries: dict[int, dict[str, Any]] = {}
        formatted_records = []
        for record in records:
            percentage = (
                float(_decimal(record["marks_obtained"]) / _decimal(record["total_marks"]) * 100)
                if _decimal(record["total_marks"])
                else 0
            )
            formatted = {
                **record,
                "marks_obtained": f"{_decimal(record['marks_obtained']):.2f}",
                "total_marks": f"{_decimal(record['total_marks']):.2f}",
                "percentage": round(percentage, 1),
                "grade": _grade(percentage),
            }
            formatted_records.append(formatted)
            course = course_summaries.setdefault(
                int(record["course_id"]),
                {
                    "course_id": record["course_id"],
                    "course_code": record["course_code"],
                    "course_name": record["course_name"],
                    "assessment_count": 0,
                    "_percentage_total": 0.0,
                },
            )
            course["assessment_count"] += 1
            course["_percentage_total"] += percentage

        courses = []
        for course in course_summaries.values():
            average = course.pop("_percentage_total") / course["assessment_count"]
            courses.append({**course, "average_percentage": round(average, 1), "grade": _grade(average)})
        courses.sort(key=lambda course: course["course_code"])
        formatted_trends = [
            {
                **trend,
                "average_percentage": round(float(trend["average_percentage"]), 1),
            }
            for trend in trends
        ]
        overall_average = (
            sum(record["percentage"] for record in formatted_records) / len(formatted_records)
            if formatted_records
            else 0
        )
        return {
            "overall_average": round(overall_average, 1),
            "overall_grade": _grade(overall_average),
            "assessment_count": len(formatted_records),
            "courses": courses,
            "records": formatted_records,
            "trends": formatted_trends,
        }

    return router