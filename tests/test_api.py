"""Tests for lion.api module."""

import pytest

# FastAPI has compatibility issues with Python 3.14 alpha
# Skip these tests if import fails
try:
    from fastapi.testclient import TestClient
    from lion.api import app
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    TestClient = None
    app = None


pytestmark = pytest.mark.skipif(
    not FASTAPI_AVAILABLE,
    reason="FastAPI not compatible with this Python version"
)


@pytest.fixture
def client():
    """Create a test client for the API."""
    if not FASTAPI_AVAILABLE:
        pytest.skip("FastAPI not available")
    return TestClient(app)


class TestRootEndpoint:
    """Tests for root endpoint."""

    def test_root_returns_hello_world(self, client):
        """Test that root endpoint returns hello world message."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Hello, World!"
        assert data["service"] == "Lion API"

    def test_root_returns_json(self, client):
        """Test that root endpoint returns JSON."""
        response = client.get("/")

        assert response.headers["content-type"] == "application/json"


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_returns_healthy(self, client):
        """Test that health endpoint returns healthy status."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_returns_json(self, client):
        """Test that health endpoint returns JSON."""
        response = client.get("/health")

        assert response.headers["content-type"] == "application/json"


class TestHelloEndpoint:
    """Tests for hello/{name} endpoint."""

    def test_hello_with_name(self, client):
        """Test hello endpoint with name parameter."""
        response = client.get("/hello/World")

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Hello, World!"

    def test_hello_with_different_name(self, client):
        """Test hello endpoint with different name."""
        response = client.get("/hello/Alice")

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Hello, Alice!"

    def test_hello_with_unicode_name(self, client):
        """Test hello endpoint with unicode name."""
        response = client.get("/hello/日本語")

        assert response.status_code == 200
        data = response.json()
        assert "日本語" in data["message"]

    def test_hello_with_spaces_encoded(self, client):
        """Test hello endpoint with encoded spaces in name."""
        response = client.get("/hello/John%20Doe")

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Hello, John Doe!"


class TestAppMetadata:
    """Tests for app metadata."""

    def test_app_title(self):
        """Test that app has correct title."""
        assert app.title == "Lion API"

    def test_app_version(self):
        """Test that app has version."""
        assert app.version == "0.1.0"

    def test_app_description(self):
        """Test that app has description."""
        assert "Hello World" in app.description


class TestErrorHandling:
    """Tests for API error handling."""

    def test_not_found_endpoint(self, client):
        """Test that non-existent endpoint returns 404."""
        response = client.get("/nonexistent")

        assert response.status_code == 404

    def test_method_not_allowed(self, client):
        """Test that wrong method returns 405."""
        response = client.post("/")

        assert response.status_code == 405


class TestOpenAPIDocumentation:
    """Tests for OpenAPI documentation."""

    def test_openapi_json_available(self, client):
        """Test that OpenAPI JSON is available."""
        response = client.get("/openapi.json")

        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "info" in data
        assert data["info"]["title"] == "Lion API"

    def test_docs_endpoint_available(self, client):
        """Test that docs endpoint is available."""
        response = client.get("/docs")

        assert response.status_code == 200

    def test_redoc_endpoint_available(self, client):
        """Test that redoc endpoint is available."""
        response = client.get("/redoc")

        assert response.status_code == 200
