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

## 2026-11-02 · recommendation · מתוכנן

**מצב:** ההמלצה הסופית (BUY/HOLD/SELL) היא הסוכן המשפיע ביותר. הגרסה `recommendation_v2.md` כתובה, אבל לא נבדקה מעולם. עוד אין החלטות שהתבררו מול השוק, ולכן בשלב הראשון השיפוט הוא לפי eval התרחישים.

**השערה:** הפרומט `recommendation_v2` מנמק טוב יותר מהנוכחי: יותר יציב ונאמן לנתונים, בלי לפגוע בדיוק על המקרים המתויגים ובלי להפר את תקרת הסיכון.

**שינוי:** פרופיל בלבד, `{"recommendation": {"prompt": "recommendation_v2"}}`. אין שינוי בקוד.

**צעדים:**
1. `python -m scripts.agent_card recommendation`: לרשום כאן את הרמזים.
2. **בסיס:** `python -m evals.run --suite scenarios --agents recommendation --repeats 3 --judge --label recommendation-base --yes`
3. **אחרי:** אותה פקודה עם `--profiles '{"recommendation": {"prompt": "recommendation_v2"}}' --label recommendation-v2`
4. `python -m evals.compare evals/reports/<base>.json evals/reports/<v2>.json`
5. **החלטה** לפי [כללי ההחלטה](agent-improvement-loop.md#6-החלטה). כשיש כמה שבועות של החלטות שהתבררו: `--suite outcomes` על שתי הגרסאות.

**עלות:** המודלים חינמיים, והריצה לא קוראת ל-FMP. כדי לראות הערכת עלות לפני שמריצים, מריצים את אותה פקודה בלי `--yes`.

**בסיס / אחרי / החלטה:** עוד לא רץ.
