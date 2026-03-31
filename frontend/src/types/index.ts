export interface Group {
  id: number
  name: string
  type: string
  last_synced_at: string | null
}

export interface Topic {
  id: string
  name: string
  summary: string
  is_active: boolean
  slice_count: number
  time_start: string
  time_end: string
  group_id: number
  group_name?: string
}

export interface Message {
  id: number
  text: string
  ts: string
  sender_id: number
}

export interface Slice {
  id: string
  time_start: string
  time_end: string
  summary: string
  messages: Message[]
}

export interface TopicDetail extends Topic {
  slices: Slice[]
}

export interface Term {
  id: string
  word: string
  variants: string[]
  meanings: { meaning: string; confidence: number }[]
  examples: string[]
  status: string
  needs_review: boolean
  group_id: number | null
  created_at: string
  updated_at: string
}

export interface QaSession {
  id: string
  question: string
  answer_preview: string
  group_id: number | null
  created_at: string
}

export interface SyncJob {
  id: string
  group_id: number
  status: string
  from_ts: string
  to_ts: string
  checkpoint_message_id: number | null
  error_message: string | null
}

export interface AuthStatus {
  authorized: boolean
}

export interface WsEvent {
  event: string
  payload: Record<string, unknown>
  dedup_key: string
}
