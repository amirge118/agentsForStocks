"""
Pure financial logic — no I/O, no LLM, no database. Every function takes plain
data (dicts from providers, pandas Series) and returns numbers or small frozen
dataclasses, so it can be unit-tested and reused by any agent.
"""
