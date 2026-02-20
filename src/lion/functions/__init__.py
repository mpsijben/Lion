"""Pipeline function registry."""

from .pride import execute_pride
from .review import execute_review
from .test import execute_test
from .pr import execute_pr

FUNCTIONS = {
    "pride": execute_pride,
    "review": execute_review,
    "test": execute_test,
    "pr": execute_pr,
}
