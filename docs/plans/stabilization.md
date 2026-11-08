# תוכנית ייצוב: 5 ימי מסחר של ריצות נקיות

**מטרה:** להוכיח שהאפליקציה רצה יום אחרי יום בלי התערבות, על 9 המניות שב-watchlist, לפני שחוזרים לשפר (סעיף 4 ב-`FUTURE_IMPROVEMENTS.md`).
**מה כבר עבר:** בדיקת קצה-לקצה אחת בדוקר, 2026-11-03: PASS, 70/70 (`docs/evaluation/verify-2026-11-03.json`).
**מה עוד לא הוכח:** ריצות רצופות, תזמון אוטומטי, ועמידות מול תקלות של ספקים (Gemini 503, Yahoo, FMP).

---

## תנאי סיום: כולם צריכים להתקיים

| # | תנאי | איך בודקים |
|---|---|---|
| 1 | 5 ימי מסחר רצופים עם ריצה יומית מלאה על 9 המניות: 126 ריצות סוכן ביום | שאילתת הבדיקה היומית, בלי `--force` ובלי ריצה ידנית |
| 2 | אף ריצת סוכן לא נכשלת (`failed`) בלי שה-retry של אותו יום משלים אותה | שאילתת הבדיקה היומית (`agent_runs`) |
| 3 | fallbacks (המודל לא ענה) עד 5% מהשיפוטים ביום | שאילתת הבדיקה היומית, `agent_card <agent>` |
| 4 | ‏`daily_pipeline` רץ בזמן: `completed`, בלי `missed` / `failed`. ‏`nightly_maintenance` רק מוחק לוגים ישנים: החמצה שלו נרשמת בהערות ולא מפילה את היום | `curl localhost:8000/health`, שאילתת הבדיקה היומית (`job_runs`) |
| 5 | מכסות: FMP מתחת ל-250 ביום, ועלות LLM $0 (או מתחת ל-`LLM_DAILY_BUDGET_USD`) | שאילתת הבדיקה היומית (`provider_calls`), `scripts.token_report --days 1 --by provider` |
| 6 | הדשבורד מציג את הריצה של היום לכל מניה, בלי מסכי שגיאה | פתיחה בדפדפן: `/`, `/symbols/<X>`, `/runs` |

**כשכל התנאים מתקיימים:** מסמנים `[x]` בפריט "A few days of runs in a row" ב-`FUTURE_IMPROVEMENTS.md`, מוחקים את ההערה "development paused", וחוזרים לסעיף 4.

---

## איפה מריצים

**מומלץ במחשב שלך, בדוקר:** רשת אמיתית (Yahoo לא חסום), הנתונים נשמרים בין ימים, ורואים את הדשבורד.

```bash
docker compose up -d --build          # db → migrate → api + worker → frontend
```

**שתי אפשרויות לריצה היומית:**
- **א. אוטומטית (עדיף, כי בודק גם את המתזמן):** ב-`.env` מוגדרים `SCHEDULER_ENABLED=true`, `PIPELINE_SCHEDULE=30 16 * * mon-fri` (16:30 ניו יורק, 23:30 שעון ישראל) ו-`MAINTENANCE_SCHEDULE=0 17 * * mon-fri` (00:00 שעון ישראל). חצי שעה אחרי הסגירה נשארות כמה שעות ל-retry של אותו יום, ובשעה הזו קל יותר שהמחשב יהיה ער. ריצה שמתעכבת עד שעה עוד יוצאת (`misfire_grace_time`), אחרי זה היום נחשב `missed`.
- **ב. ידנית:** רק אם הריצה האוטומטית הוחמצה, ורק אחרי סגירת המסחר (מ-23:00 שעון ישראל): `sh infra/deploy/verify.sh`. היא מריצה את כל הסוכנים על ה-watchlist ומפיקה דוח.

**שיישאר ער:** `sudo pmset repeat wakeorpoweron MTWRF 23:20:00` מעיר את המחשב בימי חול. מחובר לחשמל, ו-Docker Desktop מוגדר להיפתח בכניסה למחשב.

**מה מוגדר כבר:**
- **9 המניות** נקראות מטבלת ה-watchlist במסד הנתונים, לא מ-`WATCHLIST` ב-`.env`.
- **retry:** ריצת סוכן שנכשלה מנוסה שוב באותו יום (`PIPELINE_RETRY_*`).
- **מכסות:** `LLM_QUOTA_MAX_WAIT_SECONDS=60` (חשוב למכסות הדקה של המודלים החינמיים).

---

## הבדיקה היומית (בבוקר, דקה אחת)

קריאה בלבד: 0 קריאות מודל ו-0 קריאות FMP. לא מריצים כאן `verify.sh`: הוא מריץ preflight חי ואת כל ה-pipeline על התאריך של היום, ובבוקר בישראל זה יום מסחר שעוד לא נסגר, אז ריצת הערב תחזור על הסוכנים היומיים.

