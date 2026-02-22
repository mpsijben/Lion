"""Pipeline function registry."""

from .pride import execute_pride
from .review import execute_review
from .test import execute_test
from .pr import execute_pr
from .create_tests import execute_create_tests
from .lint import execute_lint
from .typecheck import execute_typecheck
from .future import execute_future
from .devil import execute_devil
from .context_build import execute_context
from .distill import execute_distill
from .task import execute_task
from .impl import execute_impl
from .onboard import execute_onboard
from .audit import execute_audit
from .cost import execute_cost
from .migrate import execute_migrate
from .pair import execute_pair

FUNCTIONS = {
    "pride": execute_pride,
    "review": execute_review,
    "test": execute_test,
    "pr": execute_pr,
    "create_tests": execute_create_tests,
    "create_test": execute_create_tests,
    "lint": execute_lint,
    "typecheck": execute_typecheck,
    "future": execute_future,
    "devil": execute_devil,
    "context": execute_context,
    "distill": execute_distill,
    "task": execute_task,
    "impl": execute_impl,
    "onboard": execute_onboard,
    "audit": execute_audit,
    "cost": execute_cost,
    "migrate": execute_migrate,
    "pair": execute_pair,
}
