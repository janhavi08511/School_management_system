import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Auth import _create_access_token
from Student import create_student_router


AUTH_SECRET = "test-auth-secret-key-that-is-at-least-32-chars"


class StudentApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cursor = FakeCursor()
        self.connection = FakeConnection(self.cursor)

        def database_dependency():
            yield self.connection

        app = FastAPI()
        app.include_router(create_student_router(database_dependency))
        self.client = TestClient(app)
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            token = _create_access_token("45", ["student"])
            other_role_token = _create_access_token("45", ["teacher"])
        self.student_headers = {"Authorization": f"Bearer {token}"}
        self.other_role_headers = {"Authorization": f"Bearer {other_role_token}"}

    def test_fee_totals_are_loaded_for_the_authenticated_student(self) -> None:
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.get("/student/fees", headers=self.student_headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_fees"], "100.00")
        self.assertEqual(response.json()["pending_fees"], "100.00")
        student_lookup = next(
            (query, params)
            for query, params in self.cursor.queries
            if "from students as s" in query.lower()
        )
        self.assertEqual(student_lookup[1], (45,))
        self.assertTrue(
            all(
                params == (14,)
                for query, params in self.cursor.queries
                if "from fee_invoices" in query.lower()
                or "from student_fee_payments" in query.lower()
                or "from fee_payments" in query.lower()
            )
        )

    def test_non_student_role_cannot_access_student_profile(self) -> None:
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": AUTH_SECRET}):
            response = self.client.get(
                "/student/profile",
                headers=self.other_role_headers,
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.cursor.queries, [])


class FakeCursor:
    def __init__(self) -> None:
        self.queries: list[tuple[str, tuple[object, ...]]] = []
        self.current_query = ""
        self.current_params: tuple[object, ...] = ()

    def execute(self, query: str, params: tuple[object, ...] = ()) -> None:
        self.current_query = query.lower()
        self.current_params = params
        self.queries.append((query, params))

    def fetchone(self) -> dict[str, object] | None:
        if "from students as s" in self.current_query:
            return {
                "student_id": 14,
                "admission_number": "ST-014",
                "fee_amount": Decimal("100.00"),
            }
        return None

    def fetchall(self) -> list[dict[str, object]]:
        return []

    def close(self) -> None:
        pass


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.fake_cursor = cursor

    def cursor(self, dictionary: bool = False) -> FakeCursor:
        return self.fake_cursor

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


if __name__ == "__main__":
    unittest.main()
