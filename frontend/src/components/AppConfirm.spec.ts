/**
 * The pause before something nothing can undo, and the one thing it must not do.
 *
 * WHILE THE REQUEST IS OUT, THIS DIALOG MAY NOT CLOSE BY ANY ROUTE. The dismissing button, the
 * Escape key and a click outside all leave the operation running and the dialog gone — and the
 * dismissing button is called `Keep subscription`, which is a promise it cannot keep. Disabling
 * the button closed one of the three; the first version of this fix did exactly that and left the
 * keyboard open, which is why the close itself is refused here rather than each of its doors.
 */

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { defineComponent, h, ref } from 'vue'

import AppConfirm from '@/components/AppConfirm.vue'

/** A host that owns `open`, because the refusal is a refusal to write it.
 *
 *  Awaited: the content is portalled, so it reaches the body a tick after the mount returns. */
async function host(busy: boolean) {
  const open = ref(true)
  const wrapper = mount(
    defineComponent({
      setup() {
        return () =>
          h(AppConfirm, {
            open: open.value,
            'onUpdate:open': (next: boolean) => (open.value = next),
            action: 'Cancel subscription',
            busyAction: 'Cancelling the subscription…',
            dismiss: 'Keep subscription',
            title: 'Access runs to 09 Sep 2026 and then stops.',
            busy,
          })
      },
    }),
    { attachTo: document.body },
  )
  await flushPromises()
  return { open, wrapper }
}

function inDialog(label: string): HTMLButtonElement | undefined {
  const dialog = document.querySelector('[role="alertdialog"]')
  return [...(dialog?.querySelectorAll('button') ?? [])].find(
    (each) => each.textContent?.trim() === label,
  ) as HTMLButtonElement | undefined
}

function pressEscape(): void {
  document
    .querySelector('[role="alertdialog"]')
    ?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
}

let mounted: ReturnType<typeof mount> | null = null

afterEach(() => {
  mounted?.unmount()
  mounted = null
  document.body.innerHTML = ''
})

describe('at rest', () => {
  it('names the action, the way out and the consequence', async () => {
    const { wrapper } = await host(false)
    mounted = wrapper

    expect(inDialog('Cancel subscription')).toBeDefined()
    expect(inDialog('Keep subscription')).toBeDefined()
    // Never a button labelled `Cancel` on a dialog that cancels: one word, two opposite actions.
    expect(inDialog('Cancel')).toBeUndefined()
    expect(document.body.textContent).toContain('Access runs to 09 Sep 2026 and then stops.')
  })

  it('lets the keyboard out', async () => {
    const { open, wrapper } = await host(false)
    mounted = wrapper

    pressEscape()
    await wrapper.vm.$nextTick()

    expect(open.value).toBe(false)
  })

  it('lets the dismissing button out', async () => {
    const { open, wrapper } = await host(false)
    mounted = wrapper

    inDialog('Keep subscription')?.click()
    await wrapper.vm.$nextTick()

    expect(open.value).toBe(false)
  })
})

describe('while the request is out', () => {
  it('says so in the confirming button rather than greying it', async () => {
    const { wrapper } = await host(true)
    mounted = wrapper

    expect(inDialog('Cancelling the subscription…')).toBeDefined()
    expect(inDialog('Cancelling the subscription…')?.hasAttribute('disabled')).toBe(false)
  })

  it('refuses the dismissing button', async () => {
    const { open, wrapper } = await host(true)
    mounted = wrapper

    expect(inDialog('Keep subscription')?.hasAttribute('disabled')).toBe(true)
    inDialog('Keep subscription')?.click()
    await wrapper.vm.$nextTick()

    expect(open.value).toBe(true)
  })

  // The door the first version of this fix left open.
  it('refuses the keyboard', async () => {
    const { open, wrapper } = await host(true)
    mounted = wrapper

    pressEscape()
    await wrapper.vm.$nextTick()

    expect(open.value).toBe(true)
  })
})
