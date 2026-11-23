USE school;

-- Merge repeated seed rows while retaining every user-role and role-permission
-- assignment. The lowest existing ID remains the canonical row for each code.
START TRANSACTION;

INSERT IGNORE INTO user_roles (user_id, role_id, assigned_at)
SELECT ur.user_id,
       (SELECT MIN(r2.id) FROM roles AS r2 WHERE r2.code = r.code),
       ur.assigned_at
FROM user_roles AS ur
JOIN roles AS r ON r.id = ur.role_id
WHERE r.id <> (SELECT MIN(r2.id) FROM roles AS r2 WHERE r2.code = r.code);

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT (SELECT MIN(r2.id) FROM roles AS r2 WHERE r2.code = r.code),
       rp.permission_id
FROM role_permissions AS rp
JOIN roles AS r ON r.id = rp.role_id
WHERE r.id <> (SELECT MIN(r2.id) FROM roles AS r2 WHERE r2.code = r.code);

DELETE ur
FROM user_roles AS ur
JOIN roles AS r ON r.id = ur.role_id
WHERE r.id <> (SELECT MIN(r2.id) FROM roles AS r2 WHERE r2.code = r.code);

DELETE rp
FROM role_permissions AS rp
JOIN roles AS r ON r.id = rp.role_id
WHERE r.id <> (SELECT MIN(r2.id) FROM roles AS r2 WHERE r2.code = r.code);

DELETE r
FROM roles AS r
JOIN roles AS canonical ON canonical.code = r.code AND canonical.id < r.id;

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT rp.role_id,
       (SELECT MIN(p2.id) FROM permissions AS p2 WHERE p2.code = p.code)
FROM role_permissions AS rp
JOIN permissions AS p ON p.id = rp.permission_id
WHERE p.id <> (SELECT MIN(p2.id) FROM permissions AS p2 WHERE p2.code = p.code);

DELETE rp
FROM role_permissions AS rp
JOIN permissions AS p ON p.id = rp.permission_id
WHERE p.id <> (SELECT MIN(p2.id) FROM permissions AS p2 WHERE p2.code = p.code);

DELETE p
FROM permissions AS p
JOIN permissions AS canonical ON canonical.code = p.code AND canonical.id < p.id;

COMMIT;

-- Preserve legacy guardian values in the canonical columns, then remove the
-- legacy columns only when no conflicting values would be lost.
SET @legacy_guardian_columns = (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'students'
      AND column_name IN ('guardian_name', 'guardian_phone')
);
SET @ddl = IF(
    @legacy_guardian_columns = 2,
    'UPDATE students
     SET parent_guardian_name = COALESCE(parent_guardian_name, guardian_name),
         parent_contact = COALESCE(parent_contact, guardian_phone)',
    'SELECT 1'
);
PREPARE schema_stmt FROM @ddl;
EXECUTE schema_stmt;
DEALLOCATE PREPARE schema_stmt;

SET @legacy_guardian_conflicts = 0;
SET @ddl = IF(
    @legacy_guardian_columns = 2,
    'SELECT COUNT(*) INTO @legacy_guardian_conflicts
     FROM students
     WHERE (guardian_name IS NOT NULL AND NOT (guardian_name <=> parent_guardian_name))
        OR (guardian_phone IS NOT NULL AND NOT (guardian_phone <=> parent_contact))',
    'SELECT 1'
);
PREPARE schema_stmt FROM @ddl;
EXECUTE schema_stmt;
DEALLOCATE PREPARE schema_stmt;

SET @ddl = IF(
    @legacy_guardian_columns = 2 AND @legacy_guardian_conflicts = 0,
    'ALTER TABLE students
     DROP COLUMN guardian_name,
     DROP COLUMN guardian_phone',
    'SELECT 1'
);
PREPARE schema_stmt FROM @ddl;
EXECUTE schema_stmt;
DEALLOCATE PREPARE schema_stmt;

