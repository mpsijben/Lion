"""Pipeline function registry."""

from .pride import execute_pride
from .review import execute_review
from .test import execute_test
from .pr import execute_pr
from .create_tests import execute_create_tests
from .lint import execute_lint
from .typecheck import execute_typecheck

FUNCTIONS = {
    "pride": execute_pride,
    "review": execute_review,
    "test": execute_test,
    "pr": execute_pr,
    "create_tests": execute_create_tests,
    "lint": execute_lint,
    "typecheck": execute_typecheck,
}
