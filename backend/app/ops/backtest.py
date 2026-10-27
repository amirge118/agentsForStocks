"""Backtest report for `python -m scripts.backtest_weights` (docs/plans/backtest.md, part A)."""

from app.domain.backtest import ConfigResult
from app.domain.outcomes import TrackStats


def _cells(s: TrackStats) -> str:
    rate = "—" if s.hit_rate is None else f"{s.hit_rate * 100:.0f}%"
    alpha = "—" if s.mean_alpha_captured is None else f"{s.mean_alpha_captured * 100:+.2f}%"
    return f"{s.calls:>5} {rate:>5} {alpha:>8}"


def render_backtest(
    results: list[ConfigResult], llm: TrackStats, horizon: int, top: int = 10
) -> str:
    title = f"Backtest of the recommendation weights — {horizon} trading days, rule-based calls"
    if not results or results[0].fit.calls == 0:
        return f"{title}\n\nNot enough settled days yet to fit and test (needs two or more)."
    fit_n, test_n = results[0].fit.calls, results[0].test.calls
    cols = f"{'n':>5} {'right':>5} {'alpha':>8}"
    header = f"{'configuration':<34} {cols}   {cols}"
    lines = [
        title,
        f"Ranked on the first {fit_n} cases (fit), reported on the {test_n} later ones (test).",
        "",
        f"{'':<34} {'fit':^20}   {'test':^20}",
        header,
        "-" * len(header),
    ]
    current = next(r for r in results if r.config.name == "current")
    shown = [current] + [r for r in results[:top] if r is not current]
    for r in shown:
        mark = "*" if r is current else " "
        lines.append(f"{mark}{r.config.name[:33]:<33} {_cells(r.fit)}   {_cells(r.test)}")
    lines += [
        "",
        f" {'LLM recommendation (as stored)':<33} {'':>21}   {_cells(llm)}",
        "",
        "* current weights and ±15 thresholds. Change them only on a clear win on the test",
        "  cases, by enough calls to matter; the fit columns are what the ranking saw.",
    ]
    return "\n".join(lines)
