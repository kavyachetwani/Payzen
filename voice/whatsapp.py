"""One-way WhatsApp message sender for escalation agent messages.

Uses the WhatsApp Business Cloud API to deliver agent messages to a
test recipient phone number. Requires WHATSAPP_PHONE_NUMBER_ID,
WHATSAPP_ACCESS_TOKEN, and WHATSAPP_TEST_RECIPIENT in .env.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()


def send_whatsapp(text: str) -> bool:
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    token = os.environ.get("WHATSAPP_ACCESS_TOKEN")
    recipient = os.environ.get("WHATSAPP_TEST_RECIPIENT")

    if not all([phone_id, token, recipient]):
        print("WhatsApp not configured")
        return False

    try:
        resp = requests.post(
            f"https://graph.facebook.com/v25.0/{phone_id}/messages",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "text",
                "text": {"body": text},
            },
            timeout=10,
        )
        if resp.status_code == 200:
            print(f"WhatsApp sent: {text[:50]}...")
            return True
        else:
            print(f"WhatsApp failed: HTTP {resp.status_code} {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"WhatsApp failed: {e}")
        return False
