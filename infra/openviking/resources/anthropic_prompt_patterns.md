# Anthropic Prompt Patterns for Stock Analysis

Reference for how to structure Claude prompts across all agents in this project.

## Core Principles

1. **System prompt = role + output format constraint** — never put data here
2. **User prompt = all the data + specific question** — structured, factual
3. **Always mandate JSON output** in system prompt — prevents prose responses
4. **Include prior_context last** in user prompt — it's supplementary, not primary

---

## System Prompt Templates

### For Analyst Agents (signal generation)
```python
ANALYST_SYSTEM = """\
You are a {domain} stock analyst. Analyze the provided data and return a signal.
Return ONLY valid JSON with these exact keys:
  signal: "bullish" | "bearish" | "neutral"
  confidence: number between 0 and 100
  reasoning: string under 200 characters summarizing the key driver
Do not include any text outside the JSON object.
"""
```

### For Portfolio Manager (decision making)
```python
PORTFOLIO_SYSTEM = """\
You are a conservative portfolio manager. Make trading decisions based on analyst signals.
Bias toward hold — only act on high-conviction setups (confidence ≥ 65%).
Return ONLY valid JSON with these exact keys:
  action: "buy" | "sell" | "hold"
  quantity: integer (0 for hold)
  confidence: number between 0 and 100
  reasoning: string under 200 characters
"""
```

### For Narrative / Explanation (no JSON needed)
```python
EXPLAIN_SYSTEM = """\
You are a financial analyst writing for a sophisticated investor.
Be concise, precise, and data-driven. Use specific numbers, not vague language.
No bullet points — write in clear paragraphs. Max 3 paragraphs.
"""
```

---

## User Prompt Structure

### Standard analyst prompt structure
```
Symbol: {symbol}
[Primary metrics — most important data first]
[Secondary metrics]
[Computed scores / sub-signals]

Prior knowledge base context (from OpenViking):
{chr(10).join(f"- {p}" for p in prior_context) if prior_context else "None"}

[Specific question / instruction]
Return JSON only.
```

### Bear/Base/Bull scenario prompt
```
Symbol: {symbol}  |  Market Cap: ${mktcap:.1f}B

Scenario estimates:
  Bear (conservative): ${bear:.1f}B  — low growth (3%), WACC 12%
  Base (consensus):    ${base:.1f}B  — moderate growth (7%), WACC 10%
  Bull (optimistic):   ${bull:.1f}B  — high growth (12%), WACC 9%

Current market cap vs average estimate: {mos:+.1%} margin of safety
[Prior context]
Is this stock undervalued, overvalued, or fairly priced? Return JSON.
```

---

## Few-Shot Examples (include in prompt for better JSON compliance)

### Signal generation example
```
Example output:
{"signal": "bullish", "confidence": 72, "reasoning": "Strong FCF yield 8.2% + institutional buying + PE below sector median 18x"}
```

### Portfolio decision example
```
Example output:
{"action": "buy", "quantity": 50, "confidence": 68, "reasoning": "3/5 agents bullish, valuation 22% discount to DCF base, volatility low (12%)"}
```

---

## Model Selection Guide

| Use case | Model | Why |
|---|---|---|
| Analyst signals (structured JSON) | `claude-haiku-4-5` | Fast, cheap, reliable JSON |
| Valuation reasoning (complex) | `claude-haiku-4-5` | Still sufficient with structured data |
| Portfolio narrative / explanation | `claude-sonnet-4-6` | Better prose quality |
| Debugging / complex analysis | `claude-sonnet-4-6` | Better reasoning depth |

## Common Mistakes to Avoid

- **Don't ask "what do you think?"** — ask for a specific JSON structure
- **Don't put data in the system prompt** — it belongs in user prompt
- **Don't exceed 512 tokens for signal agents** — haiku is accurate enough, more tokens = cost with no benefit
- **Don't trust confidence > 90%** — cap at 95% in `llm_service.py` validation
- **Don't skip the prior_context block** — even if empty ("None"), keeps prompt structure consistent
