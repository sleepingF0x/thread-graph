import client from './client'
import type { QaSession } from '../types'

export const askQuestion = (question: string, groupId?: number, limit = 5) =>
  client.post<{ session_id: string | null; answer: string; sources: object[] }>('/qa', { question, group_id: groupId, limit }).then((r) => r.data)

export const getQaSessions = (params?: { limit?: number; offset?: number; group_id?: number }) =>
  client.get<QaSession[]>('/qa/sessions', { params }).then((r) => r.data)
