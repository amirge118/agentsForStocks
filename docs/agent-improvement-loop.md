# לופ שיפור סוכן

איך משפרים סוכן אחד, בסבב קבוע: **מצב ← השערה ← בסיס ← שינוי ← בדיקה ← החלטה ← מעקב.**
בכל סבב מטפלים בסוכן אחד ומשנים דבר אחד. כל סבב נרשם ב-[`agent-journal.md`](agent-journal.md).

כל הפקודות רצות מתיקיית `backend/`.

---

## 1. מצב: איפה הסוכן עומד

```bash
python -m scripts.agent_card recommendation          # 14 ימים אחרונים
python -m scripts.agent_card valuation --days 30
```

כרטיס הסוכן קורא רק ממסד הנתונים: הוא לא קורא למודל ולא ל-FMP. הוא מציג:

| חלק | מה הוא אומר |
|---|---|
| Configuration | ספק, מודל, איזה קובץ פרומט פעיל, skills, וקבצי הפרומט והצילום |
| Runs | כמה ריצות, כמה נכשלו, כמה פעמים המודל נפל ל-fallback (האות החישובי) |
| Latest call per symbol | האות והביטחון האחרונים לכל חברה |
| Data gaps | אילו נתונים חסרו, ובכמה מהריצות |
| Contract violations | תשובות שהפרו חוק שהפרומט מגדיר |
| Model calls | קריאות, שגיאות, טוקנים ועלות לפי ספק, וגרסאות הפרומט שרצו |
| Track record | אחרי 20 ימי מסחר: כמה פעמים צדק מול המדד, ומה ה-alpha |
| Eval coverage | כמה מקרי בדיקה יש לסוכן, וכמה מהם עם תשובה נכונה מתויגת |
| **Where to start** | **איפה להתחיל** (ההסבר בטבלה הבאה) |

**איך לקרוא את "Where to start", לפי סדר עדיפות:**

| רמז | מה לעשות |
|---|---|
| failed runs | לתקן קודם את הכישלון (השגיאה מוצגת). זה באג, לא פרומט. |
| Data before prompt | חסרים נתונים ביותר מ-30% מהריצות. המודל לא יכול לשפוט מה שהוא לא מקבל, ולכן מתקנים קודם את הספק (`app/providers/`) או את ה-fetch של הסוכן. |
| Contract violations | התשובה סותרת חוק. מחדדים את הניסוח בפרומט, או את ה-invariant ב-`@register_agent(invariants=...)`. |
| fallback(s) | ביותר מ-10% מהריצות לא התקבלה תשובה מהמודל. זו בעיית ספק או מכסה, לא פרומט. בודקים עם `python -m scripts.preflight` ובדף `/usage`. |
| labelled eval case(s) | פחות משני מקרים מתויגים. מוסיפים מקרה ל-`evals/cases.py` לפני שינוי, אחרת ה-eval לא יבחין בין טוב לגרוע. |
| No settled outcomes | עוד אין תוצאות מול השוק. בינתיים מסתמכים על eval התרחישים. |

**לראות את הפרומטים עצמם:**
- **בדשבורד:** `/runs` ← ריצה ← הפרומט המלא (system ו-user) ותשובת המודל, לכל קריאה. נשמר 90 יום (`LLM_CAPTURE_CONTENT=true`).
- **בקוד:**
  - ההוראות: `app/llm/prompts/<agent>.md`;
  - הנתונים שנכנסים: `_prompt()` ב-`app/agents/<agent>.py`;
  - בדיוק מה המודל מקבל, בלי להריץ: `tests/snapshots/prompts/<agent>.txt`.

---

## 2. השערה

כותבים ביומן, לפני שנוגעים בקוד:
- **מה הבעיה:** מהכרטיס, או מפרומט שנקרא ב-`/runs`.
- **מה השינוי:** אחד בלבד.
- **למה הוא אמור לעזור, ואיך נדע:** איזה מדד ב-eval צריך לזוז.

---

## 3. בסיס: eval על הגרסה הנוכחית

```bash
python -m evals.run --suite scenarios --agents recommendation --repeats 3 --label recommendation-base        # הערכת עלות בלבד
python -m evals.run --suite scenarios --agents recommendation --repeats 3 --label recommendation-base --yes  # ריצה אמיתית
```

