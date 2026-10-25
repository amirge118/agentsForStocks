"""
External data providers — the only code allowed to talk to yfinance, FMP, SEC EDGAR.
Every call goes through retry + per-domain rate limiting + a TTL cache.
"""
