/**
 * Reading a world's clock: the moment it is at, and how far that is from today. Both take
 * milliseconds rather than a Date, because the value they describe ticks — a Date built for the
 * purpose is a snapshot the caller has to remember to rebuild.
 */

const DATE = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

const TIME = new Intl.DateTimeFormat('en-GB', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: 'UTC',
})

const DAY_MS = 24 * 60 * 60 * 1000

/** The day a world is at, and the time of day, as two strings. Two rather than one because the
 *  panel is 240px wide: one string wraps or does not depending on the month's name, and a reading
 *  that jumps a line between September and October looks broken in one of them. */

/* UTC, and the label says so. Everything else this panel shows about a world is UTC, and a clock
   in local time beside a table in UTC is an hour of arithmetic the reader has to do. */
export function modelDate(ms: number): string {
  return DATE.format(new Date(ms))
}

export function modelClock(ms: number): string {
  return `${TIME.format(new Date(ms))} UTC`
}

/** How far a world has been wound, in whole days, from the offset itself. */

/* FROM THE OFFSET AND NOT FROM TWO CLOCK READINGS. Model time is the real clock plus the offset,
   so subtracting the real clock again gives the offset minus however long the two reads were
   apart — and a floor over that answers 29 for a world wound exactly 30 days. */

/* Floored rather than rounded: thirty days and a few seconds is thirty days, and rounding would
   put a day on screen that has not happened. */
export function daysWound(offsetMs: number): number {
  return Math.max(0, Math.floor(offsetMs / DAY_MS))
}
