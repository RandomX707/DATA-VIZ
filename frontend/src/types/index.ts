export interface SessionConfig {
  db: DbConfig
  superset: SupersetConfig
  llmModel: string
}

export interface DbConfig {
  type: 'postgresql' | 'mysql' | 'mongodb'
  host: string
  port: number
  database: string
  username: string
  password: string
}

export interface SupersetConfig {
  url: string
  username: string
  password: string
}

export interface ColumnProfile {
  column_name: string
  data_type: string
  sample_values: string[]
  null_pct: number
  is_likely_pk: boolean
  is_likely_fk: boolean
  is_likely_date: boolean
}

export interface TableProfile {
  table_name: string
  row_count: number
  columns: ColumnProfile[]
  sample_rows: Record<string, unknown>[]
}

export interface SchemaMap {
  all_tables: string[]
  profiled_tables: TableProfile[]
  suggested_primary: string
  suggested_joins: string[]
  agent_reasoning: string
}

export interface QueryPlan {
  sql: string
  calculated_columns: { name: string; expression: string; description: string }[]
  dataset_name_suggestion: string
  grain_description: string
  agent_reasoning: string
}

export interface DatasetQAReport {
  passed: boolean
  row_count: number
  duplicate_row_count: number
  issues: string[]
  suggestions: string[]
  sample_rows: Record<string, unknown>[]
}

export interface DatasetColumn {
  column_name: string
  type: string
  is_dttm: boolean
  expression: string | null
  distinct_values: string[] | null
}

export interface DatasetInfo {
  id: number
  name: string
  columns: DatasetColumn[]
  metrics: Record<string, unknown>[]
}

export interface ChartSpec {
  title: string
  viz_type: string
  metrics: Record<string, unknown>[]
  groupby: string[]
  time_column: string | null
  time_grain: string | null
  width: number
  reasoning: string
}

export interface FilterSpec {
  column_name: string
  filter_type: string
  label: string
  default_value: string | null
}

export interface DashboardPlan {
  dashboard_title: string
  charts: ChartSpec[]
  filters: FilterSpec[]
  reasoning: string
}

export interface QAReport {
  passed: boolean
  issues: string[]
  suggestions: string[]
}

export interface SSEEvent {
  type: 'progress' | 'done' | 'error'
  message?: string
  step?: number
  total?: number
  data?: unknown
}

export interface ExcludedTable {
  profiled: boolean
  profile: TableProfile | null
  selected_columns: string[]
  added: boolean
  error: string | null
}

export interface AuditEntry {
  id: string
  timestamp: string
  phase: 0 | 1 | 2 | 3
  event_type: string
  title: string
  detail: string
  data: Record<string, unknown> | null
  status: 'info' | 'success' | 'warning' | 'error'
}

export interface AuditLog {
  entries: AuditEntry[]
}
