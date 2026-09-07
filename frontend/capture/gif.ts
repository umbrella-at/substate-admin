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

/** Every second pixel of every frame goes into the palette. */

/* LEARNED FROM ALL OF THEM, NOT FROM THE FIRST. The first frame here is a sign-in screen, which
   holds none of the five state-chip colours — so a palette quantized from it mapped every chip in
   the animation onto the same blue-grey, and the picture's whole subject went missing. */
const EVERY = 2

export function encodeGif(frames: readonly Frame[], keep: readonly string[] = []): Buffer {
  if (frames.length === 0) throw new Error('a gif of no frames is not a gif')
  if (keep.length > COLOURS / 2) throw new Error('too many colours reserved to learn a palette')

  const decoded = frames.map((frame) => ({ image: PNG.sync.read(frame.png), ms: frame.ms }))
  const { width, height } = decoded[0]!.image
  for (const { image } of decoded) {
    if (image.width !== width || image.height !== height) {
      throw new Error(
        `every frame must be the same size; got ${image.width}x${image.height} against ${width}x${height}`,
      )
    }
  }

  // ONE PALETTE FOR THE WHOLE ANIMATION. Per-frame palettes make the interface's greys shift
  // between frames, which reads as the panel flickering rather than as the data changing.
  const encoder = GIFEncoder()
  const palette = paletteOf(
    decoded.map((frame) => frame.image),
    keep,
  )

  decoded.forEach(({ image, ms }, index) => {
    const rgba = new Uint8ClampedArray(image.data)
    // The palette is written once, on the first frame. Passed on every frame, gifenc emits a
    // local colour table each time — fifteen identical copies of the same 768 bytes.
    encoder.writeFrame(applyPalette(rgba, palette), width, height, {
      delay: ms,
      ...(index === 0 ? { palette } : {}),
    })
  })

  encoder.finish()
  return Buffer.from(encoder.bytes())
}

/** The colours of the whole animation, sampled from every frame of it. */

/* `keep` is put in by hand rather than hoped for: a state chip is a few hundred pixels of a
   million, so quantizing merges it into the greys around it — and five chips being five colours is
   the one thing this picture is about. */
function paletteOf(images: readonly { data: Buffer }[], keep: readonly string[]): number[][] {
  const pixels = images.reduce(
    (count, image) => count + Math.ceil(image.data.length / 4 / EVERY),
    0,
  )
  const sample = new Uint8ClampedArray(pixels * 4)
  let at = 0
  for (const image of images) {
    for (let p = 0; p + 3 < image.data.length; p += 4 * EVERY) {
      sample[at] = image.data[p]!
      sample[at + 1] = image.data[p + 1]!
      sample[at + 2] = image.data[p + 2]!
      sample[at + 3] = 255
      at += 4
    }
  }
  const reserved = keep.map((hex) => [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16)))
  return [...reserved, ...quantize(sample, COLOURS - reserved.length)]
}

/** The colours a gif can actually draw, read back out of the bytes it is about to be written as. */

/* One assertion the run cannot make any other way: that the five state chips are still five
   colours in the finished picture. */
export function paletteIn(gif: Buffer): [number, number, number][] {
  const packed = gif[10]!
  if ((packed & 0x80) === 0) throw new Error('this gif has no global colour table')
  const size = 2 ** ((packed & 7) + 1)
  return Array.from({ length: size }, (_unused, index) => {
    const at = 13 + index * 3
    return [gif[at]!, gif[at + 1]!, gif[at + 2]!] as [number, number, number]
  })
}

/** How far the nearest entry of a palette is from a colour, in plain RGB distance. */
export function distanceTo(palette: readonly [number, number, number][], hex: string): number {
  const want = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16))
  return Math.round(
    Math.sqrt(
      Math.min(
        ...palette.map((entry) =>
          entry.reduce((sum, part, index) => sum + (part - want[index]!) ** 2, 0),
        ),
      ),
    ),
  )
}
