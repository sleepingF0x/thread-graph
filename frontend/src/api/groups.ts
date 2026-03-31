import client from './client'
import type { Group, SyncJob } from '../types'

export const getGroups = () =>
  client.get<Group[]>('/groups/').then((r) => r.data)

export const addGroup = (id: number, name: string, type: string) =>
  client.post<{ id: number; name: string; sync_job_id: string }>('/groups/', { id, name, type }).then((r) => r.data)

export const removeGroup = (id: number) =>
  client.delete(`/groups/${id}`).then((r) => r.data)

export const triggerSync = (id: number, fromDays = 30) =>
  client.post(`/groups/${id}/sync`, null, { params: { from_days: fromDays } }).then((r) => r.data)

export const getSyncJobs = () =>
  client.get<SyncJob[]>('/groups/sync_jobs').then((r) => r.data)

export const cancelSyncJob = (jobId: string) =>
  client.post(`/groups/sync_jobs/${jobId}/cancel`).then((r) => r.data)
