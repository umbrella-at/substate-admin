/**
 * How long ago, rather than when.
 *
 * One question this answers and one it does not. "Has this person been seen lately" is a duration,
 * and a date makes the reader do the subtraction; "when did this happen" is an instant that will
 * be compared with another instant, and a duration makes them do it the other way. The activity
 * column and the subscriber card both ask the first, so they share this; the feed and the audit
 * ask the second and use `instant`.
 *
 * `numeric: 'always'`, so there are no idioms — "1 day ago" rather than "yesterday". Two reasons,
 * and the second decides it. An idiom is a calendar claim laid over arithmetic that is not
 * calendar: elapsed ÷ 24h is not a count of days on a wall, so forty-seven hours would read as
 * "yesterday" when the calendar calls it the day before. And this is read down a column, where
 * "yesterday" between "23 hours ago" and "2 days ago" is the row the eye stops on.
 *
 * THE BUCKETS ARE SIZED SO THAT EVERY ONE OF THEM STARTS AT 1. `YEAR` is both the limit the months
 * bucket stops at and the unit the years bucket divides by, so whatever a month is worth, a year
 * is worth twelve of them and the first count out of every bucket is exactly one.
 */

const RELATIVE = new Intl.RelativeTimeFormat('en-GB', { numeric: 'always' })

const MINUTE = 60 * 1000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
/** The Gregorian mean month, 365.2425 ÷ 12. Not thirty: a thirty-day month over-reports by a whole
 *  unit near every anniversary — 720 days would read as "2 years ago" against a true one year and
 *  eleven months, and a phrase that says "ago" is a floor that must not round up. */
const MONTH = 30.436875 * DAY
const YEAR = 12 * MONTH

/** Each row: the elapsed time this bucket stops at, the unit it counts in, and how long that unit
 *  is. Read in order, first match wins. */
const SCALE: readonly (readonly [number, Intl.RelativeTimeFormatUnit, number])[] = [
  [HOUR, 'minute', MINUTE],
  [DAY, 'hour', HOUR],
  [MONTH, 'day', DAY],
  [YEAR, 'month', MONTH],
  [Number.POSITIVE_INFINITY, 'year', YEAR],
]

/** The one row that is not "N units ago", and the only string here `Intl` does not produce. A
 *  count of seconds would be a precision this data does not have, and `format(0, 'second')` is
 *  "now", which reads as a claim that something is happening. A timestamp in the future — a clock
 *  askew on either end — lands here too, which is the least wrong thing to say about it. */
export const JUST_NOW = 'just now'

export function formatSince(at: Date, now: number): string {
  const elapsed = now - at.getTime()
  if (elapsed < MINUTE) return JUST_NOW
  for (const [limit, unit, step] of SCALE) {
    if (elapsed < limit) return RELATIVE.format(-Math.floor(elapsed / step), unit)
  }
  /* v8 ignore next -- the last bucket has no upper bound, so the loop always returns */
  return JUST_NOW
}

/** The exact moment, for the hover. ISO and UTC: the relative phrase is the answer and this is the
 *  evidence, so it should be unambiguous rather than readable. */
export function exactly(at: Date): string {
  return at.toISOString().replace(/\.\d{3}Z$/u, 'Z')
}
