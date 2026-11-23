import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import Admin
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from decimal import Decimal

class Cursor:
    def __init__(self,db): self.db=db; self.lastrowid=71
    def execute(self,query,params=None):
        q=' '.join(query.lower().split()); self.db.queries.append((q,params)); self.db.result=None
        if 'select id, teacher_id from courses' in q: self.db.result=self.db.course
        elif 'select id from courses where course_code' in q: self.db.result=self.db.duplicate
        elif 'select id from staff where id' in q: self.db.result=self.db.staff
        elif 'select id, fee_amount from students' in q: self.db.result=self.db.student
        elif 'select coalesce(sum(amount), 0) as paid_amount' in q: self.db.result={'paid_amount':self.db.paid}
    def fetchone(self): return self.db.result
    def fetchall(self): return []
    def close(self): pass
class DB:
    def __init__(self):
        self.queries=[]; self.result=None; self.course={'id':1,'teacher_id':5}; self.duplicate=None; self.staff={'id':5}; self.student={'id':9,'fee_amount':Decimal('1000.00')}; self.paid=Decimal('200.00'); self.commits=0; self.rollbacks=0
    def cursor(self,dictionary=True): return Cursor(self)
    def commit(self): self.commits+=1
    def rollback(self): self.rollbacks+=1
@pytest.fixture
def client_db():
    db=DB(); app=FastAPI(); app.include_router(Admin.create_admin_router(lambda:db)); app.dependency_overrides[Admin._require_admin]=lambda:{'sub':'test-admin'}
    return TestClient(app),db

@pytest.mark.case(id='ADM-API-001',name='Create course with valid payload',description='POST /admin/courses with valid code and name.',expected='HTTP 201; normalized code CS-101; ID returned; commit invoked.')
def test_create_course_success(client_db):
    client,db=client_db; r=client.post('/admin/courses',json={'course_code':'cs-101','name':'Computer Science','duration_months':12})
    assert r.status_code==201 and r.json()['course_code']=='CS-101' and r.json()['id']==71 and db.commits==1

@pytest.mark.case(id='ADM-API-002',name='Duplicate course code conflict',description='Existing course code must not be inserted again.',expected='HTTP 409 and transaction rollback.')
def test_create_course_duplicate(client_db):
    client,db=client_db; db.duplicate={'id':4}; r=client.post('/admin/courses',json={'course_code':'CS-101','name':'Computer Science'})
    assert r.status_code==409 and db.rollbacks==1

@pytest.mark.case(id='ADM-API-003',name='Course code invalid characters',description='Course code with space/special punctuation is rejected.',expected='HTTP 422 and no commit.')
def test_create_course_invalid_code(client_db):
    client,db=client_db; r=client.post('/admin/courses',json={'course_code':'CS 101!','name':'Computer Science'})
    assert r.status_code==422 and db.commits==0

@pytest.mark.case(id='ADM-API-004',name='Schedule assigned course',description='POST /admin/schedules for course with a teacher.',expected='HTTP 201; schedule id and time returned; commit invoked.')
def test_schedule_assigned_course(client_db):
    client,db=client_db; r=client.post('/admin/schedules',json={'course_id':1,'day_of_week':2,'start_time':'09:00','end_time':'10:00','class_name':'A','room':'R-1'})
    assert r.status_code==201 and r.json()['id']==71 and r.json()['start_time']=='09:00' and db.commits==1

@pytest.mark.case(id='ADM-API-005',name='Schedule end time before start',description='Schedule request with end earlier than start.',expected='HTTP 422 and no commit.')
def test_schedule_invalid_time(client_db):
    client,db=client_db; r=client.post('/admin/schedules',json={'course_id':1,'day_of_week':2,'start_time':'10:00','end_time':'09:00'})
    assert r.status_code==422 and db.commits==0

@pytest.mark.case(id='ADM-API-006',name='Schedule unknown course',description='Schedule course ID not found in DB fake.',expected='HTTP 404 and rollback.')
def test_schedule_course_missing(client_db):
    client,db=client_db; db.course=None; r=client.post('/admin/schedules',json={'course_id':999,'day_of_week':2,'start_time':'09:00','end_time':'10:00'})
    assert r.status_code==404 and db.rollbacks==1

