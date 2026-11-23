from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mysql.connector import Error as MySQLError
import pytest

from Admin import create_admin_router
from AdminModules import create_admin_modules_router
from Auth import _create_access_token
from Student import create_student_router


AUTH_SECRET = "payment-test-secret-key-that-is-at-least-32-chars"


def test_admin_users_endpoint_executes_without_pagination_parameters(payment_api):
    client, database, admin_headers, _ = payment_api

    response = client.get("/admin/users", headers=admin_headers)

    assert response.status_code == 200
    assert database.queries[-1][1] == ()


@pytest.fixture
def payment_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, "PaymentDB", dict[str, str], dict[str, str]]:
    monkeypatch.setenv("AUTH_SECRET_KEY", AUTH_SECRET)
    database = PaymentDB()

    def database_dependency():
        yield database

    app = FastAPI()
    app.include_router(create_admin_router(database_dependency))
    app.include_router(create_admin_modules_router(database_dependency))
    app.include_router(create_student_router(database_dependency))
    client = TestClient(app)
    admin_headers = {
        "Authorization": f"Bearer {_create_access_token('1', ['admin'])}"
    }
    student_headers = {
        "Authorization": f"Bearer {_create_access_token('45', ['student'])}"
    }
    return client, database, admin_headers, student_headers


def test_legacy_payment_is_visible_in_admin_student_and_receipt_flows(payment_api):
    client, database, admin_headers, student_headers = payment_api

    response = client.post(
        "/admin/payments",
        headers=admin_headers,
        json={
            "student_id": 9,
            "amount": "125.50",
            "payment_method": "online",
            "transaction_reference": "  TX-LEGACY-1  ",
            "notes": "  First installment  ",
        },
    )

    assert response.status_code == 201
    payment_id = response.json()["id"]
    assert response.json() == {
        "id": payment_id,
        "student_id": 9,
        "amount": "125.50",
        "remaining_balance": "874.50",
    }
    assert database.legacy_payments[0]["transaction_reference"] == "TX-LEGACY-1"
    assert database.legacy_payments[0]["notes"] == "First installment"
    assert database.legacy_payments[0]["received_by_username"] == "1"
    assert any("FOR UPDATE" in query.upper() for query, _ in database.queries)
    assert database.commits == 1

    admin_list = client.get("/admin/payments", headers=admin_headers)
    student_summary = client.get("/student/fees", headers=student_headers)
    receipt = client.get(
        f"/student/fees/payments/{payment_id}/receipt",
        params={"source": "legacy"},
        headers=student_headers,
    )

    assert admin_list.status_code == 200
    assert admin_list.json()["data"][0]["student_name"] == "Taylor Student"
    assert admin_list.json()["data"][0]["amount"] == "125.50"
    assert student_summary.status_code == 200
    assert student_summary.json()["total_fees"] == "1800.00"
    assert student_summary.json()["paid_fees"] == "125.50"
    assert student_summary.json()["pending_fees"] == "1674.50"
    assert student_summary.json()["payment_history"][0]["source"] == "legacy"
    assert receipt.status_code == 200
    assert receipt.json()["amount"] == "125.50"
    assert receipt.json()["student_name"] == "Taylor Student"


def test_admin_payment_history_search_filter_and_load_more(payment_api):
    client, database, admin_headers, _ = payment_api
    database.legacy_payments = []
    for payment_id in range(1, 13):
        payment = database.legacy_payment(payment_id, Decimal("10.00"))
        payment["paid_at"] += timedelta(minutes=payment_id)
        payment["transaction_reference"] = f"TX-{payment_id}"
        database.legacy_payments.append(payment)

    response = client.get(
        "/admin/payments",
        params={
            "page": 2,
            "page_size": 10,
            "search": "Taylor Student",
            "class_name": "10-A",
            "payment_method": "cash",
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert [payment["id"] for payment in response.json()["data"]] == [2, 1]
    assert response.json()["pagination"] == {
        "page": 2,
        "page_size": 10,
        "total_records": 12,
        "total_pages": 2,
        "has_next": False,
        "has_previous": True,
    }
    count_query, count_params = next(
        (query, params)
        for query, params in database.queries
        if "select count(*) as total" in query.lower()
    )
    assert "concat(u.first_name, ' ', u.last_name) like %s" in count_query.lower()
    assert count_params == (
        "%Taylor Student%",
        "%Taylor Student%",
        "%Taylor Student%",
        "%Taylor Student%",
        "%Taylor Student%",
        "%Taylor Student%",
        "10-A",
        "cash",
    )


def test_legacy_payment_accepts_exact_balance_then_rejects_additional_amount(payment_api):
    client, database, admin_headers, _ = payment_api

    exact = client.post(
        "/admin/payments",
        headers=admin_headers,
        json={"student_id": 9, "amount": "1000.00", "payment_method": "cash"},
    )
    additional = client.post(
        "/admin/payments",
        headers=admin_headers,
        json={"student_id": 9, "amount": "0.01", "payment_method": "cash"},
    )

    assert exact.status_code == 201
    assert exact.json()["remaining_balance"] == "0.00"
    assert additional.status_code == 409
    assert database.commits == 1
    assert database.rollbacks == 1
    assert len(database.legacy_payments) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"student_id": 9, "amount": "0.00", "payment_method": "cash"},
        {"student_id": 9, "amount": "-0.01", "payment_method": "cash"},
        {"student_id": 9, "amount": "1.001", "payment_method": "cash"},
        {"student_id": 9, "amount": "10000000000.00", "payment_method": "cash"},
        {"student_id": 0, "amount": "1.00", "payment_method": "cash"},
        {"student_id": 9, "amount": "1.00", "payment_method": "crypto"},
        {"student_id": 9, "amount": "1.00", "payment_method": "cash", "notes": "n" * 501},
        {"student_id": 9, "amount": "1.00"},
    ],
)
def test_legacy_payment_rejects_invalid_request_without_database_access(
    payment_api, payload
):
    client, database, admin_headers, _ = payment_api

    response = client.post("/admin/payments", headers=admin_headers, json=payload)

    assert response.status_code == 422
    assert database.queries == []
    assert database.commits == 0


