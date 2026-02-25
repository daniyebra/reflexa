import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from reflexa.api.middleware import RequestLoggingMiddleware
from reflexa.api.routers import artifacts, chat, eval, sessions
from reflexa.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Reflexa",
        description="LLM-based language learner feedback research platform",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost", "http://127.0.0.1"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)

    app.include_router(sessions.router)
    app.include_router(chat.router)
    app.include_router(artifacts.router)
    app.include_router(eval.router)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        if errors:
            first = errors[0]
            loc = first.get("loc", [])
            field = ".".join(
                str(part) for part in loc if part not in ("body", "query", "path")
            ) or None
            message = first.get("msg", "Validation error")
        else:
            field = None
            message = "Validation error"
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "validation_error", "message": message, "field": field}},
        )

    @app.get("/health", tags=["ops"])
    async def health():
        from reflexa.db.engine import engine
        from sqlalchemy import text

        db_status = "ok"
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            db_status = "error"

        llm_status = "mock" if settings.is_mock else "live"
        return {"status": "ok", "db": db_status, "llm": llm_status}

    return app


app = create_app()
