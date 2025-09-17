import os
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
print("Loaded SECRET_KEY:", os.getenv("SECRET_KEY"))

# Logger
from app.logger import Logger
logger = Logger()

# Models and DB
from inai_project.database import SessionLocal, engine, Base
from inai_project.app.signup import models as signup_models
from inai_project.app.login import models as login_models

# Routers
from inai_project.app.signup.auth_routes import router as signup_router
from inai_project.app.profile.routes import router as profile_router
from inai_project.app.gender.routes import router as gender_router
from inai_project.app.login.routes import router as login_router
from inai_project.app.email.routes import router as email_router
from inai_project.app.change_password.routes import router as change_password_router
from inai_project.app.history.history_routes import router as history_router
from inai_project.app.logout.routes import router as logout_router
from inai_project.app.tokenizer.token_routes import router as tokenizer_router


# Custom Exceptions and Handlers
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from passlib.exc import UnknownHashError
from inai_project.app.core import error_handler

from inai_project.app.core.error_handler import (
    validation_exception_handler,
    internal_server_error_handler,
    invalid_otp_handler,
    user_already_exists_handler,
    username_taken_handler,
    email_taken_handler,
    email_not_verified_handler,
    phone_taken_handler,
    photo_not_uploaded_handler,
    invalid_credentials_handler,
    invalid_gender_handler,
    otp_expired_handler,
    no_otp_handler,
    incorrect_old_password_handler,
    user_not_found_handler,
    password_mismatch_handler,
    invalid_or_expired_token_handler,
    unsupported_file_format_handler,
    # Custom Exceptions
    UnsupportedFileFormatException,
    InvalidOrExpiredTokenException,
    InvalidTokenException,
    UserAlreadyExistsException,
    UsernameTakenException,
    EmailTakenException,
    EmailNotVerifiedException,
    PhoneTakenException,
    InvalidCredentialsException,
    PhotoNotUploadedException,
    InvalidGenderException,
    NoOTPException,
    OTPExpiredException,
    IncorrectOldPasswordException,
    UserNotFoundException,
    PasswordMismatchException,
    http_exception_handler,
    InvalidCredentialsException,
    invalid_credentials_handler,
)
from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from inai_project.database import get_db
from inai_project.app.signup.models import User


app = FastAPI()

@app.get("/users/")
def read_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return users


# History manager
from inai_project.app.history.history_manager import HistoryManager
from starlette.exceptions import HTTPException as StarletteHTTPException
from inai_project.app.core import error_handler
class AuthApplication:
    def __init__(self):
        self.app = FastAPI(
            title="INAI FastAPI Auth API",
            description="Signup, Login, JWT, Phone OTP, Profile Upload with JWT",
            version="1.0.0"
        )
        self.history_manager = self.setup_history_manager()
        self.create_tables()
        self.test_db_connection()
        self.register_exception_handlers()
        self.register_routes()

    def setup_history_manager(self):
        return HistoryManager(
            db_url=os.getenv("DATABASE_URL"),
            bucket_name=os.getenv("AWS_BUCKET_NAME"),
            aws_access_key=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region=os.getenv("AWS_REGION"),
            logger=logger
        )

    def create_tables(self):
        signup_models.Base.metadata.create_all(bind=engine)
        login_models.Base.metadata.create_all(bind=engine)

    def test_db_connection(self):
        try:
            db = SessionLocal()
            db.execute(text("SELECT 1"))
            print("✅ PostgreSQL Connected Successfully!")
        except OperationalError as e:
            print("❌ PostgreSQL Connection Failed:", e)
        finally:
            db.close()

    def register_exception_handlers(self):
        self.app.add_exception_handler(RequestValidationError, validation_exception_handler)
        self.app.add_exception_handler(Exception, internal_server_error_handler)
        self.app.add_exception_handler(InvalidTokenException, invalid_otp_handler)
        self.app.add_exception_handler(UserAlreadyExistsException, user_already_exists_handler)
        self.app.add_exception_handler(UsernameTakenException, username_taken_handler)
        self.app.add_exception_handler(EmailTakenException, email_taken_handler)
        self.app.add_exception_handler(EmailNotVerifiedException, email_not_verified_handler)
        self.app.add_exception_handler(PhoneTakenException, phone_taken_handler)
        self.app.add_exception_handler(InvalidCredentialsException, invalid_credentials_handler)
        self.app.add_exception_handler(PhotoNotUploadedException, photo_not_uploaded_handler)
        self.app.add_exception_handler(InvalidGenderException, invalid_gender_handler)
        self.app.add_exception_handler(OTPExpiredException, otp_expired_handler)
        self.app.add_exception_handler(NoOTPException, no_otp_handler)
        self.app.add_exception_handler(IncorrectOldPasswordException, incorrect_old_password_handler)
        self.app.add_exception_handler(UserNotFoundException, user_not_found_handler)
        self.app.add_exception_handler(PasswordMismatchException, password_mismatch_handler)
        self.app.add_exception_handler(InvalidOrExpiredTokenException, invalid_or_expired_token_handler)
        self.app.add_exception_handler(UnsupportedFileFormatException, unsupported_file_format_handler)
        self.app.add_exception_handler(StarletteHTTPException, http_exception_handler)
        self.app.add_exception_handler(error_handler.InvalidTokenException, error_handler.invalid_otp_handler)
        self.app.add_exception_handler(error_handler.OTPExpiredException, error_handler.otp_expired_handler)
        self.app.add_exception_handler(UnknownHashError, error_handler.unknown_hash_error_handler)
        self.app.add_exception_handler(InvalidCredentialsException, invalid_credentials_handler,)
        self.app.add_exception_handler(error_handler.UserNotFoundException, user_not_found_handler)

    def register_routes(self):
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # Allow all origins (dev only!)
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        self.app.mount("/uploads/profile_pics", StaticFiles(directory="uploads/profile_pics"), name="profile_pics")

        self.app.include_router(signup_router, prefix="/signup", tags=["Signup"])
        self.app.include_router(login_router, prefix="/login", tags=["Login"])
        self.app.include_router(profile_router, prefix="/profile", tags=["Profile"])
        self.app.include_router(gender_router, prefix="/gender", tags=["Gender"])
        self.app.include_router(email_router, prefix="/email-change", tags=["Email"])
        self.app.include_router(change_password_router, prefix="/change-password", tags=["Auth"])
        self.app.include_router(history_router, prefix="/history", tags=["History"])
        self.app.include_router(logout_router, prefix="/logout", tags=["Logout"])
        self.app.include_router(tokenizer_router, prefix="/api", tags=["Tokenizer"])

        


        @self.app.get("/")
        def root():
            return {"message": "🚀 FastAPI Auth API Running!"}

    def get_app(self):
        return self.app
