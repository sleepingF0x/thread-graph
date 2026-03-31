import client from './client'
import type { Term } from '../types'

export const getTerms = (params?: { status?: string; needs_review?: boolean; group_id?: number; limit?: number; offset?: number }) =>
  client.get<Term[]>('/terms/', { params }).then((r) => r.data)

export const createTerm = (data: { word: string; variants?: string[]; meanings?: object[]; examples?: string[]; group_id?: number }) =>
  client.post<Term>('/terms/', data).then((r) => r.data)

export const patchTerm = (id: string, data: Partial<Pick<Term, 'word' | 'variants' | 'meanings' | 'examples' | 'status' | 'needs_review'>>) =>
  client.patch<Term>(`/terms/${id}`, data).then((r) => r.data)
