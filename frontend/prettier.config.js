/**
 * Every value here was read off the code rather than taken from prettier's defaults.
 *
 * A formatter installed after the fact has one job on its first day: to leave the project looking
 * the way it already looks. Anything it changes beyond that is a decision nobody made, arriving in
 * a diff too large to read.
 *
 * @type {import('prettier').Config}
 */
export default {
  // Measured: of the thirty-nine hand-written files, eight hundred lines run past ninety columns
  // and thirty-three past a hundred. That is a project written to a hundred, and it is the same
  // hundred `ruff` is given in backend/pyproject.toml, so a paragraph of prose reads the same
  // width on both sides of the repository.
  printWidth: 100,

  // Measured: zero statement-terminating semicolons in anything written by hand here.
  semi: false,

  // Measured: ninety-four single-quoted imports against six double-quoted ones, and all six of
  // those are in the vendored shadcn components, which this does not format.
  singleQuote: true,
}
