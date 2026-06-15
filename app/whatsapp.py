import os
import logging
import httpx

logger = logging.getLogger(__name__)

# NOTE: env vars read at call-time inside function, not at import-time.


async def send_whatsapp_message(to: str, text: str) -> dict:
    """
    Sends a text reply via WhatsApp Cloud API.
    `to` must be a phone number with country code, no '+' (e.g. 919876543210).
    """
    WA_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
    WA_PHONE_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    WA_API_URL = f"https://graph.facebook.com/v19.0/{WA_PHONE_ID}/messages"

    if not WA_TOKEN or not WA_PHONE_ID:
        logger.warning("WhatsApp credentials not set — skipping reply")
        return {}

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            WA_API_URL,
            headers={
                "Authorization": f"Bearer {WA_TOKEN}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if response.status_code != 200:
        logger.error(f"WhatsApp send failed: {response.status_code} — {response.text}")
    else:
        logger.info(f"WhatsApp reply sent to {to}")

    return response.json()
