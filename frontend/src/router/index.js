/**
 * ==============================================================================
 * CLIENT-SIDE ROUTER
 * ==============================================================================
 * File: frontend/src/router/index.js
 *
 * Two pages:
 *   /         the viability dossier (main page)
 *   /metrics  dashboard of the request metrics saved by the backend
 *
 * History mode gives clean URLs. In production CloudFront answers a missing
 * path with /index.html (SPA fallback), so opening /metrics directly works.
 * The metrics page is loaded on demand, so the main page does not download the
 * charting library.
 */
import { createRouter, createWebHistory } from 'vue-router'

import HomeView from '../views/HomeView.vue'

const routes = [
  { path: '/', name: 'home', component: HomeView, meta: { title: 'Geo-Yield-AI · Dossier de viabilidad' } },
  {
    path: '/metrics',
    name: 'metrics',
    component: () => import('../views/MetricsView.vue'),
    meta: { title: 'Geo-Yield-AI · Métricas' },
  },
  // The RAG quality dashboard lives in a tab of /metrics; the old address keeps working.
  { path: '/evals', redirect: { path: '/metrics', query: { tab: 'rag' } } },
  // Any other path goes back to the main page instead of showing a blank screen.
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  if (to.meta?.title) document.title = to.meta.title
})

export default router
