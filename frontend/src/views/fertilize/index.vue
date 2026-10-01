<template>
  <section class="page" data-module="fertilize">
    <header class="page-head">
      <div>
        <h2>施肥作业管理</h2>
        <p class="page-desc">填报人只写不确认，确认归本组组长；只读岗不能改肥料类型与施肥量；同一片地重复提交只认第一次。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记施肥记录</button>
        <button class="btn" type="button" @click="exportRows">导出施肥作业清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reloadAll">
      <label class="filter-item">
        <span>施肥编号</span>
        <input v-model="keyword" placeholder="按施肥编号检索" />
      </label>
      <label class="filter-item">
        <span>施肥状态</span>
        <select v-model="statusFilter">
          <option value="">全部</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
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
          <td v-for="column in columns" :key="column">{{ display(row, column) }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openConfirm(row)">确认</button>
            <button class="link" type="button" @click="openEdit(row)">编辑</button>
            <button class="link" type="button" @click="openTransfer(row)">改交</button>
            <button class="link" type="button" @click="runAction('登记过量', row)">登记过量</button>
            <button class="link" type="button" @click="runAction('补施肥料', row)">补施肥料</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无施肥作业数据，可先登记施肥记录</td>
        </tr>
      </tbody>
    </table>

    <section class="board">
      <h3 class="board-title">施肥看板（已施面积随明细实时重算）</h3>
      <div class="board-row">
        <article v-for="group in boardGroups" :key="group.班组" class="board-card">
          <span class="stat-label">{{ group.班组 }}</span>
          <strong class="stat-value">{{ group.已施面积 }} 亩</strong>
          <span class="board-sub">待确认 {{ group.待确认面积 }} 亩 · {{ group.记录数 }} 条记录</span>
        </article>
      </div>
      <table class="data-table">
        <thead>
          <tr><th>施肥编号</th><th>施肥区域</th><th>经手人</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="handler in boardHandlers" :key="handler.id">
            <td>{{ handler.施肥编号 }}</td>
            <td>{{ handler.施肥区域 }}</td>
            <td>{{ handler.经手人 }}</td>
            <td>{{ handler.状态 }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条施肥作业记录</span>
      <span v-if="noticeMessage" class="success-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="dialog === 'create'" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>登记施肥记录（{{ session.operator }} · {{ session.role }} · {{ session.group }}）</h3>
        <div class="form-grid">
          <label v-for="field in createFields" :key="field" class="form-item">
            <span>{{ field }}</span>
            <input v-model="form[field]" :placeholder="`请输入${field}`" />
          </label>
        </div>
        <p class="modal-tip">同一片地重复提交只认第一次；登记后进入「待确认」，由本组组长确认。</p>
        <footer class="modal-foot">
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" @click="submitCreate">提交登记</button>
        </footer>
      </div>
    </div>

    <div v-if="dialog === 'edit'" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>编辑施肥记录 {{ activeRow?.施肥编号 }}</h3>
        <div class="form-grid">
          <label v-for="field in editFields" :key="field" class="form-item">
            <span>{{ field }}</span>
            <input v-model="form[field]" :disabled="isReadonlyLocked(field)" />
          </label>
        </div>
        <p v-if="session.isReadonly" class="modal-tip">只读岗不能修改肥料类型与施肥量，其余字段可改。</p>
        <footer class="modal-foot">
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" @click="submitEdit">保存修改</button>
        </footer>
      </div>
    </div>

    <div v-if="dialog === 'confirm'" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>确认施肥记录 {{ activeRow?.施肥编号 }}（{{ activeRow?.所属班组 }}）</h3>
        <p class="modal-tip">确认归本组组长；与填报内容冲突时，以组长这里确认的值为准。</p>
        <div class="form-grid">
          <label v-for="field in confirmFields" :key="field" class="form-item">
            <span>{{ field }}</span>
            <input v-model="form[field]" />
          </label>
        </div>
        <footer class="modal-foot">
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" @click="submitConfirm">确认完成</button>
        </footer>
      </div>
    </div>

    <div v-if="dialog === 'transfer'" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>改交经手人（当前：{{ activeRow?.经手人 }}）</h3>
        <div class="form-grid">
          <label class="form-item">
            <span>新经手人</span>
            <input v-model="form.新经手人" placeholder="接手人姓名" />
          </label>
          <label class="form-item">
            <span>转移说明</span>
            <input v-model="form.转移说明" placeholder="为什么改交" />
          </label>
        </div>
        <p class="modal-tip">改交会写入经手记录留痕，列表、看板、导出读到的经手人保持一致。</p>
        <footer class="modal-foot">
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" @click="submitTransfer">确认改交</button>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, any>
type BoardGroup = { 班组: string; 记录数: number; 已施面积: number; 待确认面积: number }
type BoardHandler = { id: number; 施肥编号: string; 施肥区域: string; 经手人: string; 状态: string }
type Board = {
  已施面积合计: number
  待确认条数: number
  已确认条数: number
  异常条数: number
  班组: BoardGroup[]
  经手人一览: BoardHandler[]
}

const ENDPOINT = '/api/fertilize'
const columns = ['施肥编号', '施肥区域', '肥料类型', '施肥量', '施肥面积', '所属班组', '填报人', '经手人', '确认人', '施肥状态']
const statuses = ['待确认', '已确认', '过量', '已补施']
const createFields = ['施肥编号', '施肥区域', '肥料类型', '施肥量', '施肥面积', '施肥方式', '施肥日期', '作业人员']
const editFields = ['施肥区域', '肥料类型', '施肥量', '施肥面积', '施肥方式', '施肥日期', '作业人员']
const confirmFields = ['肥料类型', '施肥量', '施肥面积', '施肥方式', '施肥日期', '作业人员']
const READONLY_LOCKED = ['肥料类型', '施肥量']

const session = useSessionStore()

const rows = ref<Row[]>([])
const total = ref(0)
const keyword = ref('')
const statusFilter = ref('')
const errorMessage = ref('')
const noticeMessage = ref('')
const dialog = ref<'' | 'create' | 'edit' | 'confirm' | 'transfer'>('')
const activeRow = ref<Row | null>(null)
const form = reactive<Record<string, string>>({})
const board = ref<Board>({ 已施面积合计: 0, 待确认条数: 0, 已确认条数: 0, 异常条数: 0, 班组: [], 经手人一览: [] })

const stats = computed(() => [
  { label: '已施面积(亩)', value: board.value.已施面积合计 },
  { label: '待确认', value: board.value.待确认条数 },
  { label: '已确认', value: board.value.已确认条数 },
  { label: '异常', value: board.value.异常条数 },
])
const boardGroups = computed(() => board.value.班组)
const boardHandlers = computed(() => board.value.经手人一览)

function display(row: Row, column: string) {
  const value = row[column]
  return value === undefined || value === null || value === '' ? '—' : value
}

function isReadonlyLocked(field: string) {
  return session.isReadonly && READONLY_LOCKED.includes(field)
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reloadAll()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function fillForm(fields: string[], source?: Row) {
  for (const key of Object.keys(form)) delete form[key]
  for (const field of fields) form[field] = source ? String(source[field] ?? '') : ''
}

function openCreate() {
  fillForm(createFields)
  form['施肥日期'] = new Date().toISOString().slice(0, 10)
  dialog.value = 'create'
}

function openEdit(row: Row) {
  activeRow.value = row
  fillForm(editFields, row)
  dialog.value = 'edit'
}

function openConfirm(row: Row) {
  activeRow.value = row
  fillForm(confirmFields, row)
  dialog.value = 'confirm'
}

function openTransfer(row: Row) {
  activeRow.value = row
  fillForm(['新经手人', '转移说明'])
  dialog.value = 'transfer'
}

function closeDialog() {
  dialog.value = ''
  activeRow.value = null
}

async function send(path: string, init: RequestInit): Promise<boolean> {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(path, init)
    const payload: any = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(payload?.detail ?? `接口返回 ${response.status}`)
    }
    if (payload && payload.ok === false) {
      errorMessage.value = payload.message ?? '操作未生效'
      return false
    }
    noticeMessage.value = payload?.message ?? '操作成功'
    return true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '施肥作业操作失败'
    return false
  }
}

async function submitCreate() {
  const values: Record<string, string> = {}
  for (const field of createFields) values[field] = form[field] ?? ''
  const ok = await send(ENDPOINT, { method: 'POST', body: JSON.stringify({ values }) })
  if (ok) {
    closeDialog()
    await reloadAll()
  }
}

async function submitEdit() {
  if (!activeRow.value) return
  const values: Record<string, string> = {}
  for (const field of editFields) values[field] = form[field] ?? ''
  const ok = await send(`${ENDPOINT}/${activeRow.value.id}`, { method: 'PUT', body: JSON.stringify({ values }) })
  if (ok) {
    closeDialog()
    await reloadAll()
  }
}

async function submitConfirm() {
  if (!activeRow.value) return
  const values: Record<string, string> = {}
  for (const field of confirmFields) values[field] = form[field] ?? ''
  const ok = await send(`${ENDPOINT}/${activeRow.value.id}/confirm`, { method: 'POST', body: JSON.stringify({ values }) })
  if (ok) {
    closeDialog()
    await reloadAll()
  }
}

async function submitTransfer() {
  if (!activeRow.value) return
  const values = { target: form['新经手人'] ?? '', note: form['转移说明'] ?? '' }
  const ok = await send(`${ENDPOINT}/${activeRow.value.id}/transfer`, { method: 'POST', body: JSON.stringify({ values }) })
  if (ok) {
    closeDialog()
    await reloadAll()
  }
}

async function runAction(action: string, row: Row) {
  const ok = await send(`${ENDPOINT}/${row.id}/actions`, { method: 'POST', body: JSON.stringify({ values: { action } }) })
  if (ok) await reloadAll()
}

async function reload() {
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  const response = await request(`${ENDPOINT}?${query.toString()}`)
  const payload = await response.json()
  rows.value = payload.items ?? []
  total.value = payload.total ?? rows.value.length
}

async function loadBoard() {
  const response = await request(`${ENDPOINT}/board`)
  board.value = await response.json()
}

async function reloadAll() {
  errorMessage.value = ''
  try {
    await Promise.all([reload(), loadBoard()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '施肥作业列表读取失败'
  }
}

onMounted(reloadAll)
</script>
