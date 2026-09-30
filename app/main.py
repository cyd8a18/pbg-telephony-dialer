import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI

from .database import connect
from .processor import EventProcessor


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "dialer.sqlite3"
DEFAULT_LEAD_BOOK = PROJECT_ROOT / "lead_book.json"

app = FastAPI(title="Telephony Dialer State Prototype")


def get_processor() -> EventProcessor:
    db_path = Path(os.getenv("DIALER_DB_PATH", DEFAULT_DB_PATH))
    lead_book_path = Path(os.getenv("LEAD_BOOK_PATH", DEFAULT_LEAD_BOOK))
    conn = connect(db_path)
    try:
        yield EventProcessor(conn, lead_book_path)
    finally:
        conn.close()


@app.post("/webhooks")
def receive_webhook(
    payload: dict[str, Any], processor: EventProcessor = Depends(get_processor)
) -> dict[str, Any]:
    return processor.process(payload).dict()


@app.get("/state")
def state(processor: EventProcessor = Depends(get_processor)) -> dict[str, Any]:
    return processor.state()
