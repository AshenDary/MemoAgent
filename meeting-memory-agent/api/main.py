"""FastAPI entrypoint for meeting memory agent."""

from fastapi import FastAPI

app = FastAPI(title="Meeting Memory Agent API")


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}
