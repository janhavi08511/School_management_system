-- Optional performance indexes for the School Management System.
-- Inspect existing indexes first. Skip any equivalent index already present.
-- Run these statements individually during a maintenance window.

SHOW INDEX FROM users;
SHOW INDEX FROM student_assessments;
SHOW INDEX FROM student_fee_payments;
SHOW INDEX FROM fee_payments;
SHOW INDEX FROM salary_payments;

-- Supports ORDER BY created_at DESC, id DESC in recent-user queries.
CREATE INDEX idx_users_created_at_id
    ON users (created_at, id);

-- Supports recent assessment dashboard aggregations.
CREATE INDEX idx_assessments_created_course_student
    ON student_assessments (created_at, course_id, student_id);

-- Supports recent-payment dashboard queries and five-month fee trends.
CREATE INDEX idx_student_fee_payments_paid_at_id
    ON student_fee_payments (paid_at, id);

CREATE INDEX idx_fee_payments_paid_at_id
    ON fee_payments (paid_at, id);

-- Already present in the supplied schema; do not recreate:
-- salary_payments: ix_salary_period_status (pay_period, status)
-- student_fee_payments: ix_student_fee_payments_student_paid_at (student_id, paid_at)
-- staff: idx_staff_type_status (staff_type, status)
-- courses: idx_courses_teacher (teacher_id)
