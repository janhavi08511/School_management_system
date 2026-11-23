

CREATE DATABASE IF NOT EXISTS school;
USE school;

-- For existing installations, also apply migrations/2026-11-16_align_schema.sql
-- after this bootstrap script.

CREATE TABLE if Not Exists roles (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    code VARCHAR(40) NOT NULL,
    name VARCHAR(80) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_roles_code (code)
);

CREATE TABLE if Not Exists permissions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    code VARCHAR(80) NOT NULL,
    description VARCHAR(255) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_permissions_code (code)
);

CREATE TABLE if Not Exists role_permissions (
    role_id BIGINT UNSIGNED NOT NULL,
    permission_id BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (role_id, permission_id),
    CONSTRAINT fk_role_permissions_role
        FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE CASCADE,
    CONSTRAINT fk_role_permissions_permission
        FOREIGN KEY (permission_id) REFERENCES permissions (id) ON DELETE CASCADE
);

CREATE TABLE if Not Exists users (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    username VARCHAR(80) NOT NULL,
    email VARCHAR(254) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    phone VARCHAR(30) NULL,
    profile_photo_path VARCHAR(255) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_username (username),
    KEY ix_users_first_name (first_name),
    KEY ix_users_last_name (last_name)
);

CREATE TABLE if Not Exists user_roles (
    user_id BIGINT UNSIGNED NOT NULL,
    role_id BIGINT UNSIGNED NOT NULL,
    assigned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role_id),
    CONSTRAINT fk_user_roles_user
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_user_roles_role
        FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE if Not Exists academic_years (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    name VARCHAR(30) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (id),
    UNIQUE KEY uq_academic_years_name (name)
);

CREATE TABLE if Not Exists students (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    admission_number VARCHAR(40) NOT NULL,
    date_of_birth DATE NULL,
    gender VARCHAR(30) NULL,
    admission_date DATE NOT NULL,
    address VARCHAR(500) NULL,
    parent_guardian_name VARCHAR(160) NULL,
    parent_contact VARCHAR(30) NULL,
    status ENUM('active', 'inactive', 'graduated', 'withdrawn') NOT NULL DEFAULT 'active',
    class_name VARCHAR(80) NOT NULL DEFAULT 'Unassigned',
    fee_amount DECIMAL(12, 2) NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_students_user_id (user_id),
    UNIQUE KEY uq_students_admission_number (admission_number),
    KEY ix_students_class_name (class_name),
    CONSTRAINT fk_students_user
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT chk_students_fee_amount CHECK (fee_amount >= 0)
);

CREATE TABLE if Not Exists staff (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    employee_number VARCHAR(40) NOT NULL,
    staff_type ENUM('teacher', 'non_teaching') NOT NULL,
    designation VARCHAR(120) NOT NULL,
    hire_date DATE NOT NULL,
    education VARCHAR(500) NULL,
    experience_years DECIMAL(4, 1) NOT NULL DEFAULT 0,
    department VARCHAR(120) NULL,
    address VARCHAR(500) NULL,
    base_salary DECIMAL(12, 2) NOT NULL DEFAULT 0,
    shift VARCHAR(80) NULL,
    status ENUM('active', 'inactive', 'on_leave', 'terminated') NOT NULL DEFAULT 'active',
    PRIMARY KEY (id),
    UNIQUE KEY uq_staff_user_id (user_id),
    UNIQUE KEY uq_staff_employee_number (employee_number),
    CONSTRAINT fk_staff_user
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT chk_staff_base_salary CHECK (base_salary >= 0)
);

