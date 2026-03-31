import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getGroups } from '../api/groups'
import { getTopics, getTopicDetail } from '../api/topics'
import { askQuestion } from '../api/qa'
import type { Topic, Slice } from '../types'

function formatTs(ts: string): string {
  return new Date(ts).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function summarySplit(summary: string): string {
  const lines = summary.split('\n')
  return lines.slice(0, 2).join('\n')
}

export default function Topics() {
  const [selectedGroup, setSelectedGroup] = useState<number | null>(null)
  const [fromTs, setFromTs] = useState('')
  const [toTs, setToTs] = useState('')
  const [expandedTopicId, setExpandedTopicId] = useState<string | null>(null)
  const [expandedSliceId, setExpandedSliceId] = useState<string | null>(null)
  const [question, setQuestion] = useState('')
  const [qaResult, setQaResult] = useState<{ answer: string; sources: object[] } | null>(null)
  const [isAsking, setIsAsking] = useState(false)

  const { data: groups } = useQuery({
    queryKey: ['groups'],
    queryFn: getGroups,
  })

  const { data: topics, isLoading: topicsLoading, isError: topicsError } = useQuery({
    queryKey: ['topics', selectedGroup, fromTs, toTs],
    queryFn: () => getTopics(selectedGroup!, { from_ts: fromTs || undefined, to_ts: toTs || undefined }),
    enabled: selectedGroup !== null,
  })

  const { data: topicDetail } = useQuery({
    queryKey: ['topic-detail', expandedTopicId],
    queryFn: () => getTopicDetail(selectedGroup!, expandedTopicId!),
    enabled: expandedTopicId !== null && selectedGroup !== null,
  })

  const handleTopicClick = (topic: Topic) => {
    if (expandedTopicId === topic.id) {
      setExpandedTopicId(null)
      setExpandedSliceId(null)
    } else {
      setExpandedTopicId(topic.id)
      setExpandedSliceId(null)
    }
  }

  const handleSliceClick = (slice: Slice) => {
    if (expandedSliceId === slice.id) {
      setExpandedSliceId(null)
    } else {
      setExpandedSliceId(slice.id)
    }
  }

  const handleAsk = async () => {
    if (!question.trim()) return
    setIsAsking(true)
    try {
      const result = await askQuestion(question, selectedGroup ?? undefined)
      setQaResult(result)
    } finally {
      setIsAsking(false)
    }
  }

  return (
    <div className="pb-20">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">话题时间线</h1>

      {/* Controls */}
      <div className="flex flex-wrap gap-3 mb-6 items-end">
        <div>
          <label className="block text-xs text-gray-500 mb-1">群组</label>
          <select
            className="border border-gray-300 rounded px-3 py-2 text-sm"
            value={selectedGroup ?? ''}
            onChange={(e) => {
              const v = e.target.value
              setSelectedGroup(v === '' ? null : Number(v))
              setExpandedTopicId(null)
              setExpandedSliceId(null)
            }}
          >
            <option value="">-- 选择群组 --</option>
            {groups?.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-gray-500 mb-1">开始日期</label>
          <input
            type="date"
            className="border border-gray-300 rounded px-3 py-2 text-sm"
            value={fromTs ? fromTs.slice(0, 10) : ''}
            onChange={(e) => setFromTs(e.target.value ? new Date(e.target.value).toISOString() : '')}
          />
        </div>

        <div>
          <label className="block text-xs text-gray-500 mb-1">结束日期</label>
          <input
            type="date"
            className="border border-gray-300 rounded px-3 py-2 text-sm"
            value={toTs ? toTs.slice(0, 10) : ''}
            onChange={(e) => setToTs(e.target.value ? new Date(e.target.value).toISOString() : '')}
          />
        </div>
      </div>

      {/* Topics List */}
      {selectedGroup === null && (
        <p className="text-gray-500">请先选择群组</p>
      )}

      {selectedGroup !== null && topicsLoading && (
        <p className="text-gray-500">加载中...</p>
      )}

      {selectedGroup !== null && topicsError && (
        <p className="text-red-500">加载失败</p>
      )}

      {topics && topics.length === 0 && (
        <p className="text-gray-500">暂无话题</p>
      )}

      {topics && topics.length > 0 && (
        <div className="space-y-3">
          {topics.map((topic) => {
            const isExpanded = expandedTopicId === topic.id
            const slices = isExpanded && topicDetail?.id === topic.id ? topicDetail.slices : null

            return (
              <div key={topic.id} className="border border-gray-200 rounded-lg overflow-hidden">
                {/* Topic header */}
                <div
                  className="bg-white p-4 cursor-pointer hover:bg-gray-50 transition-colors"
                  onClick={() => handleTopicClick(topic)}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-semibold text-gray-900 truncate">{topic.name || '(未命名话题)'}</span>
                        <span className="text-xs text-gray-400 shrink-0">{topic.slice_count} 个片段</span>
                      </div>
                      <div className="text-xs text-gray-400 mb-2">
                        {formatTs(topic.time_start)} — {formatTs(topic.time_end)}
                      </div>
                      <p className="text-sm text-gray-600 whitespace-pre-line line-clamp-2">
                        {summarySplit(topic.summary || '暂无摘要')}
                      </p>
                    </div>
                    <span className="text-gray-400 text-sm shrink-0">{isExpanded ? '▲' : '▼'}</span>
                  </div>
                </div>

                {/* Slices accordion */}
                {isExpanded && (
                  <div className="border-t border-gray-100 bg-gray-50">
                    {!slices && (
                      <p className="px-4 py-3 text-sm text-gray-500">加载中...</p>
                    )}
                    {slices && slices.length === 0 && (
                      <p className="px-4 py-3 text-sm text-gray-500">暂无片段</p>
                    )}
                    {slices && slices.map((slice) => {
                      const sliceExpanded = expandedSliceId === slice.id
                      return (
                        <div key={slice.id} className="border-t border-gray-100 first:border-t-0">
                          <div
                            className="px-4 py-3 cursor-pointer hover:bg-gray-100 transition-colors"
                            onClick={() => handleSliceClick(slice)}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <div className="flex-1 min-w-0">
                                <div className="text-xs text-gray-400 mb-1">
                                  {formatTs(slice.time_start)} — {formatTs(slice.time_end)}
                                </div>
                                <p className="text-sm text-gray-700 line-clamp-2">{slice.summary || '暂无摘要'}</p>
                                <span className="text-xs text-gray-400 mt-1 inline-block">
                                  {slice.messages?.length ?? 0} 条消息
                                </span>
                              </div>
                              <span className="text-gray-400 text-xs shrink-0">{sliceExpanded ? '▲' : '▼'}</span>
                            </div>
                          </div>

                          {/* Messages list */}
                          {sliceExpanded && slice.messages && (
                            <div className="bg-white border-t border-gray-100 divide-y divide-gray-50">
                              {slice.messages.map((msg) => (
                                <div key={msg.id} className="px-5 py-2">
                                  <div className="flex items-baseline gap-2 mb-0.5">
                                    <span className="text-xs font-medium text-blue-600">用户 {msg.sender_id}</span>
                                    <span className="text-xs text-gray-400">{formatTs(msg.ts)}</span>
                                  </div>
                                  <p className="text-sm text-gray-800">{msg.text}</p>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* QA result box */}
      {qaResult && (
        <div className="mt-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
          <p className="text-sm font-medium text-blue-800 mb-2">回答（{qaResult.sources.length} 个来源）</p>
          <p className="text-sm text-gray-800 whitespace-pre-wrap">{qaResult.answer}</p>
        </div>
      )}

      {/* RAG panel */}
      <div className="fixed bottom-0 left-48 right-0 bg-white border-t border-gray-200 p-3 flex gap-2">
        <input
          type="text"
          placeholder="问一个问题..."
          className="flex-1 border border-gray-300 rounded px-3 py-2 text-sm"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleAsk()}
        />
        <button
          onClick={handleAsk}
          disabled={!question.trim() || isAsking}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
        >
          {isAsking ? '...' : '提问'}
        </button>
      </div>
    </div>
  )
}
