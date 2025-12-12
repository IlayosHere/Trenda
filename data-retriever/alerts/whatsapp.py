import requests
import os
from dotenv import load_dotenv
import utils.display as display

load_dotenv()


def send_whatsapp_message(text, to_numbers=None):
    TOKEN = os.getenv("WHATSAPP_TOKEN")
    PHONE_NUMBER_ID = os.getenv("PHONE_ID")

    if not TOKEN or not PHONE_NUMBER_ID:
        raise ValueError("Missing WHATSAPP_TOKEN or PHONE_ID")

    if to_numbers is None:
        to_numbers = os.getenv("TO_PHONE", "").split(",")

    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }

    for number in to_numbers:
        number = number.strip()
        if not number:
            continue
        payload = {
            "messaging_product": "whatsapp",
            "to": number,
            "type": "text",
            "text": {"body": text}
        }
        response = requests.post(url, json=payload, headers=headers)
        display.print_status(f"{number} | {response.status_code} | {response.text}")
