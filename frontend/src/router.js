import { createRouter, createWebHistory } from 'vue-router'
import { usersStore } from '@/stores/user'
import { sessionStore } from '@/stores/session'
import { studentStore } from '@/stores/student'

const routes = [
  { path: "/payments-account", name: "Payments account", meta: { paymentsAccount: true }, component: () => import("@/pages/PaymentsAccount.vue") },
  { path: '/', redirect: '/schedule' },
  {
    path: '/schedule',
    name: 'Schedule',
    component: () => import('@/pages/Schedule.vue'),
  },
  {
    path: '/grades',
    name: 'Grades',
    component: () => import('@/pages/Grades.vue'),
  },
  {
    path: '/fees',
    name: 'Fees',
    component: () => import('@/pages/Fees.vue'),
  },
  {
    path: '/attendance',
    name: 'Attendance',
    component: () => import('@/pages/Attendance.vue'),
  },
  {
    path: '/:catchAll(.*)',
    redirect: '/schedule',
  },
]

let router = createRouter({
  history: createWebHistory('/student-portal'),
  routes,
})

router.beforeEach(async (to, from) => {
  const { isLoggedIn, user: sessionUser } = sessionStore()
  const { user } = usersStore()
  const { student } = studentStore()

  if (!isLoggedIn) {
    window.location.href = '/login?redirect-to=' + encodeURIComponent('/student-portal' + to.fullPath)
    return false
  }

  if (to.meta.paymentsAccount) {
    if (!user.fetched) await user.reload()
    if (!(user.data?.roles || []).includes('System Manager')) return { path: '/fees' }
    return true
  }

  // Identity and enrollment are shared by portal routes; load once per session.
  await Promise.all([
    user.fetched ? Promise.resolve() : user.reload(),
    student.fetched ? Promise.resolve() : student.reload(),
  ])
  if (!student.data) return false
})

export default router
