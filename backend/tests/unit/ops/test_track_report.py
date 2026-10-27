import pytest

from app.domain.outcomes import AgentTrack, TrackStats
from app.ops.track_report import render_track_record


@pytest.mark.unit
def test_render_track_record() -> None:
    assert "No settled calls yet (4 outcomes pending)" in render_track_record([], 20, 4)
    tracks = [
        AgentTrack(
            "recommendation",
            TrackStats(4, 3, 0.0125),
            {"bullish": TrackStats(3, 3, 0.02), "bearish": TrackStats(1, 0, -0.01)},
            {},
        ),
        AgentTrack("moat", TrackStats(1, 0, None), {}, {}),
    ]
    text = render_track_record(tracks, 20, 2)
    rows = text.splitlines()
    assert rows[0].startswith("Track record — 20 trading days")
    rec = next(r for r in rows if r.startswith("recommendation"))
    assert rec.split()[:4] == ["recommendation", "4", "75%", "+1.25%"]
    assert "100% of 3" in rec and "0% of 1" in rec
    moat = next(r for r in rows if r.startswith("moat"))
    assert moat.split()[:4] == ["moat", "1", "0%", "—"]
    assert rows[-1] == "2 outcomes still pending (their windows have not fully traded)."
