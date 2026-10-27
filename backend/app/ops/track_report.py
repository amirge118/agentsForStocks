"""Track record of every agent from the settled outcomes (`python -m scripts.track_report`)."""

from app.domain.outcomes import AgentTrack, TrackStats


def _rate(stats: TrackStats) -> str:
    return "—" if stats.hit_rate is None else f"{stats.hit_rate * 100:.0f}%"


def _alpha(stats: TrackStats) -> str:
    alpha = stats.mean_alpha_captured
    return "—" if alpha is None else f"{alpha * 100:+.2f}%"


def render_track_record(tracks: list[AgentTrack], horizon: int, pending: int) -> str:
    title = f"Track record — {horizon} trading days after each call, vs the benchmark"
    if not tracks:
        return f"{title}\n\nNo settled calls yet ({pending} outcomes pending)."
    header = (
        f"{'agent':<18} {'calls':>6} {'hit':>5} {'alpha':>8}   "
        f"{'bullish':>13} {'neutral':>13} {'bearish':>13}"
    )
    lines = [title, "", header, "-" * len(header)]
    for t in tracks:
        cells = []
        for signal in ("bullish", "neutral", "bearish"):
            s = t.by_signal.get(signal)
            cells.append(f"{_rate(s)} of {s.calls}" if s else "—")
        lines.append(
            f"{t.agent[:18]:<18} {t.overall.calls:>6} {_rate(t.overall):>5} "
            f"{_alpha(t.overall):>8}   {cells[0]:>13} {cells[1]:>13} {cells[2]:>13}"
        )
    lines += ["", f"{pending} outcomes still pending (their windows have not fully traded)."]
    return "\n".join(lines)
