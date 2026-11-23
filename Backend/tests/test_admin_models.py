import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import Admin
import pytest
from pydantic import ValidationError

@pytest.mark.case(id='ADM-MOD-001',name='Valid course create model',description='Validate valid course code, name and duration.',expected='Model instantiates; values preserved.')
def test_course_create_valid():
    m=Admin.CourseCreateRequest(course_code='cs-101',name='Computer Science',duration_months=12)
    assert m.duration_months==12

@pytest.mark.case(id='ADM-MOD-002',name='Course code too short rejected',description='Course code violates minimum length of two.',expected='Pydantic ValidationError.')
def test_course_code_short():
    with pytest.raises(ValidationError): Admin.CourseCreateRequest(course_code='A',name='Math')

@pytest.mark.case(id='ADM-MOD-003',name='Duration outside range rejected',description='Duration must be 1 through 120 months.',expected='Pydantic ValidationError.')
@pytest.mark.parametrize('duration',[0,121])
def test_duration_invalid(duration):
    with pytest.raises(ValidationError): Admin.CourseCreateRequest(course_code='MATH',name='Math',duration_months=duration)

@pytest.mark.case(id='ADM-MOD-004',name='Valid course schedule model',description='Check course id, weekday and time fields.',expected='Model instantiates and parses times.')
def test_schedule_model_valid():
    m=Admin.CourseScheduleCreateRequest(course_id=1,day_of_week=2,start_time='09:00',end_time='10:00')
    assert str(m.start_time)=='09:00:00'

@pytest.mark.case(id='ADM-MOD-005',name='Invalid weekday rejected',description='Weekday must be between 0 and 6.',expected='Pydantic ValidationError.')
@pytest.mark.parametrize('day',[-1,7])
def test_schedule_weekday_invalid(day):
    with pytest.raises(ValidationError): Admin.CourseScheduleCreateRequest(course_id=1,day_of_week=day,start_time='09:00',end_time='10:00')

@pytest.mark.case(id='ADM-MOD-006',name='Payment model accepts supported method',description='Validate positive payment and allowed method.',expected='Model accepts valid amount/method.')
def test_payment_model_valid():
    m=Admin.FeePaymentRequest(student_id=3,amount='100.00',payment_method='online'); assert m.amount>0

@pytest.mark.case(id='ADM-MOD-007',name='Payment model rejects unsupported method',description='Payment method crypto is not among supported literals.',expected='Pydantic ValidationError.')
def test_payment_method_invalid():
    with pytest.raises(ValidationError): Admin.FeePaymentRequest(student_id=3,amount='100.00',payment_method='crypto')

@pytest.mark.case(id='ADM-MOD-008',name='Staff attendance status validation',description='Accept known attendance status and reject unknown status.',expected='Valid model accepted; unsupported status raises ValidationError.')
def test_staff_attendance_status():
    Admin.StaffAttendanceRequest(staff_id=4,attendance_date='2026-11-16',status='present')
    with pytest.raises(ValidationError): Admin.StaffAttendanceRequest(staff_id=4,attendance_date='2026-11-16',status='holiday')
