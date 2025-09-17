from google.oauth2 import id_token
from google.auth.transport import requests
import requests as http_requests

GOOGLE_CLIENT_ID = "96767928697-96dhp159kitbc68bat0om3vobkk80lpv.apps.googleusercontent.com"

def get_email_from_google_token(token: str) -> str:
    try:
        id_info = id_token.verify_oauth2_token(token, requests.Request(), GOOGLE_CLIENT_ID)
        return id_info.get("email")
    except Exception:
        return None


def get_email_from_facebook_token(token: str) -> str:
    try:
        debug_url = f"https://graph.facebook.com/me?fields=email&access_token={token}"
        response = http_requests.get(debug_url)
        if response.status_code == 200:
            return response.json().get("email")
    except Exception:
        pass
    return None
