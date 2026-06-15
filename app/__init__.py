from fastapi import FastAPI
from app.sheets import setup_sheet_headers
import logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    from app.main import app

    @app.on_event("startup")
    async def startup():
        logger.info("Running startup: setting up sheet headers...")
        await setup_sheet_headers()

    return app