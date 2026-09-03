/**
 * What every figure shares, built from the design tokens at draw time. Chart.js draws for a light
 * theme by default — black ticks, a white tooltip — and that is undone once here rather than per
 * figure, so a sixth figure cannot be the one that forgot.
 */

import type { ChartOptions } from 'chart.js'

import { furniture, type Reader } from '@/charts/palette'

/** What a bar and a line both accept. Chart.js types its options per chart type, so the union of
 *  the two satisfies neither and the intersection is what says "these are the shared ones". */
type Shared = ChartOptions<'bar'> & ChartOptions<'line'>

/** From docs/design.md's Floor: the ceiling for a transition, and nothing on an update. */
const ENTRANCE = 200

/** A bar is never thicker than a table row, so three marks do not draw as three slabs. */
export const MAX_BAR = 40

const TICK_SIZE = 12
const TOOLTIP_TEXT = 13

export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

interface Shape {
  /** True when the category axis runs down the side, which is how a long label is read. */
  horizontal?: boolean
  /** Drawn only where there is more than one series to tell apart. */
  legend?: boolean
  /** How a value is said in the tooltip. Counts need nothing; money needs its unit. */
  format?: (value: number) => string
  /** How a value is said on the axis, when that is not how it is said in the tooltip. Money is:
   *  the unit belongs beside one number, not beside six of them down the side of a plot. */
  tick?: (value: number) => string
}

/**
 * Two axes, one of which carries no grid: a rule between two named things would say they are a
 * measurement apart. The value axis starts at zero, because a truncated one exaggerates silently.
 */
export function chartOptions(
  { horizontal = false, legend = false, format, tick: tickFormat }: Shape = {},
  read?: Reader,
): Shared {
  const grid = furniture('grid', read)
  const tick = furniture('tick', read)
  const said = tickFormat ?? format
  const label = (value: number | string): string =>
    typeof value === 'number' && said !== undefined ? said(value) : String(value)

  const values = {
    beginAtZero: true,
    border: { display: false },
    grid: { color: grid, drawTicks: false },
    // Six rules at most. A plot with ten is a grid somebody has to read past to see the marks.
    ticks: {
      color: tick,
      font: { size: TICK_SIZE },
      padding: 8,
      maxTicksLimit: 6,
      callback: label,
    },
  }
  // `maxRotation: 0` and let Chart.js drop the labels that will not fit. A rotated tick is a
  // label a reader tilts their head for, and twelve months in half a column is where it happens.
  const categories = {
    border: { display: false },
    grid: { display: false },
    ticks: { color: tick, font: { size: TICK_SIZE }, padding: 8, maxRotation: 0, autoSkip: true },
  }

  return {
    responsive: true,
    maintainAspectRatio: false,
    indexAxis: horizontal ? 'y' : 'x',
    // On first paint only. A figure that replayed itself whenever a poll came back would tell the
    // whole story again every thirty seconds.
    animation: prefersReducedMotion() ? false : { duration: ENTRANCE },
    animations: { colors: false, x: false, y: false },
    scales: horizontal ? { x: values, y: categories } : { x: categories, y: values },
    plugins: {
      legend: {
        display: legend,
        align: 'start',
        position: 'top',
        labels: {
          color: furniture('legend', read),
          font: { size: TICK_SIZE },
          boxWidth: 12,
          boxHeight: 2,
          usePointStyle: false,
        },
      },
      tooltip: {
        backgroundColor: furniture('tooltipFill', read),
        borderColor: furniture('tooltipEdge', read),
        borderWidth: 1,
        titleColor: furniture('tooltipText', read),
        bodyColor: furniture('tooltipText', read),
        titleFont: { size: TOOLTIP_TEXT },
        bodyFont: { size: TOOLTIP_TEXT },
        cornerRadius: 6,
        displayColors: false,
        padding: 8,
        callbacks:
          format === undefined
            ? {}
            : {
                // A point with no value on the axis being read is drawn as a gap by Chart.js;
                // these series carry none, and zero is the honest thing to say if one ever does.
                label: (item: { parsed: { x: number | null; y: number | null } }) =>
                  format((horizontal ? item.parsed.x : item.parsed.y) ?? 0),
              },
      },
    },
  }
}
