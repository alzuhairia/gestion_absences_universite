"""Small helpers shared by the test modules."""

from django.test import TestCase


def capture_on_commit_callbacks(*, execute=False):
    """
    TestCase.captureOnCommitCallbacks, callable outside the class.
    (It is a classmethod; the django-types stubs do not declare it.)
    """
    capture = getattr(TestCase, "captureOnCommitCallbacks")
    return capture(execute=execute)
