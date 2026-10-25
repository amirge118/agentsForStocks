"""The committed frontend/openapi.json must match the live API — regenerate with
`python -m scripts.export_openapi` (from backend/) after changing schemas or routes."""

import pytest

from scripts.export_openapi import OPENAPI_PATH, render


@pytest.mark.integration
def test_frontend_contract_is_up_to_date() -> None:
    assert (
        OPENAPI_PATH.read_text(encoding="utf-8") == render()
    ), "frontend/openapi.json is stale — run: cd backend && python -m scripts.export_openapi"
