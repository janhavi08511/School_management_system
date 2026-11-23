-- Recommended MySQL indexes for admin search and pagination.
-- Review EXPLAIN plans and existing indexes before applying in production.
-- These statements intentionally do not delete or alter existing data.

CREATE INDEX ix_users_name_search
    ON users (last_name, first_name, username);

CREATE INDEX ix_staff_search
    ON staff (status, staff_type, employee_number, designation, department);

CREATE INDEX ix_courses_search
    ON courses (teacher_id, course_code, name);

CREATE INDEX ix_student_courses_lookup
    ON student_courses (student_id, course_id, status);

CREATE INDEX ix_students_search
    ON students (status, admission_number, class_name);

CREATE INDEX ix_fee_invoices_list
    ON fee_invoices (due_date, status, student_id);

CREATE INDEX ix_fee_payments_invoice_amount
    ON fee_payments (invoice_id, amount);

CREATE INDEX ix_assessments_list
    ON student_assessments (created_at, course_id, student_id);