SELECT IF(
    @legacy_guardian_columns = 2 AND @legacy_guardian_conflicts > 0,
    'Legacy guardian columns retained: conflicting values require review.',
    'Legacy guardian columns aligned.'
) AS guardian_migration_status;

ALTER TABLE students
    MODIFY COLUMN class_name VARCHAR(80) NOT NULL DEFAULT 'Unassigned',
    MODIFY COLUMN fee_amount DECIMAL(12, 2) NOT NULL DEFAULT 0;

ALTER TABLE staff
    MODIFY COLUMN base_salary DECIMAL(12, 2) NOT NULL DEFAULT 0;

ALTER TABLE fee_payments
    MODIFY COLUMN received_by BIGINT UNSIGNED NULL;

ALTER TABLE school_events
    MODIFY COLUMN created_by BIGINT UNSIGNED NULL;

-- The canonical key is (name, academic_year_id); older databases may have a
-- unique index on name alone.
SET @fee_type_index_columns = (
    SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX SEPARATOR ',')
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'fee_types'
      AND index_name = 'uq_fee_types_name'
);
SET @fee_type_index_is_correct = (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'fee_types'
      AND index_name = 'uq_fee_types_name'
      AND non_unique = 0
);
SET @ddl = IF(
    @fee_type_index_columns = 'name,academic_year_id' AND @fee_type_index_is_correct = 2,
    'SELECT 1',
    IF(
        @fee_type_index_columns IS NULL,
        'ALTER TABLE fee_types ADD UNIQUE KEY uq_fee_types_name (name, academic_year_id)',
        'ALTER TABLE fee_types DROP INDEX uq_fee_types_name,
         ADD UNIQUE KEY uq_fee_types_name (name, academic_year_id)'
    )
);
PREPARE schema_stmt FROM @ddl;
EXECUTE schema_stmt;
DEALLOCATE PREPARE schema_stmt;

SET @index_exists = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'academic_years'
      AND index_name = 'uq_academic_years_name'
);
SET @ddl = IF(@index_exists = 0,
    'ALTER TABLE academic_years ADD UNIQUE KEY uq_academic_years_name (name)',
    'SELECT 1');
PREPARE schema_stmt FROM @ddl; EXECUTE schema_stmt; DEALLOCATE PREPARE schema_stmt;

SET @index_exists = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'roles'
      AND index_name = 'uq_roles_code'
);
SET @ddl = IF(@index_exists = 0,
    'ALTER TABLE roles ADD UNIQUE KEY uq_roles_code (code)',
    'SELECT 1');
PREPARE schema_stmt FROM @ddl; EXECUTE schema_stmt; DEALLOCATE PREPARE schema_stmt;

SET @index_exists = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'permissions'
      AND index_name = 'uq_permissions_code'
);
SET @ddl = IF(@index_exists = 0,
    'ALTER TABLE permissions ADD UNIQUE KEY uq_permissions_code (code)',
    'SELECT 1');
PREPARE schema_stmt FROM @ddl; EXECUTE schema_stmt; DEALLOCATE PREPARE schema_stmt;

SET @index_exists = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'students'
      AND index_name = 'uq_students_user_id'
);
SET @ddl = IF(@index_exists = 0,
    'ALTER TABLE students ADD UNIQUE KEY uq_students_user_id (user_id)',
    'SELECT 1');
PREPARE schema_stmt FROM @ddl; EXECUTE schema_stmt; DEALLOCATE PREPARE schema_stmt;

SET @index_exists = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'students'
      AND index_name = 'uq_students_admission_number'
);
SET @ddl = IF(@index_exists = 0,
    'ALTER TABLE students ADD UNIQUE KEY uq_students_admission_number (admission_number)',
    'SELECT 1');
PREPARE schema_stmt FROM @ddl; EXECUTE schema_stmt; DEALLOCATE PREPARE schema_stmt;

SET @index_exists = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'staff'
      AND index_name = 'uq_staff_user_id'
);
SET @ddl = IF(@index_exists = 0,
    'ALTER TABLE staff ADD UNIQUE KEY uq_staff_user_id (user_id)',
    'SELECT 1');
