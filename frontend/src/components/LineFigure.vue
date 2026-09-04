<script setup lang="ts">
/**
 * Two lines, told apart by more than their hue. `--success-text` and `--danger-text` are 1.47:1
 * apart, so the outflow line is dashed as well as red and a reader who cannot separate the two
 * colours still has two lines.
 */

import { computed } from 'vue'
import { Line } from 'vue-chartjs'

import { chartOptions } from '@/charts/options'
import { colour, type SeriesRole } from '@/charts/palette'
import '@/charts/register'

const props = defineProps<{
  labels: string[]
  series: { label: string; values: number[]; role: SeriesRole; dashed?: boolean }[]
}>()

const data = computed(() => ({
  labels: props.labels,
  datasets: props.series.map((line) => ({
    label: line.label,
    data: line.values,
    borderColor: colour(line.role),
    backgroundColor: colour(line.role),
    borderDash: line.dashed === true ? [6, 4] : [],
    borderWidth: 2,
    pointRadius: 0,
    pointHitRadius: 12,
    tension: 0,
  })),
}))

const options = computed(() => chartOptions({ legend: true }))

const said = computed(() =>
  props.labels.map((label, index) => ({
    label,
    values: props.series.map((line) => `${line.label} ${line.values[index] ?? 0}`).join(', '),
  })),
)
</script>

<template>
  <div class="h-chart-plot">
    <Line :data="data" :options="options" :aria-hidden="true" />
  </div>
  <dl class="sr-only">
    <template v-for="row in said" :key="row.label">
      <dt>{{ row.label }}</dt>
      <dd>{{ row.values }}</dd>
    </template>
  </dl>
</template>
