<script setup lang="ts">
/**
 * Bars, one colour for the series or one per bar. The numbers are also written into the page as a
 * list nobody sees: a canvas is a picture to a screen reader, and "chart" is not an answer.
 */

import { computed } from 'vue'
import { Bar } from 'vue-chartjs'

import { chartOptions, MAX_BAR } from '@/charts/options'
import { colour, type SeriesRole } from '@/charts/palette'
import '@/charts/register'

const props = defineProps<{
  title: string
  labels: string[]
  values: number[]
  /** One role for the whole series, or one per bar where each bar is its own category. */
  roles: SeriesRole | SeriesRole[]
  horizontal?: boolean | undefined
  /** How a value is said in the tooltip and in the list a screen reader gets. */
  format?: ((value: number) => string) | undefined
  /** How a value is said on the axis, when that differs. */
  tick?: ((value: number) => string) | undefined
}>()

const fills = computed(() => {
  const roles = props.roles
  return Array.isArray(roles)
    ? roles.map((role) => colour(role))
    : props.values.map(() => colour(roles))
})

const data = computed(() => ({
  labels: props.labels,
  datasets: [
    {
      label: props.title,
      data: props.values,
      backgroundColor: fills.value,
      borderWidth: 0,
      maxBarThickness: MAX_BAR,
    },
  ],
}))

const options = computed(() =>
  chartOptions({
    horizontal: props.horizontal ?? false,
    ...(props.format === undefined ? {} : { format: props.format }),
    ...(props.tick === undefined ? {} : { tick: props.tick }),
  }),
)

const said = computed(() =>
  props.labels.map((label, index) => ({
    label,
    value: props.format?.(props.values[index] ?? 0) ?? String(props.values[index] ?? 0),
  })),
)
</script>

<template>
  <div class="h-chart-plot">
    <Bar :data="data" :options="options" :aria-hidden="true" />
  </div>
  <dl class="sr-only">
    <template v-for="row in said" :key="row.label">
      <dt>{{ row.label }}</dt>
      <dd>{{ row.value }}</dd>
    </template>
  </dl>
</template>
