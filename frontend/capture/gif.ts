/** Frames in, one animated GIF out. */

/* WHY THIS IS NOT ffmpeg. The screenshots beside it are produced by a checkout with node and a
   browser and nothing else, and a recording step that needed a system binary would make the
   README's picture the one thing somebody cannot regenerate. */

/* WHY IT IS NOT A PLAYWRIGHT VIDEO EITHER. A video is recorded at whatever rate the page happened
   to paint; these frames are taken at moments the run chose, so the run can assert what is in
   them. That is the whole point of generating the picture rather than taking it. */

import gifenc from 'gifenc'
import { PNG } from 'pngjs'

const { GIFEncoder, applyPalette, quantize } = gifenc

/** One picture and how long it stays on screen, in milliseconds. */
export interface Frame {
  png: Buffer
  ms: number
}

/** 256 is the format's ceiling, and this interface is a dark panel with five chip colours in it —
 *  the palette it actually needs is far smaller, but a cheap ceiling costs nothing here. */
const COLOURS = 256

export function encodeGif(frames: readonly Frame[]): Buffer {
  if (frames.length === 0) throw new Error('a gif of no frames is not a gif')

  const decoded = frames.map((frame) => ({ image: PNG.sync.read(frame.png), ms: frame.ms }))
  const { width, height } = decoded[0]!.image
  for (const { image } of decoded) {
    if (image.width !== width || image.height !== height) {
      throw new Error(
        `every frame must be the same size; got ${image.width}x${image.height} against ${width}x${height}`,
      )
    }
  }

  // ONE PALETTE FOR THE WHOLE ANIMATION, quantized from the first frame and reused. Per-frame
  // palettes make the interface's greys shift between frames, which reads as the panel flickering
  // rather than as the data changing — and the data changing is the entire subject.
  const encoder = GIFEncoder()
  const palette = quantize(new Uint8ClampedArray(decoded[0]!.image.data), COLOURS)

  for (const { image, ms } of decoded) {
    const rgba = new Uint8ClampedArray(image.data)
    encoder.writeFrame(applyPalette(rgba, palette), width, height, { palette, delay: ms })
  }

  encoder.finish()
  return Buffer.from(encoder.bytes())
}
