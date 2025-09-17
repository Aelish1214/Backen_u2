# app/core/sms_utils.py
import boto3
from botocore.exceptions import ClientError, BotoCoreError
from fastapi import HTTPException
import os

def send_sms_otp(phone_number: str, otp: str) -> bool:
    try:
        sns = boto3.client(
            "sns",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
        )

        # Validate credentials
        sns.get_sms_attributes()  # Will raise error if credentials invalid

        message = f"Your OTP is: {otp}"
        sns.publish(PhoneNumber=phone_number, Message=message)
        return True
    except (BotoCoreError, ClientError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to send OTP SMS: {str(e)}")
