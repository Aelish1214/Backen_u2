from prometheus_client import Counter, Summary, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError

# Metrics
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint'])
REQUEST_LATENCY = Summary('http_request_duration_seconds', 'Request latency', ['method', 'endpoint'])
ERROR_COUNT = Counter('http_errors_total', 'Total HTTP errors', ['method', 'endpoint', 'status_code'])

# Middleware for requests
async def metrics_middleware(request: Request, call_next):
    method = request.method
    endpoint = request.url.path
    try:
        with REQUEST_LATENCY.labels(method=method, endpoint=endpoint).time():
            response = await call_next(request)
        REQUEST_COUNT.labels(method=method, endpoint=endpoint).inc()
        return response
    except Exception as e:
        ERROR_COUNT.labels(method=method, endpoint=endpoint, status_code=500).inc()
        return JSONResponse(
            status_code=500,
            content={"status": 500, "error": "Internal Server Error", "message": str(e)}
        )

# Handler for HTTP exceptions (like 404, 400, etc.)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    ERROR_COUNT.labels(method=request.method, endpoint=request.url.path, status_code=exc.status_code).inc()
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": exc.status_code, "message": exc.detail}
    )

# Custom handler for 400 errors (RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    ERROR_COUNT.labels(method=request.method, endpoint=request.url.path, status_code=400).inc()
    return JSONResponse(
        status_code=400,
        content={"status": 400, "message": "Bad Request", "detail": exc.errors()}
    )

# Prometheus metrics endpoint
def metrics_endpoint():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)