import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from collections.abc import Callable, Generator
from datetime import date
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from mysql.connector import Error as MySQLError
from mysql.connector import MySQLConnection
from pydantic import BaseModel, Field

ADMIN_USERNAME = "admin"
PASSWORD_HASH_ITERATIONS = 310_000
ACCESS_TOKEN_LIFETIME_SECONDS = 3600
DatabaseDependency = Callable[[], Generator[MySQLConnection, None, None]]

bearer_scheme = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


class StudentProfile(BaseModel):
    admission_number: str = Field(min_length=1, max_length=40)
    date_of_birth: Optional[date] = None
    gender: Optional[str] = Field(default=None, max_length=30)
    admission_date: date
    course_ids: list[int] = Field(min_length=1)
    academic_year_id: int = Field(gt=0)
    address: str = Field(min_length=1, max_length=500)
    parent_guardian_name: Optional[str] = Field(default=None, max_length=160)
    parent_contact: Optional[str] = Field(default=None, max_length=30)
    fee_amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    class_name: str = Field(min_length=1, max_length=80)
    status: Literal["active", "inactive", "graduated", "withdrawn"] = "active"


class TeacherProfile(BaseModel):
    joining_date: date
    course_ids: list[int] = Field(min_length=1)
    education: str = Field(min_length=1, max_length=500)
    experience_years: Decimal = Field(default=Decimal("0"), ge=0, max_digits=4, decimal_places=1)
    department: Optional[str] = Field(default=None, max_length=120)
    address: Optional[str] = Field(default=None, max_length=500)
    salary: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class NonTeachingStaffProfile(BaseModel):
    salary: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    work: str = Field(min_length=1, max_length=120)
    shift: str = Field(min_length=1, max_length=80)
    joining_date: Optional[date] = None
    department: Optional[str] = Field(default=None, max_length=120)
    address: Optional[str] = Field(default=None, max_length=500)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["student", "teacher", "non_teaching_staff"]
    email: str = Field(min_length=3, max_length=254)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=1, max_length=30)
    student: Optional[StudentProfile] = None
    teacher: Optional[TeacherProfile] = None
    non_teaching_staff: Optional[NonTeachingStaffProfile] = None


