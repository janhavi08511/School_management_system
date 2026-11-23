"""
Synthetic data generator for the School Management System.

Based on the actual MySQL CREATE TABLE definitions supplied in
school_actual_schema.txt (22 tables).

Defaults:
  100,000 students
   80,000 teachers
   20,000 non-teaching staff
    5,000 courses
  500,000 enrollments (5 per student)
  1,000,000 attendance records (2 sessions per course, subject to enrollment)
  1,000,000 assessments (2 per enrollment)

Install:
    pip install mysql-connector-python python-dotenv

Create .env beside this file:
    MYSQL_HOST=localhost
    MYSQL_PORT=3306
    MYSQL_DATABASE=school
    MYSQL_USER=root
    MYSQL_PASSWORD=your_mysql_password

Run:
    python generate_school_data.py

This script APPENDS data. It does not drop, truncate, or alter tables.
It calculates starting IDs from MAX(id), so existing rows are preserved.
"""

import os
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from itertools import islice

import mysql.connector

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ------------------------------- SETTINGS -------------------------------

STUDENT_COUNT = int(os.getenv("STUDENT_COUNT", "100000"))
TEACHER_COUNT = int(os.getenv("TEACHER_COUNT", "80000"))
NON_TEACHING_STAFF_COUNT = int(os.getenv("NON_TEACHING_STAFF_COUNT", "20000"))
COURSE_COUNT = int(os.getenv("COURSE_COUNT", "5000"))
COURSES_PER_STUDENT = int(os.getenv("COURSES_PER_STUDENT", "5"))
SESSIONS_PER_COURSE = int(os.getenv("SESSIONS_PER_COURSE", "2"))
ASSESSMENTS_PER_ENROLLMENT = int(os.getenv("ASSESSMENTS_PER_ENROLLMENT", "2"))
STAFF_ATTENDANCE_DAYS = int(os.getenv("STAFF_ATTENDANCE_DAYS", "5"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "2000"))
RANDOM_SEED = int(os.getenv("RANDOM_SEED", "42"))

DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "database": os.getenv("MYSQL_DATABASE", "school"),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "autocommit": False,
}

random.seed(RANDOM_SEED)

FIRST_NAMES = [
    "Aarav", "Aditi", "Aditya", "Ananya", "Arjun", "Diya", "Ishaan",
    "Janhavi", "Kabir", "Kavya", "Meera", "Neha", "Rohan", "Saanvi",
    "Sai", "Sakshi", "Vihaan", "Zoya", "Rahul", "Priya", "Ira",
    "Vedant", "Mira", "Om", "Tanvi", "Yash",
]
LAST_NAMES = [
    "Patil", "Sharma", "Deshmukh", "Kulkarni", "Joshi", "More",
    "Pawar", "Jadhav", "Shinde", "Kadam", "Gupta", "Verma",
    "Chavan", "Khan", "Shaikh", "Singh", "Nair", "Rao",
]
DEPARTMENTS = [
    "Computer Science", "Mathematics", "Physics", "Chemistry",
    "Biology", "English", "History", "Commerce", "Administration",
]
COURSE_NAMES = [
    "Mathematics", "English", "Science", "Physics", "Chemistry",
    "Biology", "Computer Science", "History", "Geography",
    "Economics", "Accountancy", "Business Studies", "Programming",
    "Database Management", "Web Development", "Cyber Security",
    "Artificial Intelligence", "Machine Learning", "Computer Networks",
    "Operating Systems", "Software Engineering", "Cloud Computing",
]
CLASS_NAMES = ["Class 1", "Class 2", "Class 3", "Class 4", "Class 5",
               "Class 6", "Class 7", "Class 8", "Class 9", "Class 10",
               "Class 11", "Class 12"]
PAYMENT_METHODS = ["cash", "card", "bank_transfer", "online", "other"]
ATTENDANCE_STATUSES = ["present", "present", "present", "absent", "late", "excused"]
ROOMS = [f"Room-{i:03d}" for i in range(1, 201)]


# ------------------------------- HELPERS ---------------------------------

