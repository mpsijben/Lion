"""
Hello World API for Lion.

A simple FastAPI-based REST API.

Usage:
    uvicorn lion.api:app --reload

Or run directly:
    python -m lion.api
"""

from fastapi import FastAPI

app = FastAPI(
    title="Lion API",
    description="Hello World API for the Lion orchestration system",
    version="0.1.0"
)


@app.get("/")
def root():
    """Root endpoint returning a welcome message."""
    return {"message": "Hello, World!", "service": "Lion API"}


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/hello/{name}")
def hello(name: str):
    """Greet a user by name."""
    return {"message": f"Hello, {name}!"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
