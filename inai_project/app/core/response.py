# app/core/response.py
from fastapi.responses import JSONResponse

def success_response(msg: str, data: dict = None):
    """
    Standard success response.
    Only include 'data' if provided.
    """
    content = {
        "status": True,
        "message": msg
    }
    if data is not None:
        content["data"] = data

    return JSONResponse(
        status_code=200,
        content=content
    )

def error_response(error: str, message: str, status_code: int):
    """
    Standard error response
    """
    return JSONResponse(
        status_code=status_code,
        content={
            "error": error,
            "message": message,
            "status_code": status_code
        }
    )
