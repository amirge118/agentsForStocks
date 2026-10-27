/**
 * The recommendation's action thresholds, mirrored from backend/app/domain/scoring.py
 * (BUY_THRESHOLD / SELL_THRESHOLD). Charts draw them; the backend decides with them.
 */
export const SCORE_THRESHOLDS = { buy: 15, sell: -15 } as const

/** Weighted scores live on −100…+100. */
export const SCORE_RANGE = { min: -100, max: 100 } as const
