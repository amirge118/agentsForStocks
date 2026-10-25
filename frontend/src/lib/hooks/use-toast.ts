"use client"

/**
 * shadcn/ui toast store: toast({ title, description, variant }) from anywhere,
 * rendered by <Toaster />. Kept minimal — one toast visible at a time.
 */
import * as React from "react"

import type { ToastProps } from "@/components/ui/toast"

const TOAST_LIMIT = 1
const TOAST_REMOVE_DELAY_MS = 5_000

export interface ToasterToast extends Omit<ToastProps, "title"> {
  id: string
  title?: React.ReactNode
  description?: React.ReactNode
}

type State = { toasts: ToasterToast[] }

let count = 0
let memoryState: State = { toasts: [] }
const listeners = new Set<(state: State) => void>()

function setState(next: State): void {
  memoryState = next
  listeners.forEach((listener) => listener(memoryState))
}

function dismiss(id?: string): void {
  setState({
    toasts: memoryState.toasts.map((t) =>
      id === undefined || t.id === id ? { ...t, open: false } : t,
    ),
  })
  setTimeout(() => {
    setState({ toasts: memoryState.toasts.filter((t) => t.open !== false) })
  }, TOAST_REMOVE_DELAY_MS)
}

export function toast(props: Omit<ToasterToast, "id">): { id: string; dismiss: () => void } {
  count = (count + 1) % Number.MAX_SAFE_INTEGER
  const id = String(count)
  const next: ToasterToast = {
    ...props,
    id,
    open: true,
    onOpenChange: (open) => {
      if (!open) dismiss(id)
    },
  }
  setState({ toasts: [next, ...memoryState.toasts].slice(0, TOAST_LIMIT) })
  return { id, dismiss: () => dismiss(id) }
}

export function useToast(): State & { toast: typeof toast; dismiss: typeof dismiss } {
  const [state, setLocal] = React.useState<State>(memoryState)
  React.useEffect(() => {
    listeners.add(setLocal)
    return () => {
      listeners.delete(setLocal)
    }
  }, [])
  return { ...state, toast, dismiss }
}
