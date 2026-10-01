/** 统一请求封装：拼后端地址、带上当班人身份、禁缓存、抛网络错误、给页脚留一句可读的说明。 */
import { useSessionStore } from '@/stores/session'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

// 请求头的值只能是 ASCII，中文姓名/岗位先编码，后端再解码还原。
function identityHeaders(): Record<string, string> {
  try {
    const session = useSessionStore()
    return {
      'X-Operator-Name': encodeURIComponent(session.operator),
      'X-Operator-Role': encodeURIComponent(session.role),
      'X-Operator-Group': encodeURIComponent(session.group),
    }
  } catch {
    return {}
  }
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, {
    cache: 'no-store',
    ...init,
    headers: { 'Content-Type': 'application/json', ...identityHeaders(), ...(init?.headers ?? {}) },
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}
