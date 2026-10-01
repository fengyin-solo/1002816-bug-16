<template>
  <section class="page" data-module="fertilize">
    <header class="page-head">
      <div>
        <h2>施肥作业管理</h2>
        <p class="page-desc">填报人只写不确认，确认归本组组长；只读岗不能碰肥料类型与施肥量；同一片地重复提交只认第一次。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记施肥记录</button>
        <button class="btn" type="button" @click="exportRows">导出施肥作业清单</button>
      </div>
    </header>

    <form class="filter-bar" @submit.prevent>
      <label class="filter-item">
        <span>当前操作人</span>
        <input v-model="session.operator" placeholder="操作人姓名" />
      </label>
      <label class="filter-item">
        <span>角色</span>
        <select v-model="session.role">
          <option v-for="role in OPERATOR_ROLES" :key="role" :value="role">{{ role }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>所属班组</span>
        <select v-model="session.group">
          <option v-for="group in WORK_GROUPS" :key="group" :value="group">{{ group }}</option>
        </select>
      </label>
    </form>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section v-if="showCreate" class="panel">
      <h3 class="panel-title">登记施肥记录</h3>
      <p v-if="session.isReadonly" class="error-text">只读岗只能查看，肥料类型与施肥量不可填写</p>
      <div class="panel-grid">
        <label v-for="field in createFields" :key="field.key" class="filter-item">
          <span>{{ field.label }}</span>
          <input
            v-model="createForm[field.key]"
            :disabled="session.isReadonly && field.locked"
            :placeholder="`请输入${field.label}`"
          />
        </label>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" :disabled="session.isReadonly" @click="submitCreate">提交填报</button>
        <button class="btn ghost" type="button" @click="showCreate = false">取消</button>
      </div>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="confirmRow(row)">确认施肥</button>
            <button class="link" type="button" @click="runAction('登记过量', row)">登记过量</button>
            <button class="link" type="button" @click="runAction('补施肥料', row)">补施肥料</button>
            <button class="link" type="button" @click="transferRow(row)">转交</button>
            <button class="link" type="button" @click="showHistory(row)">转移记录</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无施肥作业数据，可先登记施肥记录</td>
        </tr>
      </tbody>
    </table>

    <section v-if="historyRow" class="panel">
      <h3 class="panel-title">
        转移记录：{{ historyRow.施肥编号 }}（当前经手人：{{ historyRow.经手人 || '—' }}）
      </h3>
      <table class="data-table">
        <thead>
          <tr><th>时间</th><th>原经手人</th><th>新经手人</th><th>操作人</th><th>备注</th></tr>
        </thead>
        <tbody>
          <tr v-for="(log, index) in historyRow.转移记录 ?? []" :key="index">
            <td>{{ log.时间 }}</td>
            <td>{{ log.原经手人 }}</td>
            <td>{{ log.新经手人 }}</td>
            <td>{{ log.操作人 }}</td>
            <td>{{ log.备注 || '—' }}</td>
          </tr>
          <tr v-if="!(historyRow.转移记录 ?? []).length">
            <td colspan="5" class="empty-state">暂无转移记录，经手人自填报起未变更</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条施肥作业记录</span>
      <span v-if="notice" :class="noticeOk ? 'ok-text' : 'error-text'">{{ notice }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { OPERATOR_ROLES, WORK_GROUPS, useSessionStore } from '@/stores/session'

type TransferLog = { 时间: string; 原经手人: string; 新经手人: string; 操作人: string; 备注: string }
type Row = Record<string, any> & { id: number | string; 转移记录?: TransferLog[] }
type ActionPayload = { ok: boolean; message: string; entry?: Row | null }

const ENDPOINT = '/api/fertilize'
const columns = ["施肥编号", "施肥区域", "肥料类型", "施肥量", "施肥面积", "所属班组", "填报人", "经手人", "确认人", "施肥状态"]
const createFields = [
  { key: '施肥区域', label: '施肥区域', locked: false },
  { key: '肥料类型', label: '肥料类型', locked: true },
  { key: '施肥量', label: '施肥量', locked: true },
  { key: '施肥面积', label: '施肥面积(亩)', locked: true },
  { key: '施肥方式', label: '施肥方式', locked: false },
  { key: '施肥日期', label: '施肥日期', locked: false },
]
// 筛选框与后端查询参数的对应关系
const filterParamMap: Record<string, string> = { 施肥编号: 'keyword', 施肥区域: 'region', 肥料类型: 'fertilizer' }
const filterFields = Object.keys(filterParamMap)

const session = useSessionStore()

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref([
  { label: '待确认', value: 0 },
  { label: '已施肥', value: 0 },
  { label: '过量', value: 0 },
  { label: '已施面积(亩)', value: 0 },
])
const notice = ref('')
const noticeOk = ref(true)
const filters = ref<Record<string, string>>({})
const showCreate = ref(false)
const createForm = reactive<Record<string, string>>({})
const historyRow = ref<Row | null>(null)

function operatorContext() {
  return { operator: session.operator, role: session.role, group: session.group }
}

function setNotice(message: string, ok: boolean) {
  notice.value = message
  noticeOk.value = ok
}

async function parseAction(response: Response): Promise<ActionPayload> {
  const payload = (await response.json()) as ActionPayload
  if (!response.ok) {
    throw new Error(payload.message || `接口返回 ${response.status}`)
  }
  return payload
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  if (session.isReadonly) {
    setNotice('只读岗只能查看，不能登记施肥记录：肥料类型与施肥量对只读岗不可写', false)
    return
  }
  showCreate.value = true
}

async function submitCreate() {
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm, ...operatorContext() } }),
    })
    const payload = await parseAction(response)
    setNotice(payload.message, payload.ok)
    if (payload.ok) {
      showCreate.value = false
      for (const field of createFields) createForm[field.key] = ''
    }
  } catch (error) {
    setNotice(error instanceof Error ? error.message : '施肥记录登记失败', false)
  }
  await refresh()
}

