# app/core/email_utils.py

import os
from pathlib import Path
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from pydantic import EmailStr
from dotenv import load_dotenv

# ✅ Load env variables
load_dotenv()

# ✅ Email configuration
conf = ConnectionConfig(
    MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_FROM=os.getenv("MAIL_FROM"),
    MAIL_PORT=int(os.getenv("MAIL_PORT", 587)),
    MAIL_SERVER=os.getenv("MAIL_SERVER"),
    MAIL_FROM_NAME=os.getenv("MAIL_FROM_NAME", "INAI"),
    MAIL_STARTTLS=os.getenv("MAIL_STARTTLS", "True").lower() == "true",
    MAIL_SSL_TLS=os.getenv("MAIL_SSL_TLS", "False").lower() == "true",
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True
)

async def send_email_otp(
    email: EmailStr,
    otp: str,
    purpose: str = "signup",
    user_name: str | None = None
):
    # ✅ Email content based on purpose
    if purpose == "signup":
        subject = "Verify Your Email - INAI"
        greeting = f"Hello {user_name}," if user_name else "Hello there,"
        intro = "Welcome to <b>INAI</b>! Please verify your email to activate your account."
    elif purpose == "email_change":
        subject = "Confirm Your New Email - INAI"
        greeting = f"Hello {user_name}," if user_name else "Hello there,"
        intro = "You requested to update your email address on <b>INAI</b>. Please confirm this change."
    elif purpose == "password_reset":
        subject = "Reset Your Password - INAI"
        greeting = f"Hello {user_name}," if user_name else "Hello there,"
        intro = "We received a request to reset your <b>INAI</b> account password. Use the code below to continue."
    else:
        subject = "INAI Verification Code"
        greeting = f"Hello {user_name}," if user_name else "Hello there,"
        intro = "Here is your secure verification code."

    # ✅ Inline HTML body without image logo
    message_body = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <title>{subject}</title>
    </head>
    <body style="margin:0; padding:0; background:#ffffff; font-family:Arial, Helvetica, sans-serif;">

    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="padding:30px 0; background:#f0f2f5;">
      <tr>
        <td align="center">

          <table cellpadding="0" cellspacing="0" border="0"
              style="background:#ffffff; border-radius:10px; box-shadow:0 4px 12px rgba(0,0,0,0.15); 
                     padding:25px; max-width:600px; width:100%;">

            <!-- Text Logo -->
            <tr>
              <td align="center" style="padding-bottom:20px;">
                <h1 style="margin:0; font-size:24px; color:#2563eb; letter-spacing:2px;">INAI</h1>
              </td>
            </tr>

            <!-- Greeting -->
            <tr>
              <td style="text-align:left; font-size:15px; color:#333333; padding-bottom:12px;">
                {greeting}
              </td>
            </tr>

            <!-- Intro -->
            <tr>
              <td style="text-align:left; font-size:13px; color:#000000; padding-bottom:20px;">
                <p style="margin:0 0 16px 0;">{intro}</p>
                <p style="margin:0;">Your One-Time Password (OTP) is here:</p>
              </td>
            </tr>

            <!-- OTP Box -->
            <tr>
              <td align="center" style="padding:25px 0;">
                <div style="
                  font-size:28px; 
                  font-weight:bold; 
                  color:#2563eb; 
                  background:#f1f5f9; 
                  padding:18px 55px; 
                  border-radius:8px; 
                  display:inline-block; 
                  letter-spacing:6px; 
                  box-shadow:0 4px 20px rgba(37,99,235,0.35); 
                  text-shadow:1px 1px 10px rgba(37,99,235,0.3);
                ">
                  {otp}
                </div>
              </td>
            </tr>

            <!-- Expiry Note -->
            <tr>
              <td style="padding:10px 20px; text-align:center; font-size:14px; color:#555555;">
                <p style="margin:0 0 8px 0;">This OTP will expire in <b>60 seconds.</b></p>
                <p style="margin:0;">For your security, do not share it with anyone.</p>
              </td>
            </tr>

            <!-- Security Tip -->
            <tr>
              <td style="padding:18px 20px 0; text-align:center; font-size:13px; color:#444444; border-top:1px solid #e5e5e5;">
                <p style="margin:0 0 8px 0;"><b>Security Tip:</b> Never share your OTP with anyone. INAI will never ask for it.</p>
                <p style="margin:0;">If you did not request this, please ignore this email.</p>
                <p style="margin:8px 0 0 0;">If any problem, contact us at 
                <a href="mailto:help@inaiworlds.com" style="color:#1a73e8; text-decoration:none;">help@inaiworlds.com</a>
                </p>
              </td>
            </tr>

          </table>

        </td>
      </tr>
    </table>

    </body>
    </html>
    """

    # ✅ Send the email (no attachments now)
    message = MessageSchema(
        subject=subject,
        recipients=[email],
        body=message_body,
        subtype=MessageType.html,
    )

    fm = FastMail(conf)
    await fm.send_message(message)