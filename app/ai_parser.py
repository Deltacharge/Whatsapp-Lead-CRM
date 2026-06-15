import os
import json
import logging
from datetime import datetime
import httpx

logger = logging.getLogger(__name__)

# NOTE: Do NOT capture env vars at module level — they must be read at call-time
# so that load_dotenv() in main.py has already executed.
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


async def parse_lead_from_message(
    text: str,
    sender_phone: str,
    sender_name: str,
    timestamp: str | None = None,
) -> dict:
    """
    Uses Gemini Flash to extract structured lead data from a raw WhatsApp message.
    Falls back to raw data if AI parsing fails.
    """
    prompt = f"""You are a CRM assistant. Extract structured lead information from this WhatsApp message.

Message: "{text}"
Sender Name (from WhatsApp profile): {sender_name}
Sender Phone: {sender_phone}

Return ONLY a valid JSON object with these exact keys:
{{
  "name": "the person's name — use sender name if not mentioned in message",
  "phone": "{sender_phone}",
  "topic": "what they are enquiring about in 3-6 words",
  "intent": "one of: purchase, inquiry, support, complaint, partnership, other",
  "urgency": "one of: high, medium, low — based on language cues",
  "summary": "one sentence summarising what they want",
  "raw_message": "{text.replace('"', "'")}"
}}

Return only the JSON, no markdown, no explanation."""

    try:
        gemini_api_key = os.getenv("GEMINI_API_KEY")  # Read at call-time, not import-time
        if not gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not set in environment")

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{GEMINI_URL}?key={gemini_api_key}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 300},
                },
            )
            response.raise_for_status()
            data = response.json()

        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
        # Strip markdown fences if Gemini wraps in ```json ... ```
        clean = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        lead = json.loads(clean)

        # Add metadata
        lead["timestamp"] = (
            datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d %H:%M:%S")
            if timestamp
            else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        lead["status"] = "New"
        lead["source"] = "WhatsApp"

        logger.info(f"AI parsed lead: {lead}")
        return lead

    except Exception as e:
        logger.warning(f"AI parsing failed ({e}), using fallback")
        return {
            "name": sender_name,
            "phone": sender_phone,
            "topic": "General enquiry",
            "intent": "inquiry",
            "urgency": "medium",
            "summary": text[:120],
            "raw_message": text,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "New",
            "source": "WhatsApp",
        }
