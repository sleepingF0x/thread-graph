import client from './client'
import type { Topic, TopicDetail } from '../types'

export const getTopics = (groupId: number, params?: { from_ts?: string; to_ts?: string; limit?: number; offset?: number }) =>
  client.get<Topic[]>(`/groups/${groupId}/topics`, { params }).then((r) => r.data)

export const getTopicDetail = (groupId: number, topicId: string) =>
  client.get<TopicDetail>(`/groups/${groupId}/topics/${topicId}`).then((r) => r.data)

export const getActiveTopics = (limit = 20) =>
  client.get<Topic[]>('/topics/active', { params: { limit } }).then((r) => r.data)

export const reprocessTopic = (topicId: string) =>
  client.post(`/topics/${topicId}/reprocess`).then((r) => r.data)
