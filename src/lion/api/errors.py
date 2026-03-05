"""Error types for structured API responses."""

from __future__ import annotations


class ApiError(Exception):
    """Base API error with structured code and status."""

    def __init__(self, status_code: int, error_code: str, message: str, detail: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.detail = detail


class PipelineValidationError(ApiError):
    """Raised when request/pipeline syntax is invalid."""

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(
            status_code=400,
            error_code="invalid_pipeline",
            message=message,
            detail=detail,
        )
