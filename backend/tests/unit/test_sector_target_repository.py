from decimal import Decimal

import pytest

from app.repositories.sector_targets import SectorTargetRepository


@pytest.mark.unit
async def test_targets_are_replaced_as_a_set(db_session) -> None:
    repo = SectorTargetRepository(db_session)
    assert await repo.all() == {}
    await repo.replace({"Technology": Decimal("40"), "Energy": Decimal("10")})
    await db_session.commit()
    await repo.replace({"Technology": Decimal("35.5")})
    await db_session.commit()
    assert await repo.all() == {"Technology": Decimal("35.5")}