@pytest.mark.case(id='ADM-API-007',name='Schedule course teacher unassigned',description='Course teacher_id is null.',expected='HTTP 409 and rollback.')
def test_schedule_teacher_unassigned(client_db):
    client,db=client_db; db.course={'id':1,'teacher_id':None}; r=client.post('/admin/schedules',json={'course_id':1,'day_of_week':2,'start_time':'09:00','end_time':'10:00'})
    assert r.status_code==409 and db.rollbacks==1

def test_schedule_catalog_filters_and_paginates_by_day(client_db):
    client, db = client_db

    response = client.get(
        "/admin/schedules",
        params={"day_of_week": 1, "page": 2, "page_size": 5},
    )

    assert response.status_code == 200
    assert response.json()["data"] == []
    assert response.json()["pagination"] == {
        "page": 2,
        "page_size": 5,
        "total_records": 0,
        "total_pages": 0,
        "has_next": False,
        "has_previous": True,
    }
    schedule_query = next(
        (query, params)
        for query, params in db.queries
        if "from teacher_course_schedules as sc" in query
        and "limit %s offset %s" in query
    )
    assert schedule_query[1] == (1, 5, 5)

def test_enrollment_student_search_includes_name_filter_and_pagination(client_db):
    client, db = client_db

    response = client.get(
        "/admin/enrollment-students",
        params={"class_name": "11", "search": "Ada", "page": 2, "page_size": 10},
    )

    assert response.status_code == 200
    assert response.json()["data"] == []
    assert response.json()["pagination"]["page"] == 2
    assert response.json()["pagination"]["page_size"] == 10
    student_query = next(
        (query, params)
        for query, params in db.queries
        if "from students as s" in query and "limit %s offset %s" in query
    )
    assert "concat(u.first_name, ' ', u.last_name) like %s" in student_query[0]
    assert student_query[1] == ("11", "%Ada%", "%Ada%", "%Ada%", "%Ada%", "%Ada%", 10, 10)

@pytest.mark.case(id='ADM-API-008',name='Fee payment within remaining balance',description='Post a payment amount below the remaining student fee.',expected='HTTP 201; remaining balance is 700.00; commit invoked.')
def test_fee_payment_success(client_db):
    client,db=client_db; r=client.post('/admin/payments',json={'student_id':9,'amount':'100.00','payment_method':'online','transaction_reference':'TX-ABC'})
    assert r.status_code==201 and r.json()['remaining_balance']=='700.00' and db.commits==1

@pytest.mark.case(id='ADM-API-009',name='Fee payment over balance rejected',description='Post 900 when balance is 800.',expected='HTTP 409; rollback and no commit.')
def test_fee_overpayment(client_db):
    client,db=client_db; r=client.post('/admin/payments',json={'student_id':9,'amount':'900.00','payment_method':'cash'})
    assert r.status_code==409 and db.rollbacks==1 and db.commits==0

@pytest.mark.case(id='ADM-API-010',name='Fee payment for missing student',description='Attempt payment for student ID absent in test database.',expected='HTTP 404 and rollback.')
def test_payment_missing_student(client_db):
    client,db=client_db; db.student=None; r=client.post('/admin/payments',json={'student_id':999,'amount':'50.00','payment_method':'cash'})
    assert r.status_code==404 and db.rollbacks==1

@pytest.mark.case(id='ADM-API-011',name='Record staff attendance',description='POST attendance for active staff and trim notes whitespace.',expected='HTTP 200; notes trimmed; commit invoked.')
def test_staff_attendance_success(client_db):
    client,db=client_db; r=client.post('/admin/staff-attendance',json={'staff_id':5,'attendance_date':'2026-11-16','status':'present','notes':'  arrived  '})
    assert r.status_code==200 and r.json()['notes']=='arrived' and db.commits==1

@pytest.mark.case(id='ADM-API-012',name='Staff attendance unknown staff',description='Attendance request refers to unknown/inactive staff id.',expected='HTTP 404 and rollback.')
def test_staff_attendance_missing_staff(client_db):
    client,db=client_db; db.staff=None; r=client.post('/admin/staff-attendance',json={'staff_id':999,'attendance_date':'2026-11-16','status':'present'})
    assert r.status_code==404 and db.rollbacks==1
