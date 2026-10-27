"use client"

import { useSyncExternalStore } from "react"

/** Token names the charts paint with (globals.css @theme). */
const TOKENS = ["ok", "bad", "ink", "ink-2", "muted", "rule", "rule-2", "paper-2", "paper-3", "accent", "cool"] as const
export type ThemeColor = (typeof TOKENS)[number]
export type ThemeColors = Record<ThemeColor, string>

// Charts can't take var() in every attribute they set, so they get the resolved values.
const FALLBACK = Object.fromEntries(TOKENS.map((t) => [t, `var(--color-${t})`])) as ThemeColors

/**
 * A CSS colour as rgb()/rgba(). The tokens are oklch, which the browser may report as
 * lab(); canvas chart libraries only parse rgb / hex, so paint it once and read it back.
 */
export function toRgb(color: string): string {
  const canvas = document.createElement("canvas")
  canvas.width = canvas.height = 1
  const ctx = canvas.getContext("2d", { willReadFrequently: true })
  if (!ctx) return color
  ctx.fillStyle = color
  ctx.fillRect(0, 0, 1, 1)
  const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data
  return a === 255 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${((a ?? 0) / 255).toFixed(3)})`
}

export function readThemeColors(root: Element = document.documentElement): ThemeColors {
  const style = getComputedStyle(root)
  return Object.fromEntries(
    TOKENS.map((t) => {
      const value = style.getPropertyValue(`--color-${t}`).trim()
      return [t, value ? toRgb(value) : FALLBACK[t]]
    }),
  ) as ThemeColors
}

let cached: ThemeColors | null = null
const noSubscription = () => () => {}

/** The theme's colours, resolved in the browser (var() fallbacks during server rendering). */
export function useThemeColors(): ThemeColors {
  return useSyncExternalStore(
    noSubscription,
    () => (cached ??= readThemeColors()),
    () => FALLBACK,
  )
}
