"""Pipeline function registry."""

from .pride import execute_pride

FUNCTIONS = {
    "pride": execute_pride,
}
