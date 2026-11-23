import pytest


def test_intentional_failure_is_visible_in_attendance_report():
    """Opt-in demonstration for verifying failed-test reporting."""
    pytest.fail("Intentional report-demo failure; this is not an application defect.")
