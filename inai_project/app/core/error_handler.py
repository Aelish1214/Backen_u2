# app/core/error_handler.py
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError, HTTPException
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_404_NOT_FOUND,
)
from passlib.exc import UnknownHashError


# ✅ Common response function — always returns only {"error": "..."}
def error_response(message: str, status_code: int):
    return JSONResponse(
        status_code=status_code,
        content={"error": message}
    )


# ✅ Custom Exceptions
class UserAlreadyExistsException(Exception):
    def __init__(self, message="User already exists"):
        self.message = message


class UsernameTakenException(Exception):
    def __init__(self, message="Username already taken"):
        self.message = message


class InvalidTokenException(Exception):
    def __init__(self, message="Invalid OTP"):
        self.message = message


class InvalidOrExpiredTokenException(Exception):
    def __init__(self, message="Invalid or expired token. Please login again."):
        self.message = message


class UserNotFoundException(Exception):
    def __init__(self, message="User not found"):
        self.message = message


class EmailTakenException(Exception):
    def __init__(self, message="Email already taken"):
        self.message = message


class EmailNotVerifiedException(Exception):
    def __init__(self, message="Please verify your email before logging in."):
        self.message = message


class PhoneTakenException(Exception):
    def __init__(self, message="Phone number already taken"):
        self.message = message


class InvalidCredentialsException(Exception):
    def __init__(self, message="Invalid email or password"):
        self.message = message


class PhotoNotUploadedException(Exception):
    def __init__(self, message="Profile photo not uploaded"):
        self.message = message


class InvalidGenderException(Exception):
    def __init__(self, message="Gender must be male or female"):
        self.message = message


class OTPExpiredException(Exception):
    def __init__(self, message="OTP has expired. Please request a new one."):
        self.message = message


class NoOTPException(Exception):
    def __init__(self, message="No OTP found. Please request a new one."):
        self.message = message


class IncorrectOldPasswordException(Exception):
    def __init__(self, message="Old password is incorrect"):
        self.message = message


class PasswordMismatchException(Exception):
    def __init__(self, message="New passwords do not match"):
        self.message = message


class UnsupportedFileFormatException(Exception):
    def __init__(self, message="Unsupported file format"):
        self.message = message


# ✅ Validation Error Handler
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if exc.errors():
        err = exc.errors()[0]
        msg = err['msg']
        if msg.lower().startswith("value error, "):
            msg = msg[len("Value error, "):]
        full_msg = msg
    else:
        full_msg = "Validation error"
    return error_response(full_msg, HTTP_400_BAD_REQUEST)


# ✅ Internal Server Error Handler
async def internal_server_error_handler(request: Request, exc: Exception):
    return error_response("Internal server error. Please try again later.", HTTP_500_INTERNAL_SERVER_ERROR)


# ✅ Custom Exception Handlers
async def user_already_exists_handler(request: Request, exc: UserAlreadyExistsException):
    return error_response(exc.message, HTTP_400_BAD_REQUEST)


async def invalid_otp_handler(request: Request, exc: InvalidTokenException):
    return error_response(exc.message, HTTP_400_BAD_REQUEST)


async def invalid_or_expired_token_handler(request: Request, exc: InvalidOrExpiredTokenException):
    return error_response(exc.message, HTTP_400_BAD_REQUEST)


async def user_not_found_handler(request: Request, exc: UserNotFoundException):
    return error_response(exc.message, HTTP_404_NOT_FOUND)


async def username_taken_handler(request: Request, exc: UsernameTakenException):
    return error_response(exc.message, HTTP_400_BAD_REQUEST)


async def email_taken_handler(request: Request, exc: EmailTakenException):
    return error_response(exc.message, HTTP_400_BAD_REQUEST)


async def email_not_verified_handler(request: Request, exc: EmailNotVerifiedException):
    return error_response(exc.message, HTTP_400_BAD_REQUEST)


async def phone_taken_handler(request: Request, exc: PhoneTakenException):
    return error_response(exc.message, HTTP_400_BAD_REQUEST)


async def invalid_credentials_handler(request: Request, exc: InvalidCredentialsException):
    return error_response(exc.message, HTTP_400_BAD_REQUEST)


async def photo_not_uploaded_handler(request: Request, exc: PhotoNotUploadedException):
    return error_response(exc.message, HTTP_400_BAD_REQUEST)


async def invalid_gender_handler(request: Request, exc: InvalidGenderException):
    return error_response(exc.message, HTTP_400_BAD_REQUEST)


async def otp_expired_handler(request: Request, exc: OTPExpiredException):
    return error_response(exc.message, HTTP_400_BAD_REQUEST)


async def no_otp_handler(request: Request, exc: NoOTPException):
    return error_response(exc.message, HTTP_400_BAD_REQUEST)


async def incorrect_old_password_handler(request: Request, exc: IncorrectOldPasswordException):
    return error_response(exc.message, HTTP_400_BAD_REQUEST)


async def password_mismatch_handler(request: Request, exc: PasswordMismatchException):
    return error_response(exc.message, HTTP_400_BAD_REQUEST)


async def unsupported_file_format_handler(request: Request, exc: UnsupportedFileFormatException):
    return error_response(exc.message, HTTP_400_BAD_REQUEST)


async def unknown_hash_error_handler(request: Request, exc: UnknownHashError):
    return error_response(
        "Password hash is invalid or corrupted. Please reset your password.",
        HTTP_400_BAD_REQUEST
    )


# ✅ HTTPException handler (no detail, only error)
async def http_exception_handler(request: Request, exc: HTTPException):
    message = str(exc.detail) if exc.detail else "An error occurred"
    return error_response(message, exc.status_code)