def batches(iterable, size=BATCH_SIZE):
    iterator = iter(iterable)
    while True:
        batch = list(islice(iterator, size))
        if not batch:
            return
        yield batch


def bulk_insert(cursor, table, columns, rows):
    """Insert rows in bounded batches; all values use parameter placeholders."""
    col_sql = ", ".join(f"`{c}`" for c in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    sql = f"INSERT INTO `{table}` ({col_sql}) VALUES ({placeholders})"
    total = 0
    for batch in batches(rows):
        cursor.executemany(sql, batch)
        total += len(batch)
    print(f"  {table}: {total:,} rows")


def next_id(cursor, table):
    cursor.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM `{table}`")
    return int(cursor.fetchone()[0])


def get_or_create_roles(cursor):
    required = [
        ("ADMIN", "Administrator"),
        ("STUDENT", "Student"),
        ("TEACHER", "Teacher"),
        ("NON_TEACHING_STAFF", "Non-Teaching Staff"),
    ]
    result = {}
    for code, name in required:
        cursor.execute("SELECT id FROM roles WHERE code = %s", (code,))
        row = cursor.fetchone()
        if row:
            result[code] = int(row[0])
        else:
            cursor.execute(
                "INSERT INTO roles (code, name) VALUES (%s, %s)",
                (code, name),
            )
            result[code] = int(cursor.lastrowid)
    return result


def get_or_create_permissions(cursor):
    permission_data = [
        ("users.read", "View users"),
        ("users.write", "Manage users"),
        ("students.read", "View students"),
        ("students.write", "Manage students"),
        ("courses.read", "View courses"),
        ("courses.write", "Manage courses"),
        ("attendance.read", "View attendance"),
        ("attendance.write", "Record attendance"),
        ("fees.read", "View fees"),
        ("fees.write", "Manage fees"),
        ("payroll.read", "View payroll"),
        ("payroll.write", "Manage payroll"),
        ("events.read", "View school events"),
        ("events.write", "Manage school events"),
    ]
    result = {}
    for code, description in permission_data:
        cursor.execute("SELECT id FROM permissions WHERE code = %s", (code,))
        row = cursor.fetchone()
        if row:
            result[code] = int(row[0])
        else:
            cursor.execute(
                "INSERT INTO permissions (code, description) VALUES (%s, %s)",
                (code, description),
            )
            result[code] = int(cursor.lastrowid)
    return result


def create_role_permissions(cursor, roles, permissions):
    mapping = {
        "ADMIN": list(permissions.keys()),
        "STUDENT": ["courses.read", "attendance.read", "fees.read", "events.read"],
        "TEACHER": ["students.read", "courses.read", "attendance.read",
                    "attendance.write", "events.read"],
        "NON_TEACHING_STAFF": ["students.read", "courses.read", "fees.read", "events.read"],
    }
    rows = []
    for role_code, permission_codes in mapping.items():
        for permission_code in permission_codes:
            rows.append((roles[role_code], permissions[permission_code]))
    for batch in batches(rows):
        # Existing mappings are harmlessly ignored.
        cursor.executemany(
            "INSERT IGNORE INTO role_permissions (role_id, permission_id) VALUES (%s, %s)",
            batch,
        )


def get_or_create_academic_years(cursor):
    year_data = [
        ("2024-2025", date(2024, 6, 1), date(2025, 4, 30), 0),
        ("2025-2026", date(2025, 6, 1), date(2026, 4, 30), 0),
        ("2026-2027", date(2026, 6, 1), date(2027, 4, 30), 1),
    ]
    ids = []
    for name, start, end, current in year_data:
        cursor.execute("SELECT id FROM academic_years WHERE name = %s", (name,))
        row = cursor.fetchone()
        if row:
            ids.append(int(row[0]))
        else:
            cursor.execute(
                """INSERT INTO academic_years
                   (name, start_date, end_date, is_current)
                   VALUES (%s, %s, %s, %s)""",
                (name, start, end, current),
            )
            ids.append(int(cursor.lastrowid))
    return ids


def name_for(number):
    first = FIRST_NAMES[(number - 1) % len(FIRST_NAMES)]
    last = LAST_NAMES[((number - 1) // len(FIRST_NAMES)) % len(LAST_NAMES)]
    return first, last


def random_phone(number):
    return f"+9198{number % 100000000:08d}"


def make_email(prefix, number):
    return f"{prefix}{number:08d}@example.test"


def decimal_money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


# ---------------------------- DATA GENERATORS ----------------------------

def generate_users(cursor, first_user_id, admin_role_id):
    print("\n[1/11] Creating users and user roles")
    total_students = STUDENT_COUNT
    total_staff = TEACHER_COUNT + NON_TEACHING_STAFF_COUNT
    total_people = total_students + total_staff
    admin_user_id = first_user_id + total_people
    created = datetime(2026, 1, 1, 9, 0, 0)

    def user_rows():
        for i in range(1, total_people + 1):
            if i <= total_students:
                prefix = "student"
            elif i <= total_students + TEACHER_COUNT:
                prefix = "teacher"
            else:
                prefix = "staff"
            first, last = name_for(i)
            yield (
                first_user_id + i - 1,
                f"{prefix}_{first_user_id + i - 1}",
                make_email(prefix, first_user_id + i - 1),
                "SYNTHETIC_HASH_NOT_FOR_LOGIN",
                first, last, random_phone(i), None, 1,
                created + timedelta(seconds=i),
            )

    bulk_insert(
        cursor, "users",
        ["id", "username", "email", "password_hash", "first_name", "last_name",
         "phone", "profile_photo_path", "is_active", "created_at"],
        user_rows(),
    )

    admin_id = admin_user_id
    bulk_insert(
        cursor, "users",
        ["id", "username", "email", "password_hash", "first_name", "last_name",
         "phone", "profile_photo_path", "is_active", "created_at"],
        [(admin_id, "synthetic_admin", "synthetic_admin@example.test",
          "SYNTHETIC_HASH_NOT_FOR_LOGIN", "Synthetic", "Administrator",
          None, None, 1, created)],
    )

    def role_rows():
        for i in range(1, total_people + 1):
            user_id = first_user_id + i - 1
            if i <= total_students:
                role_id = STUDENT_ROLE_ID
            elif i <= total_students + TEACHER_COUNT:
                role_id = TEACHER_ROLE_ID
            else:
                role_id = STAFF_ROLE_ID
            yield (user_id, role_id)

    bulk_insert(cursor, "user_roles", ["user_id", "role_id"], role_rows())
    bulk_insert(cursor, "user_roles", ["user_id", "role_id"], [(admin_id, admin_role_id)])
    return admin_id


def generate_students(cursor, first_student_id, first_user_id):
    print("\n[2/11] Creating student profiles")

    def rows():
        for i in range(1, STUDENT_COUNT + 1):
            student_id = first_student_id + i - 1
            user_id = first_user_id + i - 1
            first, last = name_for(i)
            dob = date(2007, 1, 1) + timedelta(days=(i * 17) % 2500)
            admission = date(2024, 6, 1) + timedelta(days=i % 650)
            yield (
                student_id, user_id, f"ADM{student_id:09d}", dob,
                random.choice(["Male", "Female", "Other"]),
                admission,
                f"House {i % 999 + 1}, Nashik, Maharashtra",
                f"{FIRST_NAMES[(i + 5) % len(FIRST_NAMES)]} {last}",
                random_phone(i + 500000),
                "active",
                CLASS_NAMES[(i - 1) % len(CLASS_NAMES)],
                decimal_money(random.choice([18000, 22000, 25000, 30000, 35000])),
            )

    bulk_insert(
        cursor, "students",
        ["id", "user_id", "admission_number", "date_of_birth", "gender",
         "admission_date", "address", "parent_guardian_name", "parent_contact",
         "status", "class_name", "fee_amount"],
        rows(),
    )


def generate_staff(cursor, first_staff_id, first_user_id):
    print("\n[3/11] Creating teaching and non-teaching staff")

    def rows():
        total = TEACHER_COUNT + NON_TEACHING_STAFF_COUNT
        for i in range(1, total + 1):
            staff_id = first_staff_id + i - 1
            user_id = first_user_id + STUDENT_COUNT + i - 1
            is_teacher = i <= TEACHER_COUNT
            staff_type = "teacher" if is_teacher else "non_teaching"
            if is_teacher:
                designation = random.choice(
                    ["Primary Teacher", "Secondary Teacher", "Senior Teacher",
                     "Subject Teacher", "Assistant Professor", "HOD"]
                )
                department = random.choice(DEPARTMENTS[:8])
                salary = random.randint(28000, 85000)
            else:
                designation = random.choice(
                    ["Accountant", "Librarian", "Clerk", "Lab Assistant",
                     "Office Assistant", "Security Supervisor", "Counsellor"]
                )
                department = random.choice(["Administration", "Library", "Accounts",
                                            "Laboratory", "Facilities"])
                salary = random.randint(16000, 45000)

            yield (
                staff_id, user_id, f"EMP{staff_id:09d}", staff_type,
                designation,
                date(2016, 1, 1) + timedelta(days=(i * 11) % 3500),
                "active",
                random.choice(["B.Ed", "M.Sc", "M.A", "B.Com", "M.Com", "B.Sc", "MBA"]),
                Decimal(str(round(random.uniform(0.5, 20.0), 1))),
                department,
                f"Staff Housing {i % 500 + 1}, Nashik, Maharashtra",
                decimal_money(salary),
                random.choice(["Morning", "General", "Evening"]),
            )

    bulk_insert(
        cursor, "staff",
        ["id", "user_id", "employee_number", "staff_type", "designation",
         "hire_date", "status", "education", "experience_years", "department",
         "address", "base_salary", "shift"],
        rows(),
    )


def generate_courses(cursor, first_course_id, first_staff_id, year_ids):
    print("\n[4/11] Creating courses")

    def rows():
        for i in range(1, COURSE_COUNT + 1):
            course_id = first_course_id + i - 1
            teacher_id = first_staff_id + ((i - 1) % TEACHER_COUNT)
            year_id = year_ids[(i - 1) % len(year_ids)]
            class_name = CLASS_NAMES[(i - 1) % len(CLASS_NAMES)]
            base_name = COURSE_NAMES[(i - 1) % len(COURSE_NAMES)]
            yield (
                course_id, f"CRS{course_id:08d}",
                f"{base_name} - {class_name} - {i}",
                f"Synthetic course description for {base_name}.",
                class_name, random.randint(3, 12), year_id, teacher_id,
            )

    bulk_insert(
        cursor, "courses",
        ["id", "course_code", "name", "description", "class_name",
         "duration_months", "academic_year_id", "teacher_id"],
        rows(),
    )


def generate_enrollments(cursor, first_student_id, first_course_id, year_ids):
    print("\n[5/11] Creating student-course enrollments")
    enrollment_pairs = []
    rows = []
    for student_offset in range(STUDENT_COUNT):
        student_id = first_student_id + student_offset
        # Deterministic distinct courses per student; avoids expensive random.sample.
        chosen = set()
        attempt = 0
        while len(chosen) < min(COURSES_PER_STUDENT, COURSE_COUNT):
            chosen.add((student_offset * 7 + attempt * 997) % COURSE_COUNT)
            attempt += 1
        for course_offset in sorted(chosen):
            course_id = first_course_id + course_offset
            year_id = year_ids[course_offset % len(year_ids)]
            enrollment_pairs.append((student_id, course_id, year_id))
            rows.append((
                student_id, course_id, year_id,
                date(2026, 6, 1) + timedelta(days=student_offset % 60),
                "enrolled",
            ))
            if len(rows) >= BATCH_SIZE:
                bulk_insert(
                    cursor, "student_courses",
                    ["student_id", "course_id", "academic_year_id", "enrolled_at", "status"],
                    rows,
                )
                rows = []
    bulk_insert(
        cursor, "student_courses",
        ["student_id", "course_id", "academic_year_id", "enrolled_at", "status"],
        rows,
    )
    print(f"  Enrollment pairs retained in memory: {len(enrollment_pairs):,}")
    return enrollment_pairs


def generate_schedules(cursor, first_schedule_id, first_course_id):
    print("\n[6/11] Creating teacher course schedules")

    def rows():
        for i in range(COURSE_COUNT):
            start_hour = 8 + (i % 7)
            yield (
                first_schedule_id + i,
                first_course_id + i,
                i % 7,
                time(start_hour, 0),
                time(start_hour + 1, 0),
                CLASS_NAMES[i % len(CLASS_NAMES)],
                ROOMS[i % len(ROOMS)],
            )

    bulk_insert(
        cursor, "teacher_course_schedules",
        ["id", "course_id", "day_of_week", "start_time", "end_time", "class_name", "room"],
        rows(),
    )


def generate_attendance(cursor, first_session_id, first_staff_id, first_course_id,
                         year_ids, enrollment_pairs, admin_user_id, admin_username):
    print("\n[7/11] Creating attendance sessions and attendance records")
    session_rows = []
    session_lookup = {}
    session_id = first_session_id

    for course_offset in range(COURSE_COUNT):
        course_id = first_course_id + course_offset
        year_id = year_ids[course_offset % len(year_ids)]
        for session_no in range(SESSIONS_PER_COURSE):
            session_date = date(2026, 7, 1) + timedelta(days=course_offset % 25 + session_no * 35)
            session_rows.append((
                session_id, course_id, year_id, session_date,
                admin_user_id, f"Synthetic lesson {session_no + 1}",
            ))
            session_lookup.setdefault(course_id, []).append(session_id)
            session_id += 1

    bulk_insert(
        cursor, "attendance_sessions",
        ["id", "course_id", "academic_year_id", "attendance_date", "recorded_by", "notes"],
        session_rows,
    )

    students_for_course = {}
    for student_id, course_id, year_id in enrollment_pairs:
        students_for_course.setdefault(course_id, []).append((student_id, year_id))

    attendance_rows = []
    for course_id, students in students_for_course.items():
        sessions = session_lookup[course_id]
        for student_id, year_id in students:
            for sess_id in sessions:
                attendance_rows.append((
                    sess_id, course_id, year_id, student_id,
                    random.choice(ATTENDANCE_STATUSES),
                    None,
                ))
                if len(attendance_rows) >= BATCH_SIZE:
                    bulk_insert(
                        cursor, "attendance_records",
                        ["session_id", "course_id", "academic_year_id", "student_id", "status", "notes"],
                        attendance_rows,
                    )
                    attendance_rows = []
    bulk_insert(
        cursor, "attendance_records",
        ["session_id", "course_id", "academic_year_id", "student_id", "status", "notes"],
        attendance_rows,
    )

    print("  Creating staff attendance")
    total_staff = TEACHER_COUNT + NON_TEACHING_STAFF_COUNT
    staff_attendance_rows = []
    start_day = date(2027, 1, 4)
    next_attendance_id = next_id(cursor, "staff_attendance")
    for staff_offset in range(total_staff):
        staff_id = first_staff_id + staff_offset
        for day_offset in range(STAFF_ATTENDANCE_DAYS):
            work_date = start_day + timedelta(days=day_offset)
            status = random.choices(
                ["present", "late", "absent", "half_day", "on_leave"],
                weights=[80, 8, 5, 4, 3],
            )[0]
            if status in ("absent", "on_leave"):
                check_in = None
                check_out = None
            else:
                check_in = time(8, random.randint(0, 35))
                check_out = time(16, random.randint(30, 59))
            staff_attendance_rows.append((
                next_attendance_id, staff_id, work_date, status,
                check_in, check_out, None, admin_username,
            ))
            next_attendance_id += 1
            if len(staff_attendance_rows) >= BATCH_SIZE:
                bulk_insert(
                    cursor, "staff_attendance",
                    ["id", "staff_id", "attendance_date", "status", "check_in",
                     "check_out", "notes", "recorded_by_username"],
                    staff_attendance_rows,
                )
                staff_attendance_rows = []
    bulk_insert(
        cursor, "staff_attendance",
        ["id", "staff_id", "attendance_date", "status", "check_in",
         "check_out", "notes", "recorded_by_username"],
        staff_attendance_rows,
    )


def generate_assessments(cursor, enrollment_pairs):
    print("\n[8/11] Creating student assessments")
    assessment_id = next_id(cursor, "student_assessments")
    rows = []
    for student_id, course_id, year_id in enrollment_pairs:
        for exam_no in range(ASSESSMENTS_PER_ENROLLMENT):
            total = Decimal("100.00")
            marks = Decimal(str(random.randint(25, 100))).quantize(Decimal("0.01"))
            rows.append((
                assessment_id, student_id, course_id, year_id,
                f"Synthetic Exam {exam_no + 1}", marks, total,
            ))
            assessment_id += 1
            if len(rows) >= BATCH_SIZE:
                bulk_insert(
                    cursor, "student_assessments",
                    ["id", "student_id", "course_id", "academic_year_id",
                     "exam_name", "marks_obtained", "total_marks"],
                    rows,
                )
                rows = []
    bulk_insert(
        cursor, "student_assessments",
        ["id", "student_id", "course_id", "academic_year_id",
         "exam_name", "marks_obtained", "total_marks"],
        rows,
    )


def generate_course_notes(cursor, first_note_id, first_course_id, first_staff_id):
    print("\n[9/11] Creating course notes metadata")
    def rows():
        for i in range(COURSE_COUNT):
            note_id = first_note_id + i
            course_id = first_course_id + i
            staff_id = first_staff_id + (i % TEACHER_COUNT)
            stored = f"synthetic_note_{note_id:010d}.pdf"
            yield (
                note_id, course_id, staff_id,
                f"Learning material {i + 1}",
                f"Synthetic notes metadata for course {course_id}. No real PDF is attached.",
                f"learning_material_{i + 1}.pdf",
                stored,
                "application/pdf",
                1024 + (i % 50000),
                0,
            )
    bulk_insert(
        cursor, "course_notes",
        ["id", "course_id", "uploaded_by", "title", "description",
         "original_filename", "stored_filename", "content_type",
         "file_size", "download_count"],
        rows(),
    )


def generate_fees(cursor, first_invoice_id, first_fee_payment_id,
                  first_student_fee_payment_id, first_student_id,
                  year_ids, admin_user_id, admin_username):
    print("\n[10/11] Creating fee types, invoices and payments")
    fee_type_names = [
        ("Tuition Fee", "Annual tuition", Decimal("30000.00")),
        ("Library Fee", "Library access", Decimal("1500.00")),
        ("Laboratory Fee", "Laboratory usage", Decimal("5000.00")),
        ("Sports Fee", "Sports activities", Decimal("2000.00")),
        ("Examination Fee", "Examination charges", Decimal("2500.00")),
    ]
    fee_type_ids = []
    for name, description, amount in fee_type_names:
        year_id = year_ids[-1]
        cursor.execute(
            "SELECT id FROM fee_types WHERE name = %s AND academic_year_id = %s",
            (name, year_id),
        )
        existing = cursor.fetchone()
        if existing:
            fee_type_ids.append(int(existing[0]))
        else:
            cursor.execute(
                """INSERT INTO fee_types
                   (name, description, amount, class_name, academic_year_id)
                   VALUES (%s, %s, %s, %s, %s)""",
                (name, description, amount, None, year_id),
            )
            fee_type_ids.append(int(cursor.lastrowid))

    invoice_rows = []
    payment_rows = []
    student_payment_rows = []
    for i in range(STUDENT_COUNT):
        student_id = first_student_id + i
        fee_type_index = i % len(fee_type_ids)
        fee_type_id = fee_type_ids[fee_type_index]
        amount = fee_type_names[fee_type_index][2]
        invoice_id = first_invoice_id + i
        transaction_ref = f"SYN-FEE-{invoice_id:012d}"
        paid_date = datetime(2026, 9, 15, 12, 0, 0)

        invoice_rows.append((
            invoice_id, student_id, fee_type_id, year_ids[-1],
            amount, date(2026, 10, 31), "paid",
        ))
        payment_rows.append((
            first_fee_payment_id + i, invoice_id, amount, paid_date,
            random.choice(PAYMENT_METHODS), transaction_ref,
            admin_user_id, "Synthetic full payment",
        ))
        student_payment_rows.append((
            first_student_fee_payment_id + i, student_id, amount,
            paid_date, random.choice(PAYMENT_METHODS),
            f"SYN-STU-FEE-{student_id:012d}", admin_username,
            "Synthetic student fee payment",
        ))

        if len(invoice_rows) >= BATCH_SIZE:
            bulk_insert(
                cursor, "fee_invoices",
                ["id", "student_id", "fee_type_id", "academic_year_id",
                 "amount", "due_date", "status"],
                invoice_rows,
            )
            bulk_insert(
                cursor, "fee_payments",
                ["id", "invoice_id", "amount", "paid_at", "payment_method",
                 "transaction_reference", "received_by", "notes"],
                payment_rows,
            )
            bulk_insert(
                cursor, "student_fee_payments",
                ["id", "student_id", "amount", "paid_at", "payment_method",
                 "transaction_reference", "received_by_username", "notes"],
                student_payment_rows,
            )
            invoice_rows, payment_rows, student_payment_rows = [], [], []

    bulk_insert(
        cursor, "fee_invoices",
        ["id", "student_id", "fee_type_id", "academic_year_id",
         "amount", "due_date", "status"],
        invoice_rows,
    )
    bulk_insert(
        cursor, "fee_payments",
        ["id", "invoice_id", "amount", "paid_at", "payment_method",
         "transaction_reference", "received_by", "notes"],
        payment_rows,
    )
    bulk_insert(
        cursor, "student_fee_payments",
        ["id", "student_id", "amount", "paid_at", "payment_method",
         "transaction_reference", "received_by_username", "notes"],
        student_payment_rows,
    )


def generate_salary_payments(cursor, first_salary_id, first_staff_id,
                             admin_user_id):
    print("\n[11/11] Creating salary payments and school events")
    pay_period = date(2027, 1, 1)

    def salary_rows():
        total_staff = TEACHER_COUNT + NON_TEACHING_STAFF_COUNT
        for i in range(total_staff):
            staff_id = first_staff_id + i
            gross = Decimal(str(random.randint(18000, 85000))).quantize(Decimal("0.01"))
            allowances = Decimal(str(random.randint(0, 5000))).quantize(Decimal("0.01"))
            deductions = (gross * Decimal("0.08")).quantize(Decimal("0.01"))
            net = gross + allowances - deductions
            yield (
                first_salary_id + i, staff_id, pay_period,
                gross, allowances, deductions, net,
                "paid", datetime(2027, 1, 31, 12, 0, 0),
                admin_user_id, "Synthetic salary record",
            )

    bulk_insert(
        cursor, "salary_payments",
        ["id", "staff_id", "pay_period", "gross_amount", "allowances",
         "deductions", "net_amount", "status", "paid_at", "processed_by", "notes"],
        salary_rows(),
    )

    event_start_id = next_id(cursor, "school_events")
    events = []
    for i in range(100):
        start = datetime(2027, 1, 1, 9, 0) + timedelta(days=i * 3)
        events.append((
            event_start_id + i,
            f"School Event {i + 1}",
            f"Synthetic description for school event {i + 1}.",
            start,
            start + timedelta(hours=2),
            admin_user_id,
        ))
    bulk_insert(
        cursor, "school_events",
        ["id", "title", "description", "starts_at", "ends_at", "created_by"],
        events,
    )


# ------------------------------- MAIN ------------------------------------

def validate_settings():
    if STUDENT_COUNT < 1 or TEACHER_COUNT < 1 or NON_TEACHING_STAFF_COUNT < 0:
        raise ValueError("Student and teacher counts must be positive; non-teaching staff cannot be negative.")
    if COURSE_COUNT < 1:
        raise ValueError("COURSE_COUNT must be at least 1.")
    if COURSES_PER_STUDENT < 1 or COURSES_PER_STUDENT > COURSE_COUNT:
        raise ValueError("COURSES_PER_STUDENT must be between 1 and COURSE_COUNT.")
    if SESSIONS_PER_COURSE < 1 or ASSESSMENTS_PER_ENROLLMENT < 0:
        raise ValueError("Sessions must be >= 1 and assessments cannot be negative.")
    if STAFF_ATTENDANCE_DAYS < 0 or BATCH_SIZE < 1:
        raise ValueError("Attendance days cannot be negative and batch size must be positive.")


def print_counts(cursor):
    print("\nDATABASE COUNTS")
    tables = [
        "users", "roles", "permissions", "user_roles", "role_permissions",
        "students", "staff", "academic_years", "courses", "student_courses",
        "staff_attendance", "teacher_course_schedules", "attendance_sessions",
        "attendance_records", "student_assessments", "course_notes",
        "school_events", "fee_types", "fee_invoices", "fee_payments",
        "student_fee_payments", "salary_payments",
    ]
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
        print(f"{table:28s} {cursor.fetchone()[0]:>12,}")


def main():
    validate_settings()
    print("Connecting to MySQL...")
    connection = mysql.connector.connect(**DB_CONFIG)
    cursor = connection.cursor()

    try:
        print("Connected to database:", DB_CONFIG["database"])

        # IDs start after existing rows; existing records are not deleted.
        first_user_id = next_id(cursor, "users")
        first_student_id = next_id(cursor, "students")
        first_staff_id = next_id(cursor, "staff")
        first_course_id = next_id(cursor, "courses")

        roles = get_or_create_roles(cursor)
        permissions = get_or_create_permissions(cursor)
        create_role_permissions(cursor, roles, permissions)
        year_ids = get_or_create_academic_years(cursor)
        connection.commit()

        global STUDENT_ROLE_ID, TEACHER_ROLE_ID, STAFF_ROLE_ID
        STUDENT_ROLE_ID = roles["STUDENT"]
        TEACHER_ROLE_ID = roles["TEACHER"]
        STAFF_ROLE_ID = roles["NON_TEACHING_STAFF"]

        admin_user_id = generate_users(cursor, first_user_id, roles["ADMIN"])
        connection.commit()

        generate_students(cursor, first_student_id, first_user_id)
        connection.commit()

        generate_staff(cursor, first_staff_id, first_user_id)
        connection.commit()

        generate_courses(cursor, first_course_id, first_staff_id, year_ids)
        connection.commit()

        enrollment_pairs = generate_enrollments(
            cursor, first_student_id, first_course_id, year_ids
        )
        connection.commit()

        generate_schedules(
            cursor, next_id(cursor, "teacher_course_schedules"), first_course_id
        )
        connection.commit()

        admin_username = "synthetic_admin"
        generate_attendance(
            cursor,
            next_id(cursor, "attendance_sessions"),
            first_staff_id,
            first_course_id,
            year_ids,
            enrollment_pairs,
            admin_user_id,
            admin_username,
        )
        connection.commit()

        generate_assessments(cursor, enrollment_pairs)
        connection.commit()

        generate_course_notes(
            cursor, next_id(cursor, "course_notes"),
            first_course_id, first_staff_id
        )
        connection.commit()

        generate_fees(
            cursor,
            next_id(cursor, "fee_invoices"),
            next_id(cursor, "fee_payments"),
            next_id(cursor, "student_fee_payments"),
            first_student_id,
            year_ids,
            admin_user_id,
            admin_username,
        )
        connection.commit()

        generate_salary_payments(
            cursor, next_id(cursor, "salary_payments"),
            first_staff_id, admin_user_id
        )
        connection.commit()

        print("\nSynthetic data generation completed successfully.")
        print_counts(cursor)

    except Exception:
        connection.rollback()
        print("\nAn error occurred in the current phase. That phase was rolled back.")
        print("Previously committed phases remain in the database.")
        raise
    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    main()