def test_legacy_payment_for_missing_student_rolls_back(payment_api):
    client, database, admin_headers, _ = payment_api
    database.student = None

    response = client.post(
        "/admin/payments",
        headers=admin_headers,
        json={"student_id": 999, "amount": "10.00", "payment_method": "cash"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Student not found."
    assert database.rollbacks == 1
    assert database.commits == 0


@pytest.mark.parametrize(
    ("errno", "expected_status"),
    [(1062, 409), (1205, 503)],
)
def test_legacy_payment_database_errors_map_to_conflict_or_unavailable(
    payment_api, errno, expected_status
):
    client, database, admin_headers, _ = payment_api
    database.fail_on = "insert into student_fee_payments"
    database.error_errno = errno

    response = client.post(
        "/admin/payments",
        headers=admin_headers,
        json={
            "student_id": 9,
            "amount": "10.00",
            "payment_method": "card",
            "transaction_reference": "TX-UNIQUE",
        },
    )

    assert response.status_code == expected_status
    assert database.rollbacks == 1
    assert database.commits == 0
    assert database.legacy_payments == []


def test_student_payment_receipt_is_not_visible_to_another_student(payment_api):
    client, database, admin_headers, _ = payment_api
    payment = client.post(
        "/admin/payments",
        headers=admin_headers,
        json={"student_id": 9, "amount": "10.00", "payment_method": "cash"},
    ).json()
    other_student_headers = {
        "Authorization": f"Bearer {_create_access_token('999', ['student'])}"
    }

    response = client.get(
        f"/student/fees/payments/{payment['id']}/receipt",
        params={"source": "legacy"},
        headers=other_student_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Fee receipt not found."


def test_admin_student_fee_balances_are_clamped_and_filters_are_parameterized(payment_api):
    client, database, admin_headers, _ = payment_api
    database.student["fee_amount"] = Decimal("5.00")
    database.legacy_payments.extend(
        [
            database.legacy_payment(10, Decimal("10.00")),
        ]
    )

    response = client.get(
        "/admin/students",
        params={
            "search": " Taylor ",
            "class_name": "10-A",
            "course_id": "3",
            "student_status": "active",
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.json()[0]["paid_amount"] == "10.00"
    assert response.json()[0]["balance"] == "0.00"
    query, params = next(
        (query, params)
        for query, params in database.queries
        if "from students as s" in query.lower()
        and "left join" in query.lower()
    )
    assert params == (
        "%Taylor%",
        "%Taylor%",
        "%Taylor%",
        "%Taylor%",
        "%Taylor%",
        "10-A",
        3,
        "active",
    )
    assert "s.class_name = %s" in query
    assert "EXISTS (SELECT 1 FROM student_courses" in query


def test_invoice_creation_and_partial_then_full_payment_flow(payment_api):
    client, database, admin_headers, student_headers = payment_api

    created = client.post(
        "/admin/fee-invoices",
        headers=admin_headers,
        json={
            "student_id": 9,
            "fee_type_id": 4,
            "academic_year_id": 3,
            "due_date": (date.today() + timedelta(days=30)).isoformat(),
        },
    )

    assert created.status_code == 201
    invoice_id = created.json()["id"]
    assert created.json()["amount"] == "800.00"
    assert created.json()["status"] == "unpaid"

    first_payment = client.post(
        f"/admin/fee-invoices/{invoice_id}/payments",
        headers=admin_headers,
        json={
            "amount": "300.00",
            "payment_method": "bank_transfer",
            "transaction_reference": "  TX-INVOICE-1 ",
            "notes": "  Deposit ",
        },
    )
    second_payment = client.post(
        f"/admin/fee-invoices/{invoice_id}/payments",
        headers=admin_headers,
        json={"amount": "500.00", "payment_method": "card"},
    )

    assert first_payment.status_code == 201
    assert first_payment.json()["remaining_balance"] == "500.00"
    assert first_payment.json()["status"] == "partially_paid"
    assert second_payment.status_code == 201
    assert second_payment.json()["remaining_balance"] == "0.00"
    assert second_payment.json()["status"] == "paid"
    assert database.invoice["status"] == "paid"
    assert [payment["transaction_reference"] for payment in database.invoice_payments] == [
        "TX-INVOICE-1",
        None,
    ]
    assert database.invoice_payments[0]["notes"] == "Deposit"

    history = client.get(
        f"/admin/fee-invoices/{invoice_id}/payments", headers=admin_headers
    )
    admin_receipt = client.get(
        f"/admin/fee-payments/{second_payment.json()['id']}/receipt",
        headers=admin_headers,
    )
    student_receipt = client.get(
        f"/student/fees/payments/{second_payment.json()['id']}/receipt",
        params={"source": "invoice"},
        headers=student_headers,
    )
    summary = client.get("/student/fees", headers=student_headers)

    assert history.status_code == 200
    assert [row["amount"] for row in history.json()] == ["500.00", "300.00"]
    assert admin_receipt.status_code == 200
    assert admin_receipt.json()["amount"] == "500.00"
    assert admin_receipt.json()["student_name"] == "Taylor Student"
    assert admin_receipt.json()["invoice_amount"] == "800.00"
    assert admin_receipt.json()["paid_amount"] == "800.00"
    assert admin_receipt.json()["balance"] == "0.00"
    assert student_receipt.status_code == 200
    assert student_receipt.json()["fee_name"] == "Tuition"
    assert summary.status_code == 200
    assert summary.json()["total_fees"] == "1800.00"
    assert summary.json()["paid_fees"] == "800.00"
    assert summary.json()["pending_fees"] == "1000.00"
    assert len(summary.json()["payment_history"]) == 2


def test_class_fee_assignment_creates_individual_invoices_and_skips_duplicates(payment_api):
    client, database, admin_headers, _ = payment_api
    database.invoice = None
    payload = {
        "class_name": "10-A",
        "fee_type_id": 4,
        "academic_year_id": 3,
        "due_date": (date.today() + timedelta(days=30)).isoformat(),
    }

    created = client.post(
        "/admin/fee-invoices/class",
        headers=admin_headers,
        json=payload,
    )
    duplicate = client.post(
        "/admin/fee-invoices/class",
        headers=admin_headers,
        json=payload,
    )

    assert created.status_code == 201
    assert created.json()["created_count"] == 1
    assert database.bulk_invoices == [
        {
            "student_id": 9,
            "fee_type_id": 4,
            "academic_year_id": 3,
            "amount": Decimal("800.00"),
            "due_date": date.fromisoformat(payload["due_date"]),
        }
    ]
    assert duplicate.status_code == 201
    assert duplicate.json()["created_count"] == 0
    assert len(database.bulk_invoices) == 1


def test_fee_student_options_avoid_legacy_balance_aggregation(payment_api):
    client, database, admin_headers, _ = payment_api

    response = client.get("/admin/fee-students", headers=admin_headers)
    class_response = client.get("/admin/fee-classes", headers=admin_headers)
    searched = client.get(
        "/admin/fee-students",
        params={"search": "Tay", "page": 2, "page_size": 10},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "id": 9,
            "admission_number": "ST-009",
            "class_name": "10-A",
            "status": "active",
            "name": "Taylor Student",
        }
    ]
    assert response.json()["pagination"] == {
        "page": 1,
        "page_size": 20,
        "has_next": False,
        "has_previous": False,
    }
    assert class_response.status_code == 200
    assert class_response.json() == ["10-A"]
    assert searched.status_code == 200
    student_query, student_params = database.queries[-1]
    assert "u.first_name like %s" in student_query.lower()
    assert student_params == ("Tay%", "Tay%", "Tay%", 11, 10)
    assert not any(
        "student_fee_payments" in query.lower()
        for query, _ in database.queries
    )


def test_fee_invoice_list_returns_filtered_page_and_matching_totals(payment_api):
    client, database, admin_headers, _ = payment_api

    response = client.get(
        "/admin/fee-invoices",
        params={
            "page": 1,
            "page_size": 1,
            "search": "Taylor",
            "student_id": 9,
            "class_name": "10-A",
            "payment_status": "pending",
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert len(response.json()["data"]) == 1
    assert response.json()["data"][0]["student_name"] == "Taylor Student"
    assert response.json()["pagination"] == {
        "page": 1,
        "page_size": 1,
        "total_records": 1,
        "total_pages": 1,
        "has_next": False,
        "has_previous": False,
    }
    assert response.json()["summary"] == {
        "amount": "800.00",
        "paid_amount": "0.00",
        "pending_amount": "800.00",
    }
    summary_query, summary_params = next(
        (query, params)
        for query, params in database.queries
        if "select count(*) as total" in query.lower()
        and "fee_invoices as i" in query.lower()
    )
    assert "i.student_id = %s" in summary_query
    assert "s.class_name = %s" in summary_query
    assert summary_params == (
        9,
        "10-A",
        "%Taylor%",
        "%Taylor%",
        "%Taylor%",
        "%Taylor%",
        "%Taylor%",
        "unpaid",
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"amount": "0.00", "payment_method": "cash"},
        {"amount": "-1.00", "payment_method": "cash"},
        {"amount": "1.001", "payment_method": "cash"},
        {"amount": "10000000000.00", "payment_method": "cash"},
        {"amount": "1.00", "payment_method": "crypto"},
        {"amount": "1.00", "payment_method": "cash", "transaction_reference": "x" * 121},
        {"amount": "1.00", "payment_method": "cash", "notes": "x" * 501},
    ],
)
def test_invoice_payment_rejects_invalid_request_without_database_access(
    payment_api, payload
):
    client, database, admin_headers, _ = payment_api

    response = client.post(
        "/admin/fee-invoices/14/payments",
        headers=admin_headers,
        json=payload,
    )

    assert response.status_code == 422
    assert database.queries == []
    assert database.commits == 0


def test_invoice_payment_rejects_overpayment_waived_and_missing_invoices(payment_api):
    client, database, admin_headers, _ = payment_api
    payload = {"amount": "801.00", "payment_method": "cash"}
    overpayment = client.post(
        "/admin/fee-invoices/14/payments", headers=admin_headers, json=payload
    )
    database.invoice["status"] = "waived"
    waived = client.post(
        "/admin/fee-invoices/14/payments",
        headers=admin_headers,
        json={"amount": "1.00", "payment_method": "cash"},
    )
    database.invoice = None
    missing = client.post(
        "/admin/fee-invoices/999/payments",
        headers=admin_headers,
        json={"amount": "1.00", "payment_method": "cash"},
    )

    assert overpayment.status_code == 409
    assert waived.status_code == 409
    assert missing.status_code == 404
    assert database.rollbacks == 3
    assert database.commits == 0
    assert database.invoice_payments == []


@pytest.mark.parametrize(
    ("errno", "expected_status"),
    [(1062, 409), (1205, 503)],
)
def test_invoice_payment_database_errors_roll_back_insert_and_invoice_status(
    payment_api, errno, expected_status
):
    client, database, admin_headers, _ = payment_api
    database.fail_on = "insert into fee_payments"
    database.error_errno = errno

    response = client.post(
        "/admin/fee-invoices/14/payments",
        headers=admin_headers,
        json={
            "amount": "100.00",
            "payment_method": "online",
            "transaction_reference": "TX-ERROR",
        },
    )

    assert response.status_code == expected_status
    assert database.rollbacks == 1
    assert database.commits == 0
    assert database.invoice_payments == []
    assert database.invoice["status"] == "unpaid"


def test_invoice_payment_rolls_back_if_invoice_status_update_fails(payment_api):
    client, database, admin_headers, _ = payment_api
    database.fail_on = "update fee_invoices set status"

    response = client.post(
        "/admin/fee-invoices/14/payments",
        headers=admin_headers,
        json={"amount": "300.00", "payment_method": "cash"},
    )

    assert response.status_code == 503
    assert database.rollbacks == 1
    assert database.invoice_payments == []
    assert database.invoice["status"] == "unpaid"


def test_invoice_history_and_receipt_report_missing_invoice_and_payment(payment_api):
    client, database, admin_headers, student_headers = payment_api

    missing_history = client.get(
        "/admin/fee-invoices/999/payments", headers=admin_headers
    )
    missing_admin_receipt = client.get(
        "/admin/fee-payments/999/receipt", headers=admin_headers
    )
    missing_student_receipt = client.get(
        "/student/fees/payments/999/receipt",
        params={"source": "invoice"},
        headers=student_headers,
    )

    assert missing_history.status_code == 404
    assert missing_admin_receipt.status_code == 404
    assert missing_student_receipt.status_code == 404
    assert database.commits == 0


def test_admin_records_payment_for_assigned_student_fee_and_returns_receipt_balance(payment_api):
    client, database, admin_headers, _ = payment_api

    response = client.post(
        "/admin/fee-invoices/student-payment",
        headers=admin_headers,
        json={
            "student_id": 9,
            "fee_type_id": 4,
            "academic_year_id": 3,
            "amount": "250.00",
            "payment_method": "cash",
            "transaction_reference": "  EXAM-PAY-1 ",
            "notes": "  Exam fee paid  ",
        },
    )

    assert response.status_code == 201
    assert response.json()["invoice_id"] == 14
    assert response.json()["remaining_balance"] == "550.00"
    assert response.json()["status"] == "partially_paid"
    assert database.invoice["status"] == "partially_paid"
    assert database.invoice_payments[0]["transaction_reference"] == "EXAM-PAY-1"
    assert database.invoice_payments[0]["notes"] == "Exam fee paid"

    receipt = client.get(
        f"/admin/fee-payments/{response.json()['id']}/receipt",
        headers=admin_headers,
    )

    assert receipt.status_code == 200
    assert receipt.json()["student_name"] == "Taylor Student"
    assert receipt.json()["fee_name"] == "Tuition"
    assert receipt.json()["amount"] == "250.00"
    assert receipt.json()["balance"] == "550.00"


def test_admin_creates_and_pays_invoice_when_fee_was_not_assigned(payment_api):
    client, database, admin_headers, _ = payment_api
    database.invoice = None

    response = client.post(
        "/admin/fee-invoices/student-payment",
        headers=admin_headers,
        json={
            "student_id": 9,
            "fee_type_id": 4,
            "academic_year_id": 3,
            "amount": "250.00",
            "payment_method": "cash",
            "invoice_due_date": (date.today() + timedelta(days=14)).isoformat(),
        },
    )

    assert response.status_code == 201
    assert response.json()["invoice_created"] is True
    assert response.json()["remaining_balance"] == "550.00"
    assert database.invoice["amount"] == Decimal("800.00")
    assert database.invoice["due_date"] == date.today() + timedelta(days=14)
    assert database.invoice["status"] == "partially_paid"
    assert database.commits == 1
    assert database.rollbacks == 0


def test_admin_must_use_invoice_ledger_when_matching_invoices_are_ambiguous(payment_api):
    client, database, admin_headers, _ = payment_api
    database.bulk_invoices.append(
        {
            **database.invoice,
            "id": 15,
        }
    )

    response = client.post(
        "/admin/fee-invoices/student-payment",
        headers=admin_headers,
        json={
            "student_id": 9,
            "fee_type_id": 4,
            "academic_year_id": 3,
            "amount": "250.00",
            "payment_method": "cash",
        },
    )

    assert response.status_code == 409
    assert "Multiple matching invoices" in response.json()["detail"]
    assert database.invoice_payments == []
    assert database.commits == 0
    assert database.rollbacks == 1


def test_student_fee_summary_reports_overdue_waived_and_paid_invoice_statuses(payment_api):
    client, database, _, student_headers = payment_api
    database.invoice["due_date"] = date.today() - timedelta(days=1)
    database.invoice_payments.append(
        database.invoice_payment(24, Decimal("800.00"))
    )

    summary = client.get("/student/fees", headers=student_headers)

    assert summary.status_code == 200
    assert summary.json()["items"][1]["payment_status"] == "paid"
    database.invoice_payments.clear()
    database.invoice["status"] = "unpaid"
    summary = client.get("/student/fees", headers=student_headers)
    assert summary.json()["items"][1]["payment_status"] == "overdue"
    database.invoice["status"] = "waived"
    summary = client.get("/student/fees", headers=student_headers)
    assert summary.json()["items"][1]["payment_status"] == "waived"
    assert summary.json()["items"][1]["pending_amount"] == "0.00"


def test_payment_endpoints_enforce_roles_and_student_profile_existence(payment_api):
    client, database, _, student_headers = payment_api
    wrong_role_headers = {
        "Authorization": f"Bearer {_create_access_token('45', ['teacher'])}"
    }
    forbidden = client.get("/admin/payments", headers=student_headers)
    wrong_role = client.get("/student/fees", headers=wrong_role_headers)
    assert forbidden.status_code == 403
    assert wrong_role.status_code == 403
    assert database.queries == []

    missing_profile_headers = {
        "Authorization": f"Bearer {_create_access_token('999', ['student'])}"
    }
    missing_profile = client.get("/student/fees", headers=missing_profile_headers)

    assert missing_profile.status_code == 404
    assert len(database.queries) == 1


class PaymentDB:
    def __init__(self) -> None:
        self.student: dict[str, Any] | None = {
            "student_id": 9,
            "id": 9,
            "user_id": 45,
            "admission_number": "ST-009",
            "class_name": "10-A",
            "status": "active",
            "fee_amount": Decimal("1000.00"),
            "username": "taylor",
            "first_name": "Taylor",
            "last_name": "Student",
            "email": "taylor@example.com",
        }
        self.fee_type: dict[str, Any] | None = {
            "id": 4,
            "name": "Tuition",
            "amount": Decimal("800.00"),
            "class_name": None,
            "academic_year_id": None,
        }
        self.academic_year = {"id": 3, "name": "2026-2027"}
        self.invoice: dict[str, Any] | None = {
            "id": 14,
            "student_id": 9,
            "fee_type_id": 4,
            "academic_year_id": 3,
            "amount": Decimal("800.00"),
            "status": "unpaid",
            "due_date": date.today() + timedelta(days=30),
        }
        self.legacy_payments: list[dict[str, Any]] = []
        self.invoice_payments: list[dict[str, Any]] = []
        self.bulk_invoices: list[dict[str, Any]] = []
        self.queries: list[tuple[str, tuple[Any, ...]]] = []
        self.commits = 0
        self.rollbacks = 0
        self.next_id = 70
        self.fail_on: str | None = None
        self.error_errno = 1205
        self.pending_legacy: list[dict[str, Any]] = []
        self.pending_invoice_payments: list[dict[str, Any]] = []
        self.pending_invoice: dict[str, Any] | None = None
        self.pending_new_invoice: dict[str, Any] | None = None

    def cursor(self, dictionary: bool = False) -> "PaymentCursor":
        return PaymentCursor(self)

    def commit(self) -> None:
        self.legacy_payments.extend(self.pending_legacy)
        self.invoice_payments.extend(self.pending_invoice_payments)
        if self.pending_new_invoice is not None:
            self.invoice = self.pending_new_invoice
        if self.pending_invoice is not None:
            self.invoice = self.pending_invoice
        self.pending_legacy = []
        self.pending_invoice_payments = []
        self.pending_invoice = None
        self.pending_new_invoice = None
        self.commits += 1

    def rollback(self) -> None:
        self.pending_legacy = []
        self.pending_invoice_payments = []
        self.pending_invoice = None
        self.pending_new_invoice = None
        self.rollbacks += 1

    def legacy_payment(self, payment_id: int, amount: Decimal) -> dict[str, Any]:
        return {
            "id": payment_id,
            "student_id": 9,
            "amount": amount,
            "paid_at": datetime(2026, 11, 18, 9, 0),
            "payment_method": "cash",
            "transaction_reference": None,
            "received_by_username": "admin",
            "notes": None,
        }

    def invoice_payment(self, payment_id: int, amount: Decimal) -> dict[str, Any]:
        return {
            "id": payment_id,
            "invoice_id": 14,
            "amount": amount,
            "paid_at": datetime(2026, 11, 18, 9, 0),
            "payment_method": "cash",
            "transaction_reference": None,
            "received_by": 1,
            "received_by_username": "admin",
            "notes": None,
        }


class PaymentCursor:
    def __init__(self, database: PaymentDB) -> None:
        self.database = database
        self.query = ""
        self.params: tuple[Any, ...] = ()
        self.result: dict[str, Any] | None = None
        self.rows: list[dict[str, Any]] = []
        self.inserted_id = 0

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        normalized = " ".join(query.lower().split())
        self.query = normalized
        self.params = tuple(params)
        self.database.queries.append((query, self.params))
        self.result = None
        self.rows = []

        if self.database.fail_on and self.database.fail_on in normalized:
            raise MySQLError("Simulated database error.", errno=self.database.error_errno)

        if "select id, fee_amount from students where id" in normalized:
            if self.database.student and self.database.student["id"] == self.params[0]:
                self.result = {
                    "id": self.database.student["id"],
                    "fee_amount": self.database.student["fee_amount"],
                }
        elif "select id, class_name from students where id" in normalized:
            if self.database.student and self.database.student["id"] == self.params[0]:
                self.result = {
                    "id": self.database.student["id"],
                    "class_name": self.database.student["class_name"],
                }
        elif "select s.id as student_id" in normalized and "from students as s" in normalized:
            if self.database.student and self.database.student["user_id"] == self.params[0]:
                self.result = self.database.student.copy()
        elif "select coalesce(sum(amount), 0) as paid_amount from student_fee_payments" in normalized:
            self.result = {
                "paid_amount": sum(
                    (row["amount"] for row in self.database.legacy_payments),
                    Decimal("0"),
                )
            }
        elif "insert into student_fee_payments" in normalized:
            student_id, amount, method, reference, receiver, notes = self.params
            row = self.database.legacy_payment(
                self.database.next_id, Decimal(amount)
            )
            row.update(
                {
                    "student_id": student_id,
                    "payment_method": method,
                    "transaction_reference": reference,
                    "received_by_username": receiver,
                    "notes": notes,
                }
            )
            self.inserted_id = self.database.next_id
            self.database.next_id += 1
            self.database.pending_legacy.append(row)
        elif (
            "from student_fee_payments as p" in normalized
            and "where p.id = %s and s.user_id = %s" in normalized
        ):
            payment_id, user_id = self.params
            if self.database.student and user_id == self.database.student["user_id"]:
                payment = next(
                    (row for row in self.database.legacy_payments if row["id"] == payment_id),
                    None,
                )
                if payment:
                    self.result = {
                        **payment,
                        "invoice_id": None,
                        "fee_name": "Student fee balance",
                        "academic_year": None,
                        "admission_number": self.database.student["admission_number"],
                        "class_name": self.database.student["class_name"],
                        "student_name": f"{self.database.student['first_name']} {self.database.student['last_name']}",
                    }
        elif (
            "select count(*) as total" in normalized
            and "from student_fee_payments as p" in normalized
        ):
            self.result = {"total": len(self.database.legacy_payments)}
        elif "from student_fee_payments as p join students as s" in normalized:
            rows = [
                {
                    **row,
                    "admission_number": self.database.student["admission_number"],
                    "class_name": self.database.student["class_name"],
                    "username": self.database.student["username"],
                    "first_name": self.database.student["first_name"],
                    "last_name": self.database.student["last_name"],
                }
                for row in self.database.legacy_payments
            ]
            self.rows = sorted(
                rows,
                key=lambda row: (row["paid_at"], row["id"]),
                reverse=True,
            )
            if "limit %s offset %s" in normalized:
                page_size, offset = self.params[-2:]
                self.rows = self.rows[offset : offset + page_size]
        elif (
            "select s.id, s.admission_number, s.class_name, s.status" in normalized
            and "from students as s join users as u" in normalized
            and "left join" not in normalized
        ):
            student = self.database.student
            if student:
                self.rows = [
                    {
                        "id": student["id"],
                        "admission_number": student["admission_number"],
                        "class_name": student["class_name"],
                        "status": student["status"],
                        "name": f"{student['first_name']} {student['last_name']}",
                    }
                ]
        elif "select distinct class_name from students" in normalized:
            student = self.database.student
            self.rows = [(student["class_name"],)] if student else []
        elif (
            "from students as s" in normalized
            and "left join" in normalized
            and "fee_invoices as existing" not in normalized
        ):
            student = self.database.student
            if student:
                self.rows = [
                    {
                        "id": student["id"],
                        "admission_number": student["admission_number"],
                        "class_name": student["class_name"],
                        "status": student["status"],
                        "fee_amount": student["fee_amount"],
                        "paid_amount": sum(
                            (row["amount"] for row in self.database.legacy_payments),
                            Decimal("0"),
                        ),
                        "username": student["username"],
                        "first_name": student["first_name"],
                        "last_name": student["last_name"],
                    }
                ]
        elif "select amount, class_name, academic_year_id from fee_types where id" in normalized:
            if self.database.fee_type and self.database.fee_type["id"] == self.params[0]:
                self.result = self.database.fee_type.copy()
        elif (
            "select count(*) as total" in normalized
            and "fee_invoices as i" in normalized
        ):
            invoice = self.database.invoice
            paid_amount = sum(
                (
                    row["amount"]
                    for row in self.database.invoice_payments
                    if invoice and row["invoice_id"] == invoice["id"]
                ),
                Decimal("0"),
            )
            amount = invoice["amount"] if invoice else Decimal("0")
            self.result = {
                "total": 1 if invoice else 0,
                "amount": amount,
                "paid_amount": paid_amount,
                "pending_amount": max(amount - paid_amount, Decimal("0")),
            }
        elif "select amount from fee_types where id" in normalized:
            if self.database.fee_type and self.database.fee_type["id"] == self.params[0]:
                self.result = {"amount": self.database.fee_type["amount"]}
        elif (
            "from students as s left join fee_invoices as existing" in normalized
            and "existing.id is null" in normalized
        ):
            fee_type_id, academic_year_id, class_name = self.params
            student = self.database.student
            existing_invoices = list(self.database.bulk_invoices)
            if self.database.invoice:
                existing_invoices.append(self.database.invoice)
            if (
                student
                and student["status"] == "active"
                and student["class_name"] == class_name
                and not any(
                    invoice["student_id"] == student["id"]
                    and invoice["fee_type_id"] == fee_type_id
                    and invoice["academic_year_id"] == academic_year_id
                    for invoice in existing_invoices
                )
            ):
                self.rows = [{"id": student["id"]}]
        elif "insert into fee_invoices" in normalized:
            student_id, fee_type_id, year_id, amount, due_date = self.params
            self.database.pending_new_invoice = {
                "id": self.database.next_id,
                "student_id": student_id,
                "fee_type_id": fee_type_id,
                "academic_year_id": year_id,
                "amount": Decimal(amount),
                "status": "unpaid",
                "due_date": due_date,
            }
            self.inserted_id = self.database.next_id
            self.database.next_id += 1
        elif "select amount, status from fee_invoices where id" in normalized:
            invoice = self.database.pending_new_invoice or self.database.invoice
            if invoice and invoice["id"] == self.params[0]:
                self.result = {
                    "amount": invoice["amount"],
                    "status": invoice["status"],
                }
        elif (
            "select id from fee_invoices" in normalized
            and "where student_id = %s" in normalized
            and "fee_type_id = %s" in normalized
        ):
            student_id, fee_type_id, academic_year_id = self.params
            invoices = list(self.database.bulk_invoices)
            if self.database.invoice:
                invoices.append(self.database.invoice)
            self.rows = [
                {"id": invoice["id"]}
                for invoice in invoices
                if invoice.get("student_id") == student_id
                and invoice.get("fee_type_id") == fee_type_id
                and invoice.get("academic_year_id") == academic_year_id
            ][:2]
        elif "select coalesce(sum(amount), 0) as paid_amount from fee_payments" in normalized:
            invoice_id = self.params[0]
            self.result = {
                "paid_amount": sum(
                    (
                        row["amount"]
                        for row in self.database.invoice_payments
                        if row["invoice_id"] == invoice_id
                    ),
                    Decimal("0"),
                )
            }
        elif "insert into fee_payments" in normalized:
            invoice_id, amount, method, reference, receiver_id, notes = self.params
            row = self.database.invoice_payment(
                self.database.next_id, Decimal(amount)
            )
            row.update(
                {
                    "invoice_id": invoice_id,
                    "payment_method": method,
                    "transaction_reference": reference,
                    "received_by": receiver_id,
                    "notes": notes,
                }
            )
            self.inserted_id = self.database.next_id
            self.database.next_id += 1
            self.database.pending_invoice_payments.append(row)
        elif "update fee_invoices set status" in normalized:
            status, invoice_id = self.params
            if self.database.pending_new_invoice and self.database.pending_new_invoice["id"] == invoice_id:
                self.database.pending_new_invoice = {
                    **self.database.pending_new_invoice,
                    "status": status,
                }
            elif self.database.invoice and self.database.invoice["id"] == invoice_id:
                self.database.pending_invoice = {
                    **self.database.invoice,
                    "status": status,
                }
        elif "select id from fee_invoices where id" in normalized:
            if self.database.invoice and self.database.invoice["id"] == self.params[0]:
                self.result = {"id": self.database.invoice["id"]}
        elif (
            "from fee_invoices as i" in normalized
            and "s.admission_number" in normalized
            and "order by i.due_date" in normalized
        ):
            invoice = self.database.invoice
            student = self.database.student
            if invoice and student:
                paid_amount = sum(
                    (
                        row["amount"]
                        for row in self.database.invoice_payments
                        if row["invoice_id"] == invoice["id"]
                    ),
                    Decimal("0"),
                )
                amount = invoice["amount"]
                if invoice["status"] == "waived":
                    payment_status = "waived"
                elif paid_amount >= amount:
                    payment_status = "paid"
                elif paid_amount > 0:
                    payment_status = "partially_paid"
                elif invoice["due_date"] < date.today():
                    payment_status = "overdue"
                else:
                    payment_status = "pending"
                self.rows = [
                    {
                        "id": invoice["id"],
                        "student_id": invoice["student_id"],
                        "admission_number": student["admission_number"],
                        "class_name": student["class_name"],
                        "student_name": f"{student['first_name']} {student['last_name']}",
                        "fee_name": self.database.fee_type["name"],
                        "amount": amount,
                        "due_date": invoice["due_date"],
                        "paid_amount": paid_amount,
                        "pending_amount": max(amount - paid_amount, Decimal("0")),
                        "payment_status": payment_status,
                    }
                ]
                page_size, offset = self.params[-2:]
                self.rows = self.rows[offset : offset + page_size]
        elif (
            "select p.id, p.amount, p.paid_at" in normalized
            and "from fee_payments as p" in normalized
            and "where i.student_id = %s" in normalized
        ):
            self.rows = [
                {
                    **row,
                    "fee_name": self.database.fee_type["name"],
                    "academic_year": self.database.academic_year["name"],
                }
                for row in reversed(self.database.invoice_payments)
                if self.database.invoice
                and self.database.invoice["student_id"] == self.params[0]
            ]
        elif "select p.id, p.amount, p.paid_at" in normalized and "from fee_payments as p" in normalized:
            if "where p.invoice_id" in normalized:
                invoice_id = self.params[0]
                self.rows = [
                    {
                        **row,
                        "received_by_username": row["received_by_username"],
                    }
                    for row in reversed(self.database.invoice_payments)
                    if row["invoice_id"] == invoice_id
                ]
            elif "where p.id = %s and s.user_id = %s" in normalized:
                payment_id, user_id = self.params
                self.result = self._invoice_receipt(payment_id, user_id)
            else:
                payment_id = self.params[0]
                self.result = self._invoice_receipt(payment_id, None)
        elif "select i.id, i.amount, i.due_date" in normalized and "from fee_invoices as i" in normalized:
            invoice = self.database.invoice
            if invoice and self.database.student and invoice["student_id"] == self.database.student["id"]:
                paid_amount = sum(
                    (
                        row["amount"]
                        for row in self.database.invoice_payments
                        if row["invoice_id"] == invoice["id"]
                    ),
                    Decimal("0"),
                )
                self.rows = [
                    {
                        **invoice,
                        "academic_year": self.database.academic_year["name"],
                        "fee_name": self.database.fee_type["name"],
                        "paid_amount": paid_amount,
                    }
                ]
        elif "from student_fee_payments" in normalized and "where student_id = %s" in normalized:
            self.rows = [
                row
                for row in reversed(self.database.legacy_payments)
                if row["student_id"] == self.params[0]
            ]

    def executemany(self, query: str, seq_params: list[tuple[Any, ...]]) -> None:
        self.database.queries.append((query, tuple(seq_params)))
        for student_id, fee_type_id, academic_year_id, amount, due_date in seq_params:
            self.database.bulk_invoices.append(
                {
                    "student_id": student_id,
                    "fee_type_id": fee_type_id,
                    "academic_year_id": academic_year_id,
                    "amount": Decimal(amount),
                    "due_date": due_date,
                }
            )

    def _invoice_receipt(self, payment_id: int, user_id: int | None) -> dict[str, Any] | None:
        payment = next(
            (row for row in self.database.invoice_payments if row["id"] == payment_id),
            None,
        )
        invoice = self.database.invoice
        student = self.database.student
        if (
            payment is None
            or invoice is None
            or student is None
            or invoice["id"] != payment["invoice_id"]
            or (user_id is not None and student["user_id"] != user_id)
        ):
            return None
        return {
            **payment,
            "invoice_id": invoice["id"],
            "fee_name": self.database.fee_type["name"],
            "academic_year": self.database.academic_year["name"],
            "admission_number": student["admission_number"],
            "class_name": student["class_name"],
            "student_name": f"{student['first_name']} {student['last_name']}",
            "invoice_amount": invoice["amount"],
            "paid_amount": sum(
                (row["amount"] for row in self.database.invoice_payments if row["invoice_id"] == invoice["id"]),
                Decimal("0"),
            ),
            "balance": max(
                invoice["amount"]
                - sum(
                    (row["amount"] for row in self.database.invoice_payments if row["invoice_id"] == invoice["id"]),
                    Decimal("0"),
                ),
                Decimal("0"),
            ),
        }

    def fetchone(self) -> dict[str, Any] | None:
        return self.result

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows

    @property
    def lastrowid(self) -> int:
        return self.inserted_id

    def close(self) -> None:
        pass
