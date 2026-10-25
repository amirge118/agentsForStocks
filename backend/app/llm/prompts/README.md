One system prompt per agent, named after the agent (`moat.md` → MoatAgent).
The reply format (signal / confidence / reasoning) is enforced by structured
outputs in app/llm/client.py, so prompts describe the judgement, not the JSON.
