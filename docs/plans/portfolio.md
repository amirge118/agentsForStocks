# Portfolio page: a ledger of transactions, cash, and the agents' view of it

**Goal:** see at any moment what I hold, what it is worth, how it does against the market, what the
risks are, and what the agents recommend for each holding and for the portfolio as a whole.

**Decisions (2026-11-15):** a new capability in this app, not a copy of `stocky` (only its feature
list is an inspiration). USD only. Average cost. A buy without enough cash is refused. The
existing portfolio enters as opening positions plus a cash balance. Local first; a server once it
has worked for a few weeks.

## The model: a ledger, everything else derived

One table, `portfolio_transactions`. Holdings, cash, cost basis and returns are computed from it,
never stored, so they can't disagree with it. Correcting a mistake = editing or deleting a row.

| kind | symbol | shares | price | fee | cash effect | holdings effect |
|---|---|---|---|---|---|---|
| `DEPOSIT` | — | — | — | — | + amount | — |
| `WITHDRAW` | — | — | — | — | − amount | — |
| `BUY` | ✓ | ✓ | ✓ | ✓ | − shares × price − fee | + shares |
| `SELL` | ✓ | ✓ | ✓ | ✓ | + shares × price − fee | − shares, realised P/L |
| `DIVIDEND` | ✓ | — | — | — | + amount | — |
| `TRANSFER_IN` | ✓ | ✓ | cost/share | — | none | + shares at that cost (opening positions) |

Columns: `id`, `trade_date`, `kind`, `symbol` (nullable), `shares`, `price`, `fee`, `amount`,
`note`, `created_at`. Amounts as `Numeric`, not float: this is money.