CREATE TABLE if Not Exists staff_attendance (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    staff_id BIGINT UNSIGNED NOT NULL,
    attendance_date DATE NOT NULL,
    status ENUM('present', 'absent', 'late', 'half_day', 'on_leave') NOT NULL,
    check_in TIME NULL,
    check_out TIME NULL,
    notes VARCHAR(500) NULL,
    recorded_by_username VARCHAR(80) NOT NULL,
    recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_staff_attendance_staff_date (staff_id, attendance_date),
    KEY ix_staff_attendance_date_status (attendance_date, status),
    CONSTRAINT fk_staff_attendance_staff
        FOREIGN KEY (staff_id) REFERENCES staff (id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE if Not Exists courses (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    course_code VARCHAR(40) NOT NULL,
    name VARCHAR(150) NOT NULL,
    description TEXT NULL,
    class_name VARCHAR(80) NULL,
    duration_months SMALLINT UNSIGNED NULL,
    academic_year_id BIGINT UNSIGNED NULL,
    teacher_id BIGINT UNSIGNED NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_courses_code (course_code),
    CONSTRAINT fk_courses_academic_year
        FOREIGN KEY (academic_year_id) REFERENCES academic_years (id) ON DELETE SET NULL,
    CONSTRAINT fk_courses_teacher
        FOREIGN KEY (teacher_id) REFERENCES staff (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS course_notes (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    course_id BIGINT UNSIGNED NOT NULL,
    uploaded_by BIGINT UNSIGNED NOT NULL,
    title VARCHAR(150) NOT NULL,
    description TEXT NULL,
    original_filename VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(80) NOT NULL,
    content_type VARCHAR(120) NOT NULL,
    file_size BIGINT UNSIGNED NOT NULL,
    download_count INT UNSIGNED NOT NULL DEFAULT 0,
    uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_course_notes_stored_filename (stored_filename),
    KEY ix_course_notes_course_uploaded_at (course_id, uploaded_at),
    CONSTRAINT fk_course_notes_course
        FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE RESTRICT,
    CONSTRAINT fk_course_notes_uploader
        FOREIGN KEY (uploaded_by) REFERENCES staff (id) ON DELETE RESTRICT,
    CONSTRAINT chk_course_notes_file_size CHECK (file_size > 0)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS teacher_course_schedules (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    course_id BIGINT UNSIGNED NOT NULL,
    day_of_week TINYINT UNSIGNED NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    class_name VARCHAR(80) NULL,
    room VARCHAR(80) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_teacher_course_schedule_day_start
        (course_id, day_of_week, start_time),
    KEY ix_teacher_course_schedule_day_time (day_of_week, start_time),
    CONSTRAINT fk_teacher_course_schedule_course
        FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE CASCADE,
    CONSTRAINT chk_teacher_course_schedule_day CHECK (day_of_week <= 6),
    CONSTRAINT chk_teacher_course_schedule_time CHECK (end_time > start_time)
) ENGINE=InnoDB;

CREATE TABLE if Not Exists student_courses (
    student_id BIGINT UNSIGNED NOT NULL,
    course_id BIGINT UNSIGNED NOT NULL,
    academic_year_id BIGINT UNSIGNED NOT NULL,
    enrolled_at DATE NOT NULL,
    status ENUM('enrolled', 'completed', 'withdrawn') NOT NULL DEFAULT 'enrolled',
    PRIMARY KEY (student_id, course_id, academic_year_id),
    KEY ix_student_courses_course (course_id, academic_year_id),
    CONSTRAINT fk_student_courses_student
        FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE RESTRICT,
    CONSTRAINT fk_student_courses_course
        FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE RESTRICT,
    CONSTRAINT fk_student_courses_academic_year
        FOREIGN KEY (academic_year_id) REFERENCES academic_years (id) ON DELETE RESTRICT
) ENGINE=InnoDB;

INSERT INTO academic_years (name, start_date, end_date, is_current)
SELECT '2026-2027', '2026-07-01', '2027-06-30', TRUE
WHERE NOT EXISTS (
    SELECT 1 FROM academic_years WHERE name = '2026-2027'
);

INSERT INTO courses (course_code, name, description)
SELECT 'MATH-101', 'Mathematics', 'Dummy mathematics course for testing'
WHERE NOT EXISTS (
    SELECT 1 FROM courses WHERE course_code = 'MATH-101'
);

INSERT INTO courses (course_code, name, description)
SELECT 'ENG-101', 'English', 'Dummy English course for testing'
WHERE NOT EXISTS (
    SELECT 1 FROM courses WHERE course_code = 'ENG-101'
);

INSERT INTO courses (course_code, name, description)
SELECT 'SCI-101', 'Science', 'Dummy science course for testing'
WHERE NOT EXISTS (
    SELECT 1 FROM courses WHERE course_code = 'SCI-101'
);

CREATE TABLE if Not Exists attendance_sessions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    course_id BIGINT UNSIGNED NOT NULL,
    academic_year_id BIGINT UNSIGNED NOT NULL,
    attendance_date DATE NOT NULL,
    recorded_by BIGINT UNSIGNED NOT NULL,
    notes VARCHAR(500) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_attendance_session_course_year (id, course_id, academic_year_id),
    UNIQUE KEY uq_attendance_course_date (course_id, academic_year_id, attendance_date),
    CONSTRAINT fk_attendance_sessions_course
        FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE RESTRICT,
    CONSTRAINT fk_attendance_sessions_academic_year
        FOREIGN KEY (academic_year_id) REFERENCES academic_years (id) ON DELETE RESTRICT,
    CONSTRAINT fk_attendance_sessions_recorder
        FOREIGN KEY (recorded_by) REFERENCES users (id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE if Not Exists attendance_records (
    session_id BIGINT UNSIGNED NOT NULL,
    course_id BIGINT UNSIGNED NOT NULL,
    academic_year_id BIGINT UNSIGNED NOT NULL,
    student_id BIGINT UNSIGNED NOT NULL,
    status ENUM('present', 'absent', 'late', 'excused') NOT NULL,
    notes VARCHAR(500) NULL,
    PRIMARY KEY (session_id, student_id),
    KEY ix_attendance_student (student_id, session_id),
    CONSTRAINT fk_attendance_records_session
        FOREIGN KEY (session_id, course_id, academic_year_id)
        REFERENCES attendance_sessions (id, course_id, academic_year_id) ON DELETE CASCADE,
    CONSTRAINT fk_attendance_records_enrollment
        FOREIGN KEY (student_id, course_id, academic_year_id)
        REFERENCES student_courses (student_id, course_id, academic_year_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE  if Not Exists fee_types (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(255) NULL,
    amount DECIMAL(12, 2) NOT NULL DEFAULT 0,
    class_name VARCHAR(80) NULL,
    academic_year_id BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_fee_types_name (name, academic_year_id),
    CONSTRAINT fk_fee_types_academic_year
        FOREIGN KEY (academic_year_id) REFERENCES academic_years (id) ON DELETE SET NULL,
    CONSTRAINT chk_fee_type_amount CHECK (amount >= 0)
) ENGINE=InnoDB;

CREATE TABLE  if Not Exists fee_invoices (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    student_id BIGINT UNSIGNED NOT NULL,
    fee_type_id BIGINT UNSIGNED NOT NULL,
    academic_year_id BIGINT UNSIGNED NOT NULL,
    amount DECIMAL(12, 2) NOT NULL,
    due_date DATE NOT NULL,
    status ENUM('unpaid', 'partially_paid', 'paid', 'waived') NOT NULL DEFAULT 'unpaid',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_fee_invoices_student_status (student_id, status),
    KEY ix_fee_invoices_due_date (due_date),
    CONSTRAINT fk_fee_invoices_student
        FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE RESTRICT,
    CONSTRAINT fk_fee_invoices_type
        FOREIGN KEY (fee_type_id) REFERENCES fee_types (id) ON DELETE RESTRICT,
    CONSTRAINT fk_fee_invoices_academic_year
        FOREIGN KEY (academic_year_id) REFERENCES academic_years (id) ON DELETE RESTRICT,
    CONSTRAINT chk_fee_invoice_amount CHECK (amount >= 0)
) ENGINE=InnoDB;

CREATE TABLE  if Not Exists fee_payments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    invoice_id BIGINT UNSIGNED NOT NULL,
    amount DECIMAL(12, 2) NOT NULL,
    paid_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    payment_method ENUM('cash', 'card', 'bank_transfer', 'online', 'other') NOT NULL,
    transaction_reference VARCHAR(120) NULL,
    received_by BIGINT UNSIGNED NULL,
    notes VARCHAR(500) NULL,
    PRIMARY KEY (id),
    KEY ix_fee_payments_invoice (invoice_id, paid_at),
    UNIQUE KEY uq_fee_payments_transaction_reference (transaction_reference),
    CONSTRAINT fk_fee_payments_invoice
        FOREIGN KEY (invoice_id) REFERENCES fee_invoices (id) ON DELETE RESTRICT,
    CONSTRAINT fk_fee_payments_receiver
        FOREIGN KEY (received_by) REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT chk_fee_payment_amount CHECK (amount > 0)
) ENGINE=InnoDB;

CREATE TABLE if Not Exists student_fee_payments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    student_id BIGINT UNSIGNED NOT NULL,
    amount DECIMAL(12, 2) NOT NULL,
    paid_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    payment_method ENUM('cash', 'card', 'bank_transfer', 'online', 'other') NOT NULL,
    transaction_reference VARCHAR(120) NULL,
    received_by_username VARCHAR(80) NOT NULL,
    notes VARCHAR(500) NULL,
    PRIMARY KEY (id),
    KEY ix_student_fee_payments_student_paid_at (student_id, paid_at),
    UNIQUE KEY uq_student_fee_payments_transaction_reference (transaction_reference),
    CONSTRAINT fk_student_fee_payments_student
        FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE RESTRICT,
    CONSTRAINT chk_student_fee_payment_amount CHECK (amount > 0)
) ENGINE=InnoDB;

CREATE TABLE if Not Exists salary_payments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    staff_id BIGINT UNSIGNED NOT NULL,
    pay_period DATE NOT NULL,
    gross_amount DECIMAL(12, 2) NOT NULL,
    allowances DECIMAL(12, 2) NOT NULL DEFAULT 0,
    deductions DECIMAL(12, 2) NOT NULL DEFAULT 0,
    net_amount DECIMAL(12, 2) NOT NULL,
    status ENUM('pending', 'paid', 'cancelled') NOT NULL DEFAULT 'pending',
    paid_at TIMESTAMP NULL,
    processed_by BIGINT UNSIGNED NULL,
    notes VARCHAR(500) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_salary_staff_period (staff_id, pay_period),
    KEY ix_salary_period_status (pay_period, status),
    CONSTRAINT fk_salary_payments_staff
        FOREIGN KEY (staff_id) REFERENCES staff (id) ON DELETE RESTRICT,
    CONSTRAINT fk_salary_payments_processor
        FOREIGN KEY (processed_by) REFERENCES users (id) ON DELETE SET NULL,
    CONSTRAINT chk_salary_gross_amount CHECK (gross_amount >= 0),
    CONSTRAINT chk_salary_allowances CHECK (allowances >= 0),
    CONSTRAINT chk_salary_deductions CHECK (deductions >= 0),
    CONSTRAINT chk_salary_net_amount CHECK (net_amount >= 0),
    CONSTRAINT chk_salary_amounts
        CHECK (net_amount = gross_amount + allowances - deductions)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS student_assessments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    student_id BIGINT UNSIGNED NOT NULL,
    course_id BIGINT UNSIGNED NOT NULL,
    academic_year_id BIGINT UNSIGNED NOT NULL,
    exam_name VARCHAR(150) NOT NULL,
    marks_obtained DECIMAL(7, 2) NOT NULL,
    total_marks DECIMAL(7, 2) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_student_assessment (student_id, course_id, academic_year_id, exam_name),
    KEY ix_assessment_course_exam (course_id, academic_year_id, exam_name),
    CONSTRAINT fk_assessment_enrollment
        FOREIGN KEY (student_id, course_id, academic_year_id)
        REFERENCES student_courses (student_id, course_id, academic_year_id) ON DELETE RESTRICT,
    CONSTRAINT chk_assessment_marks CHECK (
        marks_obtained >= 0 AND total_marks > 0 AND marks_obtained <= total_marks
    )
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS school_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    title VARCHAR(150) NOT NULL,
    description VARCHAR(2000) NULL,
    starts_at DATETIME NOT NULL,
    ends_at DATETIME NULL,
    created_by BIGINT UNSIGNED NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_school_events_starts_at (starts_at),
    CONSTRAINT fk_school_events_creator
        FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT chk_school_event_dates CHECK (ends_at IS NULL OR ends_at >= starts_at)
) ENGINE=InnoDB;

INSERT INTO roles (code, name)
VALUES
    ('admin', 'Administrator'),
    ('student', 'Student'),
    ('teacher', 'Teacher'),
    ('non_teaching_staff', 'Non-teaching Staff')
ON DUPLICATE KEY UPDATE name = VALUES(name);

INSERT INTO permissions (code, description)
VALUES
    ('users.manage', 'Create, update, and deactivate user accounts'),
    ('roles.manage', 'Manage roles and role permissions'),
    ('students.manage', 'Manage student records'),
    ('students.view_assigned', 'View students enrolled in assigned courses'),
    ('staff.manage', 'Manage staff records'),
    ('courses.manage', 'Create and update courses and course assignments'),
    ('courses.view', 'View course information'),
    ('courses.view_assigned', 'View assigned courses'),
    ('enrollments.manage', 'Enroll students in courses'),
    ('attendance.manage', 'Record and update attendance'),
    ('attendance.manage_assigned', 'Record attendance for assigned courses'),
    ('attendance.view_self', 'View own attendance records'),
    ('fees.manage', 'Manage fee invoices and payments'),
    ('fees.view_self', 'View own fee invoices and payments'),
    ('salary.manage', 'Manage staff salary payments'),
    ('salary.view_self', 'View own salary payment records'),
    ('reports.view', 'View administrative reports')
ON DUPLICATE KEY UPDATE description = VALUES(description);

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles AS r
CROSS JOIN permissions AS p
WHERE r.code = 'admin'
ON DUPLICATE KEY UPDATE permission_id = VALUES(permission_id);

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles AS r
JOIN permissions AS p
    ON p.code IN (
        'courses.view',
        'attendance.view_self',
        'fees.view_self'
    )
WHERE r.code = 'student'
ON DUPLICATE KEY UPDATE permission_id = VALUES(permission_id);

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles AS r
JOIN permissions AS p
    ON p.code IN (
        'courses.view_assigned',
        'students.view_assigned',
        'attendance.manage_assigned',
        'salary.view_self'
    )
WHERE r.code = 'teacher'
ON DUPLICATE KEY UPDATE permission_id = VALUES(permission_id);

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles AS r
JOIN permissions AS p
    ON p.code IN (
        'courses.view',
        'fees.manage',
        'salary.view_self'
    )
WHERE r.code = 'non_teaching_staff'
ON DUPLICATE KEY UPDATE permission_id = VALUES(permission_id);

USE school;

SET @course_code_index_exists = (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'courses'
      AND index_name = 'uq_courses_code'
);
SET @course_code_index_ddl = IF(
    @course_code_index_exists = 0,
    'ALTER TABLE courses ADD UNIQUE KEY uq_courses_code (course_code)',
    'SELECT 1'
);
PREPARE course_code_index_stmt FROM @course_code_index_ddl;
EXECUTE course_code_index_stmt;
DEALLOCATE PREPARE course_code_index_stmt;

CREATE TABLE IF NOT EXISTS student_fee_payments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    student_id BIGINT UNSIGNED NOT NULL,
    amount DECIMAL(12, 2) NOT NULL,
    paid_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    payment_method ENUM('cash', 'card', 'bank_transfer', 'online', 'other') NOT NULL,
    transaction_reference VARCHAR(120) NULL,
    received_by_username VARCHAR(80) NOT NULL,
    notes VARCHAR(500) NULL,
    PRIMARY KEY (id),
    KEY ix_student_fee_payments_student_paid_at (student_id, paid_at),
    UNIQUE KEY uq_student_fee_payments_transaction_reference (transaction_reference),
    CONSTRAINT fk_student_fee_payments_student
        FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE RESTRICT,
    CONSTRAINT chk_student_fee_payment_amount CHECK (amount > 0)
) ENGINE=InnoDB;

USE school;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'users'
      AND column_name = 'profile_photo_path'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE users ADD COLUMN profile_photo_path VARCHAR(255) NULL AFTER phone',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'students'
      AND column_name = 'gender'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE students ADD COLUMN gender VARCHAR(30) NULL AFTER date_of_birth',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'students'
      AND column_name = 'parent_guardian_name'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE students ADD COLUMN parent_guardian_name VARCHAR(160) NULL AFTER address',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'students'
      AND column_name = 'parent_contact'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE students ADD COLUMN parent_contact VARCHAR(30) NULL AFTER parent_guardian_name',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'staff'
      AND column_name = 'experience_years'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE staff ADD COLUMN experience_years DECIMAL(4,1) NOT NULL DEFAULT 0 AFTER education',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'staff'
      AND column_name = 'department'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE staff ADD COLUMN department VARCHAR(120) NULL AFTER experience_years',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'staff'
      AND column_name = 'address'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE staff ADD COLUMN address VARCHAR(500) NULL AFTER department',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'courses'
      AND column_name = 'class_name'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE courses ADD COLUMN class_name VARCHAR(80) NULL AFTER description',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'courses'
      AND column_name = 'duration_months'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE courses ADD COLUMN duration_months SMALLINT UNSIGNED NULL AFTER class_name',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'courses'
      AND column_name = 'academic_year_id'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE courses ADD COLUMN academic_year_id BIGINT UNSIGNED NULL AFTER duration_months',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @constraint_exists = (
    SELECT COUNT(*) FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE() AND table_name = 'courses'
      AND constraint_name = 'fk_courses_academic_year'
);
SET @ddl = IF(@constraint_exists = 0,
    'ALTER TABLE courses ADD CONSTRAINT fk_courses_academic_year FOREIGN KEY (academic_year_id) REFERENCES academic_years (id) ON DELETE SET NULL',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'fee_types'
      AND column_name = 'amount'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE fee_types ADD COLUMN amount DECIMAL(12,2) NOT NULL DEFAULT 0 AFTER description',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'fee_types'
      AND column_name = 'class_name'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE fee_types ADD COLUMN class_name VARCHAR(80) NULL AFTER amount',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'fee_types'
      AND column_name = 'academic_year_id'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE fee_types ADD COLUMN academic_year_id BIGINT UNSIGNED NULL AFTER class_name',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @index_exists = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'users'
      AND index_name = 'ix_users_first_name'
);
SET @ddl = IF(@index_exists = 0,
    'CREATE INDEX ix_users_first_name ON users (first_name)',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @index_exists = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'users'
      AND index_name = 'ix_users_last_name'
);
SET @ddl = IF(@index_exists = 0,
    'CREATE INDEX ix_users_last_name ON users (last_name)',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @index_exists = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'students'
      AND index_name = 'ix_students_class_name'
);
SET @ddl = IF(@index_exists = 0,
    'CREATE INDEX ix_students_class_name ON students (class_name)',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'salary_payments'
      AND column_name = 'allowances'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE salary_payments ADD COLUMN allowances DECIMAL(12,2) NOT NULL DEFAULT 0 AFTER gross_amount',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

ALTER TABLE fee_payments
    MODIFY COLUMN received_by BIGINT UNSIGNED NULL;

ALTER TABLE school_events
    MODIFY COLUMN created_by BIGINT UNSIGNED NULL;

    SET @constraint_exists = (
        SELECT COUNT(*) FROM information_schema.table_constraints
        WHERE constraint_schema = DATABASE() AND table_name = 'fee_types'
          AND constraint_name = 'fk_fee_types_academic_year'
    );
    SET @ddl = IF(@constraint_exists = 0,
        'ALTER TABLE fee_types ADD CONSTRAINT fk_fee_types_academic_year FOREIGN KEY (academic_year_id) REFERENCES academic_years (id) ON DELETE SET NULL',
        'SELECT 1');
    PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

    SET @constraint_exists = (
        SELECT COUNT(*) FROM information_schema.table_constraints
        WHERE constraint_schema = DATABASE() AND table_name = 'salary_payments'
          AND constraint_name = 'chk_salary_allowances'
    );
    SET @ddl = IF(@constraint_exists = 0,
        'ALTER TABLE salary_payments ADD CONSTRAINT chk_salary_allowances CHECK (allowances >= 0)',
        'SELECT 1');
    PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(
    (SELECT COUNT(*) FROM information_schema.table_constraints
     WHERE constraint_schema = DATABASE() AND table_name = 'salary_payments'
       AND constraint_name = 'chk_salary_amounts') > 0,
    'ALTER TABLE salary_payments DROP CHECK chk_salary_amounts, ADD CONSTRAINT chk_salary_amounts CHECK (net_amount = gross_amount + allowances - deductions)',
    'ALTER TABLE salary_payments ADD CONSTRAINT chk_salary_amounts CHECK (net_amount = gross_amount + allowances - deductions)'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

ALTER TABLE staff_attendance
    MODIFY COLUMN status ENUM('present', 'absent', 'late', 'half_day', 'on_leave') NOT NULL;

CREATE TABLE IF NOT EXISTS student_assessments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    student_id BIGINT UNSIGNED NOT NULL,
    course_id BIGINT UNSIGNED NOT NULL,
    academic_year_id BIGINT UNSIGNED NOT NULL,
    exam_name VARCHAR(150) NOT NULL,
    marks_obtained DECIMAL(7, 2) NOT NULL,
    total_marks DECIMAL(7, 2) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_student_assessment (student_id, course_id, academic_year_id, exam_name),
    KEY ix_assessment_course_exam (course_id, academic_year_id, exam_name),
    CONSTRAINT fk_assessment_enrollment
        FOREIGN KEY (student_id, course_id, academic_year_id)
        REFERENCES student_courses (student_id, course_id, academic_year_id) ON DELETE RESTRICT,
    CONSTRAINT chk_assessment_marks CHECK (
        marks_obtained >= 0 AND total_marks > 0 AND marks_obtained <= total_marks
    )
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS school_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    title VARCHAR(150) NOT NULL,
    description VARCHAR(2000) NULL,
    starts_at DATETIME NOT NULL,
    ends_at DATETIME NULL,
    created_by BIGINT UNSIGNED NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_school_events_starts_at (starts_at),
    CONSTRAINT fk_school_events_creator
        FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT chk_school_event_dates CHECK (ends_at IS NULL OR ends_at >= starts_at)
) ENGINE=InnoDB;
USE school;

CREATE TABLE IF NOT EXISTS staff_attendance (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    staff_id BIGINT UNSIGNED NOT NULL,
    attendance_date DATE NOT NULL,
    status ENUM('present', 'absent', 'late', 'on_leave') NOT NULL,
    check_in TIME NULL,
    check_out TIME NULL,
    notes VARCHAR(500) NULL,
    recorded_by_username VARCHAR(80) NOT NULL,
    recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_staff_attendance_staff_date (staff_id, attendance_date),
    KEY ix_staff_attendance_date_status (attendance_date, status),
    CONSTRAINT fk_staff_attendance_staff
        FOREIGN KEY (staff_id) REFERENCES staff (id) ON DELETE RESTRICT
) ENGINE=InnoDB;


USE school;

SET @course_notes_description_exists = (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'course_notes'
      AND column_name = 'description'
);
SET @course_notes_description_ddl = IF(
    @course_notes_description_exists = 0,
    'ALTER TABLE course_notes ADD COLUMN description TEXT NULL AFTER title',
    'SELECT 1'
);
PREPARE course_notes_description_stmt FROM @course_notes_description_ddl;
EXECUTE course_notes_description_stmt;
DEALLOCATE PREPARE course_notes_description_stmt;

SET @course_notes_download_count_exists = (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'course_notes'
      AND column_name = 'download_count'
);
SET @course_notes_download_count_ddl = IF(
    @course_notes_download_count_exists = 0,
    'ALTER TABLE course_notes ADD COLUMN download_count INT UNSIGNED NOT NULL DEFAULT 0 AFTER file_size',
    'SELECT 1'
);
PREPARE course_notes_download_count_stmt FROM @course_notes_download_count_ddl;
EXECUTE course_notes_download_count_stmt;
DEALLOCATE PREPARE course_notes_download_count_stmt;

CREATE TABLE IF NOT EXISTS teacher_course_schedules (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    course_id BIGINT UNSIGNED NOT NULL,
    day_of_week TINYINT UNSIGNED NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    class_name VARCHAR(80) NULL,
    room VARCHAR(80) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_teacher_course_schedule_day_start
        (course_id, day_of_week, start_time),
    KEY ix_teacher_course_schedule_day_time (day_of_week, start_time),
    CONSTRAINT fk_teacher_course_schedule_course
        FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE CASCADE,
    CONSTRAINT chk_teacher_course_schedule_day CHECK (day_of_week <= 6),
    CONSTRAINT chk_teacher_course_schedule_time CHECK (end_time > start_time)
) ENGINE=InnoDB;

USE school;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'students'
      AND column_name = 'class_name'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE students ADD COLUMN class_name VARCHAR(80) NOT NULL DEFAULT ''Unassigned''',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'students'
      AND column_name = 'fee_amount'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE students ADD COLUMN fee_amount DECIMAL(12,2) NOT NULL DEFAULT 0',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'staff'
      AND column_name = 'education'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE staff ADD COLUMN education VARCHAR(500) NULL',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'staff'
      AND column_name = 'base_salary'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE staff ADD COLUMN base_salary DECIMAL(12,2) NOT NULL DEFAULT 0',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'staff'
      AND column_name = 'shift'
);
SET @ddl = IF(@column_exists = 0,
    'ALTER TABLE staff ADD COLUMN shift VARCHAR(80) NULL',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

USE school;

CREATE TABLE IF NOT EXISTS course_notes (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    course_id BIGINT UNSIGNED NOT NULL,
    uploaded_by BIGINT UNSIGNED NOT NULL,
    title VARCHAR(150) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(80) NOT NULL,
    content_type VARCHAR(120) NOT NULL,
    file_size BIGINT UNSIGNED NOT NULL,
    uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_course_notes_stored_filename (stored_filename),
    KEY ix_course_notes_course_uploaded_at (course_id, uploaded_at),
    CONSTRAINT fk_course_notes_course
        FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE RESTRICT,
    CONSTRAINT fk_course_notes_uploader
        FOREIGN KEY (uploaded_by) REFERENCES staff (id) ON DELETE RESTRICT,
    CONSTRAINT chk_course_notes_file_size CHECK (file_size > 0)
) ENGINE=InnoDB;

CREATE INDEX idx_attendance_sessions_date_id
ON attendance_sessions(attendance_date, id);

CREATE INDEX idx_attendance_records_session_status
ON attendance_records(session_id, status);

CREATE INDEX idx_staff_attendance_date_status
ON staff_attendance(attendance_date, status);

CREATE INDEX idx_student_fee_payments_student
ON student_fee_payments(student_id);

CREATE INDEX idx_students_status
ON students(status);

CREATE INDEX idx_staff_type_status
ON staff(staff_type, status);

SHOW INDEX FROM staff_attendance;
SHOW INDEX FROM staff;
SHOW INDEX FROM users;
SHOW INDEX FROM courses;



CREATE INDEX idx_staff_type_status
ON staff(staff_type, status);

CREATE INDEX idx_courses_teacher
ON courses(teacher_id);