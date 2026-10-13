"""HTTP-слой. Наружу: GET / и /api/clients — результат; /api/sync — принудительная синхронизация; /api/health."""
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from .service import SyncService, Unavailable

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
service = SyncService()

_HEADERS = {
    "Cache-Control": "no-store",
    "Access-Control-Allow-Origin": "*",
    "X-Content-Type-Options": "nosniff",
}
_JSON = "application/json; charset=utf-8"


def _json(data, status: int = 200) -> Response:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return Response(body, status_code=status, media_type=_JSON, headers=_HEADERS)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await run_in_threadpool(service.startup)
    yield


# Документация и схема не нужны снаружи — меньше поверхности.
app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.api_route("/", methods=["GET", "HEAD"])
@app.api_route("/api/clients", methods=["GET", "HEAD"])
async def clients():
    try:
        body = await run_in_threadpool(service.body)
    except Unavailable:
        return _json({"error": "source unavailable, no data yet"}, 503)
    return Response(body, media_type=_JSON, headers=_HEADERS)


@app.api_route("/api/sync", methods=["GET", "POST"])
async def sync():
    return _json(await run_in_threadpool(service.force_sync))


@app.api_route("/api/health", methods=["GET", "HEAD"])
async def health():
    return _json(service.health())


@app.exception_handler(StarletteHTTPException)
async def http_error(_request: Request, exc: StarletteHTTPException):
    return _json({"error": exc.detail if isinstance(exc.detail, str) else "error"}, exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _exc: RequestValidationError):
    return _json({"error": "bad request"}, 400)


@app.exception_handler(Exception)
async def unhandled(_request: Request, _exc: Exception):
    logging.getLogger("app").exception("unhandled error")
    return _json({"error": "internal error"}, 500)