PREPARE schema_stmt FROM @ddl; EXECUTE schema_stmt; DEALLOCATE PREPARE schema_stmt;

SET @index_exists = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'staff'
      AND index_name = 'uq_staff_employee_number'
);
SET @ddl = IF(@index_exists = 0,
    'ALTER TABLE staff ADD UNIQUE KEY uq_staff_employee_number (employee_number)',
    'SELECT 1');
PREPARE schema_stmt FROM @ddl; EXECUTE schema_stmt; DEALLOCATE PREPARE schema_stmt;

SET @constraint_exists = (
    SELECT COUNT(*) FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE() AND table_name = 'students'
      AND constraint_name = 'fk_students_user'
);
SET @ddl = IF(@constraint_exists = 0,
    'ALTER TABLE students ADD CONSTRAINT fk_students_user
     FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE',
    'SELECT 1');
PREPARE schema_stmt FROM @ddl; EXECUTE schema_stmt; DEALLOCATE PREPARE schema_stmt;

SET @constraint_exists = (
    SELECT COUNT(*) FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE() AND table_name = 'staff'
      AND constraint_name = 'fk_staff_user'
);
SET @ddl = IF(@constraint_exists = 0,
    'ALTER TABLE staff ADD CONSTRAINT fk_staff_user
     FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE',
    'SELECT 1');
PREPARE schema_stmt FROM @ddl; EXECUTE schema_stmt; DEALLOCATE PREPARE schema_stmt;

SET @constraint_exists = (
    SELECT COUNT(*) FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE() AND table_name = 'courses'
      AND constraint_name = 'fk_courses_teacher'
);
SET @ddl = IF(@constraint_exists = 0,
    'ALTER TABLE courses ADD CONSTRAINT fk_courses_teacher
     FOREIGN KEY (teacher_id) REFERENCES staff (id) ON DELETE SET NULL',
    'SELECT 1');
PREPARE schema_stmt FROM @ddl; EXECUTE schema_stmt; DEALLOCATE PREPARE schema_stmt;

SET @constraint_exists = (
    SELECT COUNT(*) FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE() AND table_name = 'student_courses'
      AND constraint_name = 'fk_student_courses_student'
);
SET @ddl = IF(@constraint_exists = 0,
    'ALTER TABLE student_courses ADD CONSTRAINT fk_student_courses_student
     FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE RESTRICT',
    'SELECT 1');
PREPARE schema_stmt FROM @ddl; EXECUTE schema_stmt; DEALLOCATE PREPARE schema_stmt;

SET @constraint_exists = (
    SELECT COUNT(*) FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE() AND table_name = 'student_courses'
      AND constraint_name = 'fk_student_courses_course'
);
SET @ddl = IF(@constraint_exists = 0,
    'ALTER TABLE student_courses ADD CONSTRAINT fk_student_courses_course
     FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE RESTRICT',
    'SELECT 1');
PREPARE schema_stmt FROM @ddl; EXECUTE schema_stmt; DEALLOCATE PREPARE schema_stmt;

SET @constraint_exists = (
    SELECT COUNT(*) FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE() AND table_name = 'students'
      AND constraint_name = 'chk_students_fee_amount'
);
SET @ddl = IF(@constraint_exists = 0,
    'ALTER TABLE students ADD CONSTRAINT chk_students_fee_amount CHECK (fee_amount >= 0)',
    'SELECT 1');
PREPARE schema_stmt FROM @ddl; EXECUTE schema_stmt; DEALLOCATE PREPARE schema_stmt;

SET @constraint_exists = (
    SELECT COUNT(*) FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE() AND table_name = 'staff'
      AND constraint_name = 'chk_staff_base_salary'
);
SET @ddl = IF(@constraint_exists = 0,
    'ALTER TABLE staff ADD CONSTRAINT chk_staff_base_salary CHECK (base_salary >= 0)',
    'SELECT 1');
PREPARE schema_stmt FROM @ddl; EXECUTE schema_stmt; DEALLOCATE PREPARE schema_stmt;
