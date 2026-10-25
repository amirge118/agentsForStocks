"""
Write the API contract to frontend/openapi.json (the frontend generates its
TypeScript types from it). Run from backend/:  python -m scripts.export_openapi
tests/integration/test_openapi_contract.py fails when the file is stale.
"""

import json
import logging
from pathlib import Path

from app.main import app

logger = logging.getLogger(__name__)

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    OPENAPI_PATH.write_text(render(), encoding="utf-8")
    logger.info("Wrote %s", OPENAPI_PATH)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
