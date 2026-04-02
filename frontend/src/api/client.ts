import type { TableProfile, AuditLog } from '../types'

const BASE = '/api'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const data = await res.json()
      detail = data.detail || detail
    } catch {
      // ignore
    }
    throw new ApiError(detail, res.status)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export async function createSession(): Promise<{ session_id: string }> {
  return request('POST', '/session')
}

export async function getDefaults(): Promise<{
  superset_url: string
  superset_username: string
  llm_model: string
}> {
  return request('GET', '/config/defaults')
}

export async function updateConfig(
  sid: string,
  config: {
    db?: {
      type: string
      host: string
      port: number
      database: string
      username: string
      password: string
    }
    superset?: { url: string; username: string; password: string }
    llm_model?: string
  }
): Promise<void> {
  return request('PUT', `/sessions/${sid}/config`, config)
}

export async function testDbConnection(
  sid: string
): Promise<{ ok: boolean; message: string }> {
  return request('POST', `/sessions/${sid}/db/test`)
}

export async function profileTable(
  sid: string,
  tableName: string
): Promise<TableProfile> {
  return request('POST', `/sessions/${sid}/phase1/profile-table`, {
    table_name: tableName,
  })
}

export async function addTable(
  sid: string,
  tableName: string,
  columns: string[]
): Promise<void> {
  return request('POST', `/sessions/${sid}/phase1/add-table`, {
    table_name: tableName,
    selected_columns: columns,
  })
}

export async function confirmPhase1(sid: string): Promise<void> {
  return request('POST', `/sessions/${sid}/phase1/confirm`)
}

export async function confirmPhase2(
  sid: string,
  editedSql: string
): Promise<void> {
  return request('POST', `/sessions/${sid}/phase2/confirm`, {
    edited_sql: editedSql,
  })
}

export function exploreSSE(sid: string, prompt: string): EventSource {
  const url = `/api/sessions/${sid}/phase1/explore?prompt=${encodeURIComponent(prompt)}`
  return new EventSource(url)
}

export function generateQuerySSE(sid: string): EventSource {
  return new EventSource(`/api/sessions/${sid}/phase2/generate`)
}

export function planDashboardSSE(
  sid: string,
  params: {
    dataset_name: string
    dashboard_title: string
    requirements: string
  }
): EventSource {
  const qs = new URLSearchParams({
    dataset_name: params.dataset_name,
    dashboard_title: params.dashboard_title,
    requirements: params.requirements,
  }).toString()
  return new EventSource(`/api/sessions/${sid}/phase3/plan?${qs}`)
}

export function buildDashboardSSE(
  sid: string,
  params: { dashboard_id?: string; dry_run: boolean }
): EventSource {
  const qs = new URLSearchParams()
  if (params.dashboard_id) qs.set('dashboard_id', params.dashboard_id)
  qs.set('dry_run', String(params.dry_run))
  return new EventSource(`/api/sessions/${sid}/phase3/build?${qs.toString()}`)
}

export async function getAuditLog(sessionId: string): Promise<AuditLog> {
  return request('GET', `/sessions/${sessionId}/audit`)
}

export async function clearAuditLog(sessionId: string): Promise<void> {
  return request('DELETE', `/sessions/${sessionId}/audit`)
}
