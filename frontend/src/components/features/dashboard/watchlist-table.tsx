"use client"

import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type Announcements,
  type Modifier,
  type UniqueIdentifier,
} from "@dnd-kit/core"
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import Link from "next/link"
import { useState, type ReactNode } from "react"

import { ActionBadge } from "@/components/features/stocks/action-badge"
import { ComplianceMarker } from "@/components/features/stocks/compliance-marker"
import { ReviewMarker } from "@/components/features/stocks/review-marker"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatConfidence, formatDate, formatScore, toneClasses } from "@/lib/format"
import { useSymbols, useWatchlistMutations } from "@/lib/hooks/queries"
import { cn } from "@/lib/utils"

import { ScoreSparkline } from "./score-sparkline"

export function WatchlistTable() {
  const { data, isPending, isError, error, refetch } = useSymbols()
  const { reorder } = useWatchlistMutations()
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  if (isPending) {
    return (
      <div className="space-y-2 p-4" aria-label="Loading watchlist">
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <div role="alert" className="flex items-center justify-between p-6 text-sm">
        <span className="text-bad">Could not load the watchlist: {error.message}</span>
        <Button variant="outline" size="sm" onClick={() => void refetch()}>
          Retry
        </Button>
      </div>
    )
  }

  if (data.length === 0) {
    return (
      <p role="status" className="p-6 text-sm text-muted">
        The watchlist is empty. Add a ticker above: it is analysed in the next daily run (weekdays, 18:30 New York
        time), or right away with Run analysis.
      </p>
    )
  }

  const symbols = data.map((row) => row.symbol)
  // Every recommendation carries the same backend disclaimer; show it once under the table
  const disclaimer = data.find((row) => row.recommendation)?.recommendation?.disclaimer

  return (
    <>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        modifiers={[alongTheList]}
        accessibility={{ announcements: announcements(symbols) }}
        onDragEnd={({ active, over }) => {
          if (!over || active.id === over.id) return
          reorder.mutate(arrayMove(symbols, symbols.indexOf(String(active.id)), symbols.indexOf(String(over.id))))
        }}
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8">
                <span className="sr-only">Drag to reorder</span>
              </TableHead>
              <TableHead>Symbol</TableHead>
              <TableHead>Recommendation</TableHead>
              <TableHead className="text-right">Score</TableHead>
              <TableHead className="hidden text-right sm:table-cell">Confidence</TableHead>
              <TableHead className="hidden sm:table-cell">As of</TableHead>
              <TableHead className="hidden lg:table-cell">Trend</TableHead>
              <TableHead className="hidden md:table-cell">Summary</TableHead>
              <TableHead className="text-right">
                <span className="sr-only">Order and remove</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <SortableContext items={symbols} strategy={verticalListSortingStrategy}>
              {data.map(({ symbol, recommendation: rec }, index) => (
                <SortableRow key={symbol} symbol={symbol}>
                  <TableCell className="font-mono font-medium">
                    <Link href={`/symbols/${symbol}`} className="hover:underline">
                      {symbol}
                    </Link>
                  </TableCell>
                  {rec ? (
                    <>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <ActionBadge action={rec.action} />
                          <ComplianceMarker status={rec.compliance.status} findings={rec.compliance.findings} />
                          <ReviewMarker reasons={rec.needs_review} />
                        </div>
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        <span className={cn("rounded-chip px-1.5 py-0.5", toneClasses(rec.weighted_score))}>
                          {formatScore(rec.weighted_score)}
                        </span>
                      </TableCell>
                      <TableCell className="hidden text-right font-mono sm:table-cell">
                        {formatConfidence(rec.confidence)}
                      </TableCell>
                      <TableCell className="hidden text-muted sm:table-cell">{formatDate(rec.run_date)}</TableCell>
                      <TableCell className="hidden lg:table-cell">
                        <ScoreSparkline symbol={symbol} />
                      </TableCell>
                      <TableCell className="hidden max-w-md truncate text-muted md:table-cell">
                        {rec.reasoning}
                      </TableCell>
                    </>
                  ) : (
                    <>
                      {/* One cell per hidden column too, so the controls stay in their column at every width */}
                      <TableCell colSpan={2} className="text-muted">
                        Not analysed yet
                      </TableCell>
                      <TableCell className="hidden sm:table-cell" />
                      <TableCell className="hidden sm:table-cell" />
                      <TableCell className="hidden lg:table-cell" />
                      <TableCell className="hidden md:table-cell" />
                    </>
                  )}
                  <TableCell className="text-right">
                    <RowControls symbol={symbol} index={index} symbols={symbols} />
                  </TableCell>
                </SortableRow>
              ))}
            </SortableContext>
          </TableBody>
        </Table>
      </DndContext>
      {disclaimer && (
        <p className="border-t border-rule px-4 py-3 text-xs text-muted">{disclaimer}</p>
      )}
    </>
  )
}

