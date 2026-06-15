import os
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# NOTE: env vars are intentionally NOT captured at module level.
# They are read inside each function after load_dotenv() has already run.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Column order in the sheet (must match header row)
COLUMNS = [
    "timestamp",
    "name",
    "phone",
    "topic",
    "intent",
    "urgency",
    "summary",
    "raw_message",
    "status",
    "source",
]


def _get_sheets_service():
    service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "config/service_account.json")
    creds = service_account.Credentials.from_service_account_file(
        service_account_file, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)


async def setup_sheet_headers():
    """
    Creates the header row if the sheet is empty.
    Called once on startup.
    """
    spreadsheet_id = os.getenv("GOOGLE_SHEET_ID")
    sheet_name = os.getenv("GOOGLE_SHEET_NAME", "Leads")

    try:
        service = _get_sheets_service()
        sheet = service.spreadsheets()

        # Check if headers already exist
        result = sheet.values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A1:J1",
        ).execute()

        if result.get("values"):
            logger.info("Sheet headers already exist")
            return

        # Write headers
        headers = [col.replace("_", " ").title() for col in COLUMNS]
        sheet.values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A1",
            valueInputOption="RAW",
            body={"values": [headers]},
        ).execute()

        # Bold + freeze the header row
        sheet_id = _get_sheet_id(service, sheet_name)
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "repeatCell": {
                            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                            "cell": {
                                "userEnteredFormat": {
                                    "textFormat": {"bold": True},
                                    "backgroundColor": {"red": 0.2, "green": 0.6, "blue": 0.4},
                                }
                            },
                            "fields": "userEnteredFormat(textFormat,backgroundColor)",
                        }
                    },
                    {
                        "updateSheetProperties": {
                            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                            "fields": "gridProperties.frozenRowCount",
                        }
                    },
                ]
            },
        ).execute()
        logger.info("Sheet headers created and formatted")

    except HttpError as e:
        logger.error(f"Failed to setup sheet headers: {e}")


def _get_sheet_id(service, sheet_name: str) -> int:
    spreadsheet_id = os.getenv("GOOGLE_SHEET_ID")
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for s in meta["sheets"]:
        if s["properties"]["title"] == sheet_name:
            return s["properties"]["sheetId"]
    return 0


async def append_lead_to_sheet(lead: dict):
    """Appends a single lead row to the Google Sheet."""
    spreadsheet_id = os.getenv("GOOGLE_SHEET_ID")
    sheet_name = os.getenv("GOOGLE_SHEET_NAME", "Leads")

    if not spreadsheet_id:
        raise ValueError("GOOGLE_SHEET_ID is not set in environment")

    try:
        service = _get_sheets_service()
        row = [str(lead.get(col, "")) for col in COLUMNS]

        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A:J",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

        logger.info(f"Lead appended to sheet: {lead.get('name')} — {lead.get('topic')}")

    except HttpError as e:
        logger.error(f"Sheets API error: {e}")
        raise


async def get_all_leads() -> list[dict]:
    """
    Fetches all lead rows from the Google Sheet and returns them as a list of dicts.
    Used by the dashboard. Returns an empty list on any error.
    """
    spreadsheet_id = os.getenv("GOOGLE_SHEET_ID")
    sheet_name = os.getenv("GOOGLE_SHEET_NAME", "Leads")

    if not spreadsheet_id:
        logger.warning("GOOGLE_SHEET_ID not set — dashboard will show empty")
        return []

    try:
        service = _get_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A:J",
        ).execute()

        rows = result.get("values", [])
        if len(rows) < 2:
            return []  # only header row or empty

        headers = [h.lower().replace(" ", "_") for h in rows[0]]
        leads = []
        for row in rows[1:]:
            # Pad short rows so zip doesn't drop columns
            padded = row + [""] * (len(headers) - len(row))
            leads.append(dict(zip(headers, padded)))

        return leads

    except HttpError as e:
        logger.error(f"Failed to fetch leads for dashboard: {e}")
        return []
