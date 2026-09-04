/**
 * The parts of Chart.js this panel uses, registered once. Nothing is registered by default so a
 * build can drop what it does not draw; imported for its side effect by the two figures.
 */

import {
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  Legend,
  LineController,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
} from 'chart.js'

Chart.register(
  BarController,
  BarElement,
  LineController,
  LineElement,
  PointElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
)