Rules, enforced on write (replaying the ledger up to the new row's date):
- a `SELL` can't exceed the shares held on that day;
- a `BUY` or `WITHDRAW` can't take cash below 0 on that day ("record a deposit first");
- editing or deleting an earlier row is refused when a later row would then break a rule;
- shares and prices > 0, a symbol passes `validate_symbol`, the trade date isn't in the future.

Average cost: a buy raises the cost basis by shares × price + fee; a sell removes
shares × average cost and books realised P/L = proceeds − fee − that cost.

A symbol held is added to the watchlist, so the agents analyse it from the next run. Selling out
doesn't remove it (the person decides).

## Returns: time-weighted, against SPY

Deposits, withdrawals and transfers-in are external flows, not performance. The time-weighted
return chains the daily returns between flows, so it compares fairly with SPY: the same benchmark
the agents' outcomes use. Daily values come from the stored daily closes (see Market data).

## The page (`/`; the current watchlist moves to `/watchlist`)

1. **Summary:**
   - total assets (holdings + cash) and the total cost put in;
   - P/L: unrealised and realised, in dollars and percent;
   - today and this week, in dollars and percent. The week runs from the last close of the previous
     week; deposits and withdrawals in between are taken out, so a deposit isn't shown as a gain;
   - cash and its share of the portfolio;
   - time-weighted return since the start vs SPY.
2. **This week's movers:** the three biggest gainers and losers among the holdings, in percent and
   dollars, each with the agents' current action.
3. **Value over time:** the portfolio's time-weighted return against SPY (1M / 3M / YTD / all).
4. **Positions:** shares, price, value, weight, P/L, today's and the week's change, and the agents'
   latest action, score, confidence and date for that symbol; cash as the last row.
5. **Sectors:** each sector's share of the portfolio, cash as its own row. Optionally a target per
   sector; the page then shows the drift ("Technology 54%, target 40%, +14 pts"). The sector comes
   from the `broad_analysis` result (`sector`); a fund counts as "Fund". Targets live in a small
   `sector_targets` table and don't have to add up to 100.
6. **Risk:** largest position, cash share, beta-weighted portfolio beta (beta from the risk agent),
   drawdown from the peak, symbols whose daily returns move together.
7. **The agents against the portfolio:** the share of the portfolio in each action, actions that
   changed since the previous run, holdings rated SELL. Computed in code, not by a model.
8. **Transactions:** the ledger, newest first, with edit and delete; one form for every kind, with
   the rules' messages as form errors.

Prices are live (see Market data); recommendations are daily and always shown with their date.

## Market data: fetch each figure once

What exists: `TTLCache` (`app/providers/cache.py`) de-duplicates concurrent requests for the same
key, so ten panels asking at once make one call; per-domain rate limits, retries, and the FMP
budget kept in the database. What the page needs on top, partly taken from `stocky`
(`backend/app/core/cache.py`, `services/price_service.py`):

- **A TTL per kind.** Every provider result lived 6 hours (`provider_cache_ttl_seconds`): right
  for the agents, wrong for a live price. Quotes: 60 seconds while the market is open, 30 minutes
  while it is closed (holidays aren't known, so not "until the next open"). Statements and company
  data: 6 hours, as before. Daily closes: never expire. Done in 1b.
- **Daily closes stored in the database.** A `daily_closes` table (symbol, day, close). The chart,
  the week's change and the time-weighted return read it; only missing days are fetched. A past
  close never changes, so after the first load a day costs one request per symbol at most. Use
  closes adjusted for splits but not for dividends (yfinance `auto_adjust=False`, `Close`): the
  ledger records dividends as cash, and dividend-adjusted prices would count them twice.
- **One request for all holdings.** `yfinance.download` for every held symbol at once, through
  `YFinanceClient` (its rate limit and cache), not FMP: its 250 free calls a day stay with the agents.
- **The last good price when the source fails** (`stocky` keeps a 24-hour stale copy): show it with
  its time and a "stale" mark; never 0, never empty.
- **A bounded cache.** `TTLCache` gets a TTL per call, drops expired entries and caps its size;
  today an expired entry stays in memory until overwritten.
- **Redis only with several API processes.** It shares a cache between processes; here the agents
  run in the worker at night and the page in the API, so there is nothing to share yet, and it
  would be one more service to run. `get_or_load` stays the one interface, so a Redis-backed cache
  can replace it without touching the providers.

## Privacy

Amounts stay in the local database. They never reach a prompt (the free Gemini tier may use
prompts; a test asserts no prompt contains them) or a log line, and never the repository: it is
public. PR screenshots use the E2E mocks.

## Steps (each its own PR)

1. **Ledger, cash and market data** (two PRs: 1a the ledger and its API, 1b the market data). Migration, model, repository, the replay (pure functions in
   `app/domain/portfolio.py`: positions, cash, realised P/L, the write rules), and
   `GET/POST/PUT/DELETE /api/v1/portfolio/transactions`, `GET /api/v1/portfolio`; `daily_closes`,
   the TTL per kind, the bounded cache, the batched quote with a stale fallback. Most of the tests
   live here: table-driven ledgers with known results, every refused write, a round trip.
2. **The page.** Summary (total, P/L, today), positions with the agents' view, the transaction form
   and list; the watchlist moves to `/watchlist`. Done 2026-11-15; editing an entry from the page waits
   (delete and record it again).
3. **Performance.** The week, this week's movers, time-weighted return, the chart against SPY.
   Done 2026-11-15: `GET /api/v1/portfolio/performance` (`app/domain/performance.py`). Flows
   count at the session's close (transfers in at that close, not at their old cost); the first
   missing stretch of closes is fetched in one `yf.download` and stored, later views read the
   table. The week's movers value the move for the shares held now.
4. **Sectors, risk and the agents' view.** Sector weights and targets (`sector_targets`), the risk
   figures, the action exposure, the "moves together" groups from daily returns.
   Done 2026-11-15: `GET /api/v1/portfolio/exposure`, `PUT /api/v1/portfolio/sector-targets`
   (`app/domain/exposure.py`). Everything comes from what the agents already stored (sector from
   `broad_analysis`, beta from `risk`, the call and the one before from `recommendation`; a symbol
   with technicals but no recommendation is a fund) and from `daily_closes` (pairs correlating at
   0.8 or more over the last 60 sessions); no extra model or FMP call. A missing beta is left out
   and its coverage shown, never counted as 0. The drawdown is read from the performance series.
5. **A server,** once this has worked locally for a few weeks: `docs/deploy.md` with the daily
   backup on and copied off the machine. From then on the ledger is the one thing that must not be
   lost.

Not now: other currencies, FIFO / tax lots, splits (yfinance's adjusted prices don't fix a
ledger's share counts; add a `SPLIT` kind when the first one happens), several accounts, imports
from a broker's file.
