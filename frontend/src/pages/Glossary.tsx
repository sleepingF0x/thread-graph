import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getTerms, createTerm, patchTerm } from '../api/terms'
import { getGroups } from '../api/groups'
import type { Term } from '../types'

function StatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    auto: 'bg-gray-100 text-gray-700',
    confirmed: 'bg-green-100 text-green-800',
    rejected: 'bg-red-100 text-red-800',
  }
  const labelMap: Record<string, string> = {
    auto: '自动识别',
    confirmed: '已确认',
    rejected: '已拒绝',
  }
  const color = colorMap[status] ?? 'bg-gray-100 text-gray-700'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${color}`}>
      {labelMap[status] ?? status}
    </span>
  )
}

function TermCard({
  term,
  onConfirm,
  onReject,
}: {
  term: Term
  onConfirm: (id: string) => void
  onReject: (id: string) => void
}) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div
      className={`bg-white rounded-lg border p-4 ${
        term.needs_review ? 'border-l-4 border-l-yellow-400 border-gray-200' : 'border-gray-200'
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className="text-lg font-bold text-gray-900">{term.word}</span>
            {term.needs_review && (
              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800">
                待审核
              </span>
            )}
            <StatusBadge status={term.status} />
          </div>

          {/* Variants */}
          {term.variants.length > 0 && (
            <div className="flex flex-wrap gap-1 mb-2">
              {term.variants.map((v) => (
                <span
                  key={v}
                  className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-blue-50 text-blue-700"
                >
                  {v}
                </span>
              ))}
            </div>
          )}

          {/* Meanings */}
          {term.meanings.length > 0 && (
            <ul className="text-sm text-gray-700 mb-2 space-y-0.5">
              {term.meanings.map((m, i) => (
                <li key={i} className="flex items-baseline gap-1">
                  <span className="text-gray-400 text-xs shrink-0">
                    {Math.round(m.confidence * 100)}%
                  </span>
                  <span>{m.meaning}</span>
                </li>
              ))}
            </ul>
          )}

          {/* Examples (collapsible) */}
          {term.examples.length > 0 && (
            <div className="text-sm text-gray-500">
              <p className="italic">"{term.examples[0]}"</p>
              {term.examples.length > 1 && !expanded && (
                <button
                  onClick={() => setExpanded(true)}
                  className="text-xs text-blue-600 mt-1 hover:underline"
                >
                  更多 ({term.examples.length - 1})
                </button>
              )}
              {expanded &&
                term.examples.slice(1).map((ex, i) => (
                  <p key={i} className="italic mt-1">
                    "{ex}"
                  </p>
                ))}
              {expanded && term.examples.length > 1 && (
                <button
                  onClick={() => setExpanded(false)}
                  className="text-xs text-blue-600 mt-1 hover:underline"
                >
                  收起
                </button>
              )}
            </div>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex flex-col gap-1 shrink-0">
          {term.status !== 'confirmed' && (
            <button
              onClick={() => onConfirm(term.id)}
              className="px-3 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700"
            >
              确认
            </button>
          )}
          {term.status !== 'rejected' && (
            <button
              onClick={() => onReject(term.id)}
              className="px-3 py-1 text-xs bg-red-50 text-red-700 border border-red-200 rounded hover:bg-red-100"
            >
              拒绝
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default function Glossary() {
  const [status, setStatus] = useState<'all' | 'auto' | 'confirmed' | 'rejected'>('all')
  const [needsReview, setNeedsReview] = useState(false)
  const [selectedGroup, setSelectedGroup] = useState<number | undefined>(undefined)
  const [showAddForm, setShowAddForm] = useState(false)
  const [newWord, setNewWord] = useState('')
  const [newVariants, setNewVariants] = useState('')

  const { data: groups } = useQuery({
    queryKey: ['groups'],
    queryFn: getGroups,
  })

  const {
    data: terms = [],
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ['terms', status, needsReview, selectedGroup],
    queryFn: () =>
      getTerms({
        status,
        needs_review: needsReview || undefined,
        group_id: selectedGroup,
        limit: 50,
      }),
  })

  const handleConfirm = async (id: string) => {
    await patchTerm(id, { status: 'confirmed', needs_review: false })
    refetch()
  }

  const handleReject = async (id: string) => {
    await patchTerm(id, { status: 'rejected' })
    refetch()
  }

  const handleAdd = async () => {
    if (!newWord.trim()) return
    await createTerm({
      word: newWord.trim(),
      variants: newVariants
        ? newVariants
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean)
        : undefined,
    })
    setNewWord('')
    setNewVariants('')
    setShowAddForm(false)
    refetch()
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">术语库</h1>
        <button
          onClick={() => setShowAddForm((v) => !v)}
          className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
        >
          ＋ 添加术语
        </button>
      </div>

      {/* Add term form */}
      {showAddForm && (
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">添加新术语</h2>
          <div className="flex gap-3 items-end flex-wrap">
            <div>
              <label className="text-xs text-gray-500 block mb-1">词汇</label>
              <input
                type="text"
                value={newWord}
                onChange={(e) => setNewWord(e.target.value)}
                placeholder="输入术语"
                className="border rounded px-2 py-1 text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">变体（逗号分隔）</label>
              <input
                type="text"
                value={newVariants}
                onChange={(e) => setNewVariants(e.target.value)}
                placeholder="变体1, 变体2"
                className="border rounded px-2 py-1 text-sm w-48"
              />
            </div>
            <button
              onClick={handleAdd}
              disabled={!newWord.trim()}
              className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
            >
              添加
            </button>
            <button
              onClick={() => setShowAddForm(false)}
              className="px-4 py-1.5 text-sm text-gray-500 hover:text-gray-700"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* Filter bar */}
      <div className="flex gap-3 items-center flex-wrap mb-4">
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value as typeof status)}
          className="border rounded px-2 py-1 text-sm"
        >
          <option value="all">全部状态</option>
          <option value="auto">自动识别</option>
          <option value="confirmed">已确认</option>
          <option value="rejected">已拒绝</option>
        </select>
        <label className="flex items-center gap-1 text-sm text-gray-600">
          <input
            type="checkbox"
            checked={needsReview}
            onChange={(e) => setNeedsReview(e.target.checked)}
          />
          仅待审核
        </label>
        <select
          value={selectedGroup ?? ''}
          onChange={(e) =>
            setSelectedGroup(e.target.value ? Number(e.target.value) : undefined)
          }
          className="border rounded px-2 py-1 text-sm"
        >
          <option value="">全部群组</option>
          {groups?.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
        <span className="text-xs text-gray-400">{isLoading ? '加载中...' : `${terms.length} 条`}</span>
      </div>

      {/* Term cards */}
      {!isLoading && terms.length === 0 && (
        <p className="text-sm text-gray-500 py-6 text-center">暂无术语</p>
      )}

      <div className="space-y-3">
        {terms.map((term) => (
          <TermCard
            key={term.id}
            term={term}
            onConfirm={handleConfirm}
            onReject={handleReject}
          />
        ))}
      </div>
    </div>
  )
}