/** What a screen reader hears while a row is lifted with the keyboard (space, arrows, space). */
function announcements(symbols: string[]): Announcements {
  const at = (id: UniqueIdentifier | undefined) => `position ${symbols.indexOf(String(id)) + 1} of ${symbols.length}`
  return {
    onDragStart: ({ active }) => `Picked up ${active.id}, ${at(active.id)}.`,
    onDragOver: ({ active, over }) => (over ? `${active.id} is over ${at(over.id)}.` : undefined),
    onDragEnd: ({ active, over }) =>
      over ? `Moved ${active.id} to ${at(over.id)}.` : `${active.id} was dropped where it was.`,
    onDragCancel: ({ active }) => `Moving ${active.id} was cancelled.`,
  }
}

/** Rows only move up and down. */
const alongTheList: Modifier = ({ transform }) => ({ ...transform, x: 0 })

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)"

/** A table row that moves with the drag; only its grip starts one, so links and buttons still work. */
function SortableRow({ symbol, children }: { symbol: string; children: ReactNode }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } =
    useSortable({ id: symbol })
  const still = typeof window !== "undefined" && window.matchMedia?.(REDUCED_MOTION).matches
  return (
    <TableRow
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition: still ? undefined : transition }}
      className={cn("relative", isDragging && "z-10 bg-paper-3")}
    >
      <TableCell className="w-8 px-2">
        <button
          ref={setActivatorNodeRef}
          type="button"
          aria-label={`Reorder ${symbol}`}
          className="flex h-8 w-6 cursor-grab touch-none items-center justify-center rounded-chip text-muted hover:text-ink focus-visible:outline-2 focus-visible:outline-focus active:cursor-grabbing"
          {...attributes}
          {...listeners}
        >
          <span aria-hidden>⠿</span>
        </button>
      </TableCell>
      {children}
    </TableRow>
  )
}

/**
 * Move a symbol up or down, or remove it (the second click confirms; its history stays).
 * From sm up the controls sit in the row; on a phone they fold into one menu.
 */
function RowControls({ symbol, index, symbols }: { symbol: string; index: number; symbols: string[] }) {
  const { remove, reorder } = useWatchlistMutations()
  const [confirming, setConfirming] = useState(false)
  const move = (delta: -1 | 1) => reorder.mutate(arrayMove(symbols, index, index + delta))
  const busy = remove.isPending || reorder.isPending
  const first = index === 0
  const last = index === symbols.length - 1

  if (confirming) {
    return (
      <div className="flex items-center justify-end gap-1">
        <Button variant="destructive" size="sm" disabled={busy} onClick={() => remove.mutate(symbol)}>
          Remove {symbol}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
          Keep
        </Button>
      </div>
    )
  }

  return (
    <>
      <div className="hidden items-center justify-end gap-1 sm:flex">
        <Button variant="ghost" size="sm" aria-label={`Move ${symbol} up`} disabled={busy || first} onClick={() => move(-1)}>
          ↑
        </Button>
        <Button variant="ghost" size="sm" aria-label={`Move ${symbol} down`} disabled={busy || last} onClick={() => move(1)}>
          ↓
        </Button>
        <Button variant="ghost" size="sm" aria-label={`Remove ${symbol}`} disabled={busy} onClick={() => setConfirming(true)}>
          Remove
        </Button>
      </div>
      <div className="flex justify-end sm:hidden">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" aria-label={`Actions for ${symbol}`} disabled={busy}>
              <span aria-hidden>⋯</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            <DropdownMenuItem disabled={first} onSelect={() => move(-1)}>
              Move up
            </DropdownMenuItem>
            <DropdownMenuItem disabled={last} onSelect={() => move(1)}>
              Move down
            </DropdownMenuItem>
            <DropdownMenuItem className="text-bad" onSelect={() => setConfirming(true)}>
              Remove…
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </>
  )
}