def _auth_secret() -> bytes:
    secret = os.getenv("AUTH_SECRET_KEY")
    if secret is None or len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured. Set AUTH_SECRET_KEY to at least 32 characters.",
        )
    return secret.encode("utf-8")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    )
    return "$".join(
        (
            "pbkdf2_sha256",
            str(PASSWORD_HASH_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
            base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
        )
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iteration_text, salt_text, digest_text = password_hash.split("$")
        iterations = int(iteration_text)
        if algorithm != "pbkdf2_sha256" or not 1 <= iterations <= 1_000_000:
            return False
        salt = _decode_base64url(salt_text)
        expected_digest = _decode_base64url(digest_text)
    except (AttributeError, ValueError, binascii.Error):
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(actual_digest, expected_digest)


def _encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_base64url(value: str) -> bytes:
    padded_value = value + "=" * (-len(value) % 4)
    return base64.b64decode(padded_value, altchars=b"-_", validate=True)


def _create_access_token(subject: str, roles: list[str]) -> str:
    issued_at = int(time.time())
    header = _encode_base64url(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    payload = _encode_base64url(
        json.dumps(
            {
                "sub": subject,
                "roles": roles,
                "iat": issued_at,
                "exp": issued_at + ACCESS_TOKEN_LIFETIME_SECONDS,
            },
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(_auth_secret(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_encode_base64url(signature)}"


def _decode_access_token(token: str) -> dict[str, Any]:
    try:
        header_text, payload_text, signature_text = token.split(".")
        signing_input = f"{header_text}.{payload_text}".encode("ascii")
        signature = _decode_base64url(signature_text)
        expected_signature = hmac.new(
            _auth_secret(), signing_input, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("Invalid token signature")

        header = json.loads(_decode_base64url(header_text))
        payload = json.loads(_decode_base64url(payload_text))
        if (
            not isinstance(header, dict)
            or header.get("alg") != "HS256"
            or not isinstance(payload, dict)
            or not isinstance(payload.get("sub"), str)
            or not isinstance(payload.get("roles"), list)
            or not all(isinstance(role, str) for role in payload["roles"])
            or not isinstance(payload.get("exp"), int)
            or payload["exp"] <= int(time.time())
        ):
            raise ValueError("Invalid or expired token")
    except HTTPException:
        raise
    except (
        binascii.Error,
        json.JSONDecodeError,
        UnicodeDecodeError,
        UnicodeEncodeError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return payload


def _require_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer access token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = _decode_access_token(credentials.credentials)
    if "admin" not in claims["roles"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required.",
        )
    return claims


def _require_teacher(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer access token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = _decode_access_token(credentials.credentials)
    if "teacher" not in claims["roles"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Teacher access required.",
        )
    return claims


def _require_student(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer access token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = _decode_access_token(credentials.credentials)
    if "student" not in claims["roles"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student access required.",
        )
    return claims


def create_auth_router(
    database_dependency: DatabaseDependency,
) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["authentication"])

    @router.post("/login")
    def login(
        request: LoginRequest,
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        username = request.username.strip()

        if username.casefold() == ADMIN_USERNAME:
            admin_password = os.getenv("ADMIN_PASSWORD")
            if admin_password is None or not admin_password:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Authentication is not configured. Set ADMIN_PASSWORD.",
                )
            if hmac.compare_digest(request.password, admin_password):
                token = _create_access_token(ADMIN_USERNAME, ["admin"])
                return {
                    "access_token": token,
                    "token_type": "bearer",
                    "user": {"username": ADMIN_USERNAME, "roles": ["admin"]},
                }
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT u.id, u.password_hash, r.code AS role
                FROM users AS u
                JOIN user_roles AS ur ON ur.user_id = u.id
                JOIN roles AS r ON r.id = ur.role_id
                WHERE u.username = %s AND u.is_active = TRUE
                """,
                (username,),
            )
            rows = cursor.fetchall()
        except MySQLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to query user credentials.",
            ) from exc
        finally:
            cursor.close()

        if not rows or not verify_password(request.password, rows[0]["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        roles = sorted({row["role"] for row in rows})
        token = _create_access_token(str(rows[0]["id"]), roles)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": rows[0]["id"],
                "username": username,
                "roles": roles,
            },
        }

    return router


def create_user_router(database_dependency: DatabaseDependency) -> APIRouter:
    router = APIRouter(prefix="/users", tags=["user management"])

    @router.post("/", status_code=status.HTTP_201_CREATED)
    def create_user(
        request: CreateUserRequest,
        claims: dict[str, Any] = Depends(_require_admin),
        connection: MySQLConnection = Depends(database_dependency),
    ) -> dict[str, Any]:
        del claims
        username = request.username.strip()
        email = request.email.strip()
        first_name = request.first_name.strip()
        last_name = request.last_name.strip()
        phone = request.phone.strip()
        if (
            username.casefold() == ADMIN_USERNAME
            or not re.fullmatch(r"[A-Za-z0-9._-]{3,80}", username)
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Username must be 3-80 characters using letters, numbers, '.', '_' or '-'; 'admin' is reserved.",
            )
        if (
            not email
            or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
            or not first_name
            or not last_name
            or not phone
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A valid email, first name, last name, and phone number are required.",
            )

        profiles = {
            "student": request.student,
            "teacher": request.teacher,
            "non_teaching_staff": request.non_teaching_staff,
        }
        selected_profile = profiles[request.role]
        if selected_profile is None or sum(
            profile is not None for profile in profiles.values()
        ) != 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Provide exactly one profile object matching role '{request.role}'.",
            )

        course_ids: list[int] = []
        if request.student is not None:
            course_ids = request.student.course_ids
        elif request.teacher is not None:
            course_ids = request.teacher.course_ids
        if course_ids and (
            any(course_id <= 0 for course_id in course_ids)
            or len(course_ids) != len(set(course_ids))
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Course IDs must be positive and unique.",
            )

        cursor = connection.cursor(dictionary=True)
        student_id = None
        staff_id = None
        employee_number = None
        try:
            cursor.execute(
                "SELECT id FROM roles WHERE code = %s LIMIT 1", (request.role,)
            )
            role = cursor.fetchone()
            if role is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="The requested role is missing from the database.",
                )

            cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
            if cursor.fetchone() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="That username is already in use.",
                )

            if request.student is not None:
                cursor.execute(
                    "SELECT id FROM academic_years WHERE id = %s",
                    (request.student.academic_year_id,),
                )
                if cursor.fetchone() is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="The selected academic year does not exist.",
                    )

            if course_ids:
                placeholders = ", ".join(["%s"] * len(course_ids))
                lock_clause = " FOR UPDATE" if request.teacher is not None else ""
                cursor.execute(
                    f"SELECT id, teacher_id, class_name FROM courses WHERE id IN ({placeholders}){lock_clause}",
                    tuple(course_ids),
                )
                courses = cursor.fetchall()
                found_course_ids = {course["id"] for course in courses}
                if found_course_ids != set(course_ids):
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="One or more selected courses do not exist.",
                    )
                if request.student is not None:
                    def class_key(value: Optional[str]) -> Optional[str]:
                        if not value:
                            return None
                        match = re.match(r"\s*(\d+)", str(value).strip())
                        return match.group(1) if match else str(value).strip().lower()

                    student_class = class_key(request.student.class_name)
                    mismatched = [
                        course["course_code"]
                        for course in courses
                        if "class_name" in course
                        and class_key(course["class_name"]) != student_class
                    ]
                    if mismatched:
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Selected courses do not belong to class {request.student.class_name}: {', '.join(mismatched)}",
                        )
                if request.teacher is not None and any(
                    course["teacher_id"] is not None for course in courses
                ):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="One or more selected courses already have a teacher.",
                    )

            cursor.execute(
                """
                INSERT INTO users (
                    username, email, password_hash, first_name, last_name, phone
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    username,
                    email,
                    hash_password(request.password),
                    first_name,
                    last_name,
                    phone,
                ),
            )
            user_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s)",
                (user_id, role["id"]),
            )

            if request.student is not None:
                student = request.student
                cursor.execute(
                    """
                    INSERT INTO students (
                        user_id, admission_number, date_of_birth, gender, admission_date,
                        address, parent_guardian_name, parent_contact, status, class_name,
                        fee_amount
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        student.admission_number,
                        student.date_of_birth,
                        student.gender.strip() if student.gender else None,
                        student.admission_date,
                        student.address.strip(),
                        (
                            student.parent_guardian_name.strip()
                            if student.parent_guardian_name
                            else None
                        ),
                        student.parent_contact.strip() if student.parent_contact else None,
                        student.status,
                        student.class_name.strip(),
                        student.fee_amount,
                    ),
                )
                student_id = cursor.lastrowid
                for course_id in student.course_ids:
                    cursor.execute(
                        """
                        INSERT INTO student_courses (
                            student_id, course_id, academic_year_id, enrolled_at
                        )
                        VALUES (%s, %s, %s, %s)
                        """,
                        (
                            student_id,
                            course_id,
                            student.academic_year_id,
                            date.today(),
                        ),
                    )
            else:
                if request.teacher is not None:
                    staff_type = "teacher"
                    designation = "Teacher"
                    hire_date = request.teacher.joining_date
                    education = request.teacher.education.strip()
                    experience_years = request.teacher.experience_years
                    department = (
                        request.teacher.department.strip()
                        if request.teacher.department
                        else None
                    )
                    staff_address = (
                        request.teacher.address.strip()
                        if request.teacher.address
                        else None
                    )
                    salary = request.teacher.salary
                    shift = None
                elif request.non_teaching_staff is not None:
                    non_teaching = request.non_teaching_staff
                    staff_type = "non_teaching"
                    designation = non_teaching.work.strip()
                    hire_date = non_teaching.joining_date or date.today()
                    education = None
                    experience_years = Decimal("0")
                    department = (
                        non_teaching.department.strip()
                        if non_teaching.department
                        else None
                    )
                    staff_address = (
                        non_teaching.address.strip()
                        if non_teaching.address
                        else None
                    )
                    salary = non_teaching.salary
                    shift = non_teaching.shift.strip()
                else:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Provide a profile object matching role '{request.role}'.",
                    )

                employee_number = f"EMP{user_id:06d}"
                cursor.execute(
                    """
                    INSERT INTO staff (
                        user_id, employee_number, staff_type, designation, hire_date,
                        education, experience_years, department, address, base_salary, shift
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        employee_number,
                        staff_type,
                        designation,
                        hire_date,
                        education,
                        experience_years,
                        department,
                        staff_address,
                        salary,
                        shift,
                    ),
                )
                staff_id = cursor.lastrowid

                if request.teacher is not None:
                    placeholders = ", ".join(["%s"] * len(course_ids))
                    cursor.execute(
                        f"UPDATE courses SET teacher_id = %s WHERE id IN ({placeholders}) AND teacher_id IS NULL",
                        (staff_id, *course_ids),
                    )
                    if cursor.rowcount != len(course_ids):
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail="A selected course was assigned to another teacher.",
                        )

            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except MySQLError as exc:
            connection.rollback()
            if exc.errno == 1062:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The username, admission number, or employee number is already in use.",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to create the user and role profile.",
            ) from exc
        finally:
            cursor.close()

        result: dict[str, Any] = {
            "id": user_id,
            "username": username,
            "role": request.role,
        }
        if student_id is not None:
            result["student_id"] = student_id
        if staff_id is not None:
            result["staff_id"] = staff_id
            result["employee_number"] = employee_number
        return result

    return router