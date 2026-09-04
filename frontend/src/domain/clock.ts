/**
 * Reading a world's clock: the moment it is at, and how far that is from today. Both take
 * milliseconds rather than a Date, because the value they describe ticks — a Date built for the
 * purpose is a snapshot the caller has to remember to rebuild.
 */

const WHEN = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: 'UTC',
})

const DAY_MS = 24 * 60 * 60 * 1000

/** The moment a world is at, in UTC, and saying so. Everything else this panel shows about a
 *  world is UTC, and a clock in local time next to a table in UTC is an hour of arithmetic the
 *  reader has to do. */
export function modelTime(ms: number): string {
  return `${WHEN.format(new Date(ms))} UTC`
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