```bash
# 1. המתזמן והג'ובים
curl -s localhost:8000/health

# 2. הריצה האחרונה: סטטוסים, fallbacks, עלות, ספקים, FMP, והג'וב
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F" | "' <<'SQL'
select run_date, status, count(*), sum(llm_fallbacks), round(sum(coalesce(cost_usd,0))::numeric,4) from agent_runs where run_date = (select max(run_date) from agent_runs) group by 1, 2 order by 2;
select provider, count(*) from llm_calls where created_at > now() - interval '24 hours' group by 1;
select day, calls from provider_calls where provider = 'fmp' order by day desc limit 3;
select job_id, status, started_at, finished_at, detail from job_runs where job_id = 'daily_pipeline' order by started_at desc limit 3;
SQL

# 3. רק אם משהו נכשל: איפה בדיוק
docker compose exec api python -m scripts.agent_card <agent> --days 7
```

**מה רושמים ביומן למטה:** תאריך, PASS / WARN / FAIL, ריצות שהושלמו מתוך הכלל, fallbacks, קריאות FMP, עלות, ומה הוסבר או תוקן. מספרים בלבד, בלי שמות מניות: הריפו ציבורי וה-watchlist אישי. מאותה סיבה דוחות JSON של ה-watchlist נשמרים מחוץ לריפו (`~/agentsForStocks-reports/`), לא ב-`docs/evaluation/`.

---

## מה עושים כשמשהו נכשל

| מה רואים | מה זה כנראה | מה עושים |
|---|---|---|
| `FAIL`: ריצת סוכן נכשלה | באג, או ספק שנפל | השגיאה מופיעה ב-`agent_card <agent>` (בשורה "failed run"). באג → issue או תיקון. ספק → לבדוק אם ה-retry השלים |
| `WARN` עם fallbacks | Gemini 503 או מכסה מלאה | `token_report --by provider`: האם Groq השלים? אם כל השרשרת נפלה, להוסיף `CEREBRAS_API_KEY` או להעלות את `LLM_QUOTA_MAX_WAIT_SECONDS` |
| `WARN` עם נתונים חסרים | צפוי בחלק מהמקרים (institutional בתוכנית החינמית, XOM בלי 10-K) | לוודא שזה ברשימת ה"מוסבר" בסעיף 3 של FUTURE. אם זה חדש, לרשום שם |
| `/health`: `daily_pipeline: missed` | המחשב היה כבוי בשעת הריצה | לא באג, אבל היום לא נספר. מריצים ידנית אחרי הסגירה ומשאירים את המחשב דלוק |
| `/health`: `nightly_maintenance: missed` | המחשב ישן ב-00:00 | נרשם בהערות, לא מפיל את היום |
| FMP קרוב ל-250 | שינוי ב-watchlist, או `--force` חוזר | לבדוק ב-`provider_calls` ובלוגים כמה קריאות לכל מניה. הצפי הוא כ-12 בריצה מלאה, ופחות כשהנתונים לא השתנו |

**כלל:** תיקון בזמן הייצוב רק לבאג או לתקלת נתונים. לא משנים פרומטים, משקלות או מודלים. תיקון כזה מאפס את ספירת הימים.

---

## יומן ימי הייצוב

| יום | תאריך | Verdict | ריצות | Fallbacks | FMP | עלות | הערות |
|---|---|---|---|---|---|---|---|
| 0 | 2026-11-03 | PASS | 70/70 (5 מניות, דוקר) | 0 | — | $0 | בדיקה ראשונה, `verify-2026-11-03.json` |
| 1 | 2026-11-05 | PASS | 126/126 (69 רצו, 57 הועתקו) | 0 | 46 | $0 | ריצה מתוזמנת, התחילה 14 דקות באיחור. הדשבורד לא נבדק באותו יום |
| 2 | 2026-11-06 | PASS | 126/126 (69 רצו, 57 הועתקו) | 0 | 12 | $0 | ריצה מתוזמנת, בזמן. הדשבורד לא נבדק באותו יום |
| 3 | | | | | | | |
| 4 | | | | | | | |
| 5 | | | | | | | |

---

## אחרי הייצוב: הסדר לחזרה לשיפורים
1. **מסמנים את השלב כעבר** ב-FUTURE ומוחקים את הערת ההשהיה.
2. **סבב 3 ב-`recommendation`:** נימוקי האנליסטים בפרומט (מתוכנן ב-`docs/agent-journal.md`).
3. **מתחילת דצמבר**, כשההחלטות הראשונות יתבררו (20 ימי מסחר): `track_report`, `backtest_weights`, ובדיקה של תקרות הוודאות מ-5.11 מול התוצאות.
