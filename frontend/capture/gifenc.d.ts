/** `gifenc` ships no types and no `exports` map, so Node's ESM loader hands the CJS bundle over
 *  as one default export. Both facts are declared here rather than worked around at each call. */
declare module 'gifenc' {
  interface Encoder {
    writeFrame(
      index: Uint8Array,
      width: number,
      height: number,
      options: { palette: number[][]; delay: number },
    ): void
    finish(): void
    bytes(): Uint8Array
  }

  const gifenc: {
    GIFEncoder(): Encoder
    quantize(rgba: Uint8ClampedArray, colours: number): number[][]
    applyPalette(rgba: Uint8ClampedArray, palette: number[][]): Uint8Array
  }

  export default gifenc
}