- **בלי `--yes`** מודפסת רק הערכת עלות וכמה מהמכסה החינמית תנוצל.
- **הדוח** נשמר ב-`evals/reports/<time>-<label>.json`. הדוחות לא נשמרים ב-git, ולכן מצרפים אותם ל-PR.

---

## 4. שינוי: אחד, ובלי לשבור את מה שקיים

| סוג | איך |
|---|---|
| פרומט | קובץ חדש `app/llm/prompts/<agent>_v2.md`. הקובץ הקיים לא משתנה, והגרסה נבחרת דרך פרופיל: `--profiles '{"<agent>": {"prompt": "<agent>_v2"}}'` |
| מודל או ספק | preset מוכן: `--profiles @evals/presets/haiku55.json` (וגם `free_gemini`, `free_groq`, …) |
| skill | `--profiles '{"<agent>": {"skills": ["confidence_calibration"]}}'` |
| חישוב | `app/domain/*.py` (פונקציות טהורות), עם בדיקת יחידה שמקבעת את ההתנהגות |
| נתונים | `app/providers/` או `fetch()` של הסוכן |
| משקלות ההמלצה | `recommendation_weight`. בודקים קודם: `python -m scripts.backtest_weights` |

---

## 5. בדיקה

```bash
python -m evals.run --suite scenarios --agents recommendation --repeats 3 \
    --profiles '{"recommendation": {"prompt": "recommendation_v2"}}' --label recommendation-v2 --yes
python -m evals.compare evals/reports/<base>.json evals/reports/<v2>.json
pytest                                                                   # הבדיקות כולן
UPDATE_SNAPSHOTS=1 pytest tests/unit/agents/test_prompt_snapshots.py     # רק אם הפרומט הפעיל השתנה
```

**מה ההשוואה מראה:**

| מדד | המשמעות |
|---|---|
| Label accuracy | האות תואם את התשובה המתויגת |
| Stability | אותה תשובה בשלוש חזרות |
| Violation rate | הפרות חוקים |
| Fallback rate | כמה פעמים לא התקבלה תשובה מהמודל |
| Faithfulness | עם `--judge`: הנימוק נאמן לנתונים |
| Avg tokens / Cost | כמה עולה כל קריאה |

---

## 6. החלטה

**השינוי נכנס רק אם:**
- המדד שההשערה כיוונה אליו השתפר;
- ואף מדד אחר לא נסוג: דיוק, יציבות, הפרות, fallbacks;
- והעלות סבירה.

אחרי שהוחלט להכניס:
- **פרומט:** מחליפים את הקובץ הפעיל או את ברירת המחדל בפרופיל, ומעדכנים את הצילום.
- **ה-PR כולל:** טבלת ה-compare בתיאור, וה-diff של הצילום.
- **אם לא:** רושמים ביומן למה לא נכנס. גם זו תוצאה.

---

## 7. מעקב: מול השוק

ההחלטות נסגרות אחרי 5, 20 ו-60 ימי מסחר. כשהמתזמן פעיל זה קורה אוטומטית, ואפשר גם ידנית:

```bash
python -m scripts.settle_outcomes
python -m scripts.track_report --horizon 20          # כל הסוכנים
python -m scripts.agent_card recommendation          # הסוכן הזה
python -m evals.capture --outcomes && python -m evals.run --suite outcomes --label recommendation-v2 --yes
```

רושמים ביומן את התוצאה מול השוק. זה המבחן האמיתי: ה-eval על תרחישים בודק עקביות, לא אם ההמלצה נכונה.

---

## כללים

- **סוכן אחד, שינוי אחד, בכל סבב.** שני שינויים יחד, ואי אפשר לדעת מה עזר.
- **אין שינוי בפרומט, מודל או skill בלי eval לפני ואחרי** (CLAUDE.md #16).
- **כשהכרטיס מראה בעיית נתונים או כישלונות**, הם קודמים לפרומט.
- **מכסת FMP היא 250 קריאות ביום**, וריצה מלאה של 5 חברות לוקחת כ-110. eval על תרחישים לא קורא ל-FMP.
- **כל רעיון שעולה בדרך** נרשם ב-`FUTURE_IMPROVEMENTS.md`.