async function runAction(action: string, row: Row, extra: Record<string, string> = {}) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, ...operatorContext(), ...extra } }),
    })
    const payload = await parseAction(response)
    setNotice(payload.message, payload.ok)
  } catch (error) {
    setNotice(error instanceof Error ? error.message : '施肥作业操作失败', false)
  }
  // 无论成败都以服务端明细为准重刷，避免页面上残留旧值
  await refresh()
}

async function confirmRow(row: Row) {
  const extra: Record<string, string> = {}
  if (session.role === '组长') {
    const corrected = window.prompt('如需更正施肥量请在此输入，留空则按填报值确认（冲突时以组长确认为准）', '')
    if (corrected === null) return
    if (corrected.trim()) extra['施肥量'] = corrected.trim()
  }
  await runAction('确认施肥', row, extra)
}

async function transferRow(row: Row) {
  const target = window.prompt(`当前经手人：${row.经手人 || '—'}，请输入新经手人姓名`, '')
  if (!target || !target.trim()) return
  await runAction('转交', row, { 新经手人: target.trim() })
}

function showHistory(row: Row) {
  historyRow.value = historyRow.value?.id === row.id ? null : row
}

async function reload() {
  const query = new URLSearchParams()
  for (const [field, param] of Object.entries(filterParamMap)) {
    const value = (filters.value[field] ?? '').trim()
    if (value) query.set(param, value)
  }
  const response = await request(`${ENDPOINT}?${query.toString()}`)
  const payload = await response.json()
  rows.value = payload.items ?? []
  total.value = payload.total ?? rows.value.length
}

async function loadSummary() {
  const response = await request(`${ENDPOINT}/summary`)
  const payload = await response.json()
  stats.value = [
    { label: '待确认', value: payload.待确认 ?? 0 },
    { label: '已施肥', value: payload.已施肥 ?? 0 },
    { label: '过量', value: payload.过量 ?? 0 },
    { label: '已施面积(亩)', value: payload.已施面积 ?? 0 },
  ]
}

async function refresh() {
  try {
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    setNotice(error instanceof Error ? error.message : '施肥作业列表读取失败', false)
  }
}

onMounted(refresh)
</script>
