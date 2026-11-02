# יומן שיפורי סוכנים

כל סבב של [לופ השיפור](agent-improvement-loop.md) נרשם כאן, החדש למעלה.

**הסטטוסים:**
- `מתוכנן`: ההשערה נכתבה, ועוד לא רץ כלום.
- `בבדיקה`: ה-eval רץ.
- `נכנס`: השינוי מוזג.
- `נדחה`: ה-eval לא הראה שיפור.
- `נמדד`: יש גם תוצאה מול השוק.

---

## תבנית

```markdown
## <YYYY-MM-DD> · <agent> · <סטטוס>

**מצב (agent_card):** מה הכרטיס הראה. הרמז הראשון, ומספרים רלוונטיים.
**השערה:** מה משנים, ולמה זה אמור לעזור. איזה מדד צריך לזוז.
**שינוי:** קובץ, פרופיל או preset. דבר אחד בלבד.
**בסיס:** `evals/reports/<...>-<agent>-base.json`: דיוק, יציבות, הפרות, fallbacks, טוקנים.
**אחרי:** `evals/reports/<...>-<agent>-<variant>.json`: אותם מדדים.
**החלטה:** נכנס או נדחה, ולמה. קישור ל-PR.
**מול השוק (אחרי 20 ימי מסחר):** אחוז פגיעה ו-alpha לפני ואחרי (`track_report` / `agent_card`).
```

---

## 2026-11-02 · recommendation · מתוכנן (סבב 3: נתונים לפני פרומט)

**מצב:** מסבב 2. הפרומט של `recommendation` מקבל מכל אנליסט רק אות, ביטחון ומשקל (`_prompt` ב-`app/agents/recommendation.py`), בלי הנימוק. גם `covenant breach` שהאנליסט risk דיווח בתרחיש risk_override לא מגיע למודל. לכן כשמבקשים ממנו לציין סיכון, אין לו סיכון לצטט.

**השערה:** אם הפרומט יכלול שורת נימוק קצרה מכל אנליסט (או לפחות מ-risk ומכל אנליסט שאינו bullish), המודל יצטט סיכון אמיתי והנאמנות תעלה. זה הכלל "נתונים לפני פרומט" מהמדריך.

**שינוי:** קוד, `_prompt` של recommendation: שורת `reasoning` מקוצרת (כ-120 תווים) לכל אנליסט, עם עדכון צילום הפרומט ובדיקה. ההוראה בפרומט נשארת כמו שהיא. הגרסה v3 נשמרת להשוואה נוספת.

**צעדים:**
- eval עם `--repeats 5 --judge`, base מול הקוד החדש.
- מקרה ה-eval של consensus צריך נימוקים ריאליים: כרגע לכל אנליסט יש `"reasoning": "ok"`. לעדכן את `_analysts` ב-`evals/cases.py`, כך שלפחות risk יציין סיכון אמיתי ונמוך (למשל "low leverage; main risk: China supply chain").

**בסיס / אחרי / החלטה:** עוד לא רץ.

---

## 2026-11-02 · recommendation · נדחה (סבב 2: `recommendation_v3`)

**מצב:** מסבב 1. ההוראה "for a bullish call, name the main risk too" גרמה להמצאת סיכון בתרחיש consensus.

**השערה:** אם מנסחים את ההוראה מחדש ("name the main risk an analyst reported … if none reported one, say no specific risk was reported"), המודל יפסיק להמציא סיכון.

**שינוי:** `app/llm/prompts/recommendation_v3.md`, שורה אחת. נבחר דרך פרופיל.

**תוצאות** (`--repeats 5 --judge`, gemini חינמי, $0):

| מדד | base | v3 |
|---|---|---|
| Label accuracy | 100% | 100% |
| Stability | 100% | 100% |
| Faithfulness: כולל | 50% | 50% |
| Faithfulness: consensus | 0/5 | 1/5 |
| Faithfulness: risk_override | 5/5 | 4/5 |
| ביטחון ב-consensus | 80% | 90% |
| טוקני קלט | 477 | 519 (+9%) |

דוחות (לא ב-git): `evals/reports/20261102-164600-recommendation-base5.json` ו-`20261102-164810-recommendation-v3.json`.

**מה נמצא:**
- v3 עדיין ממציא סיכון ("market volatility"), ועכשיו גם מייחס אותו לאנליסטים: "The main risk noted by the risk analyst is general market volatility". זה גרוע יותר: המצאה עם מקור מזויף.
- הסיבה: הפרומט מקבל מכל אנליסט רק אות, ביטחון ומשקל, בלי נימוק. אין שום סיכון בקלט, ולכן ניסוח לא יכול לתקן את זה.

**החלטה: נדחה.** אין שיפור בנאמנות, הביטחון עולה ל-90% בלי בסיס, ויש ייחוס מזויף. `recommendation.md` נשאר ברירת המחדל. v3 נשאר בריפו רק כווריאנט להשוואה בסבב 3.

---

## 2026-11-02 · recommendation · נדחה (סבב 1: `recommendation_v2`)

**מצב (`agent_card recommendation --days 30`):**
- 7 ריצות, 0 כישלונות, 0 fallbacks, 0 פערי נתונים, 0 הפרות.
- מודל: gemini.
- עוד אין outcomes.
- יש 2 מקרי eval, שניהם מתויגים.
- הרמז היחיד: "No settled outcomes yet: judge changes with the scenario eval for now".

**השערה:** `recommendation_v2` מנמק טוב יותר (יציבות ונאמנות) בלי לפגוע בדיוק.

**שינוי:** פרופיל `{"recommendation": {"prompt": "recommendation_v2"}}`, בלי שינוי קוד.

**תוצאות** (`--suite scenarios --agents recommendation --repeats 3 --judge`, gemini חינמי, $0):

| מדד | base | v2 |
|---|---|---|
| Label accuracy | 100% | 100% |
| Stability | 100% | 100% |
| Faithfulness (judge) | 17% (1/6) | 33% (2/6) |
| Fallbacks / Violations | 0% / 0% | 0% / 0% |
| ביטחון ב-consensus | 75–85% | 85–90% |
| טוקני קלט בממוצע | 477 | 555 (+16%) |

דוחות (לא ב-git): `evals/reports/20261102-162605-recommendation-base.json` ו-`20261102-162727-recommendation-v2.json`.

**מה נמצא:**
- בתרחיש consensus כל 6 התשובות, בשתי הגרסאות, הוסיפו סיכון שלא הופיע בנתונים, כמו "Main risk remains macroeconomic volatility".
- המקור הוא ההוראה המשותפת לשני הפרומטים: "for a bullish call, name the main risk too".
- בתרחיש risk_override התשובות נאמנות יותר, אבל לפעמים מוסיפות ניסוח כמו "Holding is prudent".

**החלטה: נדחה.**
- ההבדל בנאמנות הוא תשובה אחת מתוך 6, כלומר בגבולות הרעש.
- v2 עולה 16% יותר טוקנים, ונותן ביטחון גבוה יותר בלי בסיס נוסף.
- הבעיה האמיתית משותפת לשתי הגרסאות, ולכן היא עוברת לסבב 2 (למעלה).
- הפרומט הנוכחי נשאר ברירת המחדל.

**מול השוק:** עוד אין החלטות שהתבררו.
