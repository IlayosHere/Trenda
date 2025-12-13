import requests
import os
from dotenv import load_dotenv

load_dotenv()


def renew_long_lived_token():
    URL = "https://graph.facebook.com/v20.0/oauth/access_token"

    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    short_lived_token = os.getenv("WHATSAPP_SHORT_LIVED_TOKEN")

    if not client_id or not client_secret or not short_lived_token:
        raise ValueError("CLIENT_ID, CLIENT_SECRET, or WHATSAPP_SHORT_LIVED_TOKEN missing")

    params = {
        "grant_type": "fb_exchange_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "fb_exchange_token": short_lived_token
    }

    response = requests.get(URL, params=params)
    data = response.json()

    if "access_token" not in data:
        raise RuntimeError(f"Failed to refresh token: {data}")

    return data["access_token"], data.get("expires_in")
