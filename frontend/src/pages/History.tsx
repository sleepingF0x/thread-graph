import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { getSyncJobs, cancelSyncJob, triggerSync, getGroups } from '../api/groups'
import { useWebSocket } from '../hooks/useWebSocket'
import type { SyncJob } from '../types'

function formatDate(ts: string): string {
  return new Date(ts).toLocaleDateString('zh-CN')
}

function StatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    pending: 'bg-yellow-100 text-yellow-800',
    running: 'bg-blue-100 text-blue-800',
    done: 'bg-green-100 text-green-800',
    failed: 'bg-red-100 text-red-800',
  }
  const color = colorMap[status] ?? 'bg-gray-100 text-gray-800'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${color}`}>
      {status}
    </span>
  )
}

const chartData = Array.from({ length: 7 }, (_, i) => {
  const d = new Date()
  d.setDate(d.getDate() - (6 - i))
  return { date: `${d.getMonth() + 1}/${d.getDate()}`, count: 0 }
})

export default function History() {
  const queryClient = useQueryClient()
  const [selectedGroup, setSelectedGroup] = useState<number | null>(null)
  const [fromDays, setFromDays] = useState(30)
  const [triggerResult, setTriggerResult] = useState<{ sync_job_id: string } | null>(null)

  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ['sync-jobs'],
    queryFn: getSyncJobs,
    refetchInterval: 10000,
  })

  const { data: groups } = useQuery({
    queryKey: ['groups'],
    queryFn: getGroups,
  })

  const lastEvent = useWebSocket()
  useEffect(() => {
    if (lastEvent?.event === 'sync_progress') {
      queryClient.invalidateQueries({ queryKey: ['sync-jobs'] })
    }
  }, [lastEvent, queryClient])

  const handleCancel = async (jobId: string) => {
    await cancelSyncJob(jobId)
    queryClient.invalidateQueries({ queryKey: ['sync-jobs'] })
  }

  const handleTriggerSync = async () => {
    if (!selectedGroup) return
    const result = await triggerSync(selectedGroup, fromDays)
    setTriggerResult(result)
    queryClient.invalidateQueries({ queryKey: ['sync-jobs'] })
  }

  const canCancel = (job: SyncJob) =>
    job.status === 'pending' || job.status === 'running'

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">同步历史</h1>

      {/* Trigger sync form */}
      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">触发历史同步</h2>
        <div className="flex gap-3 items-end">
          <div>
            <label className="text-xs text-gray-500">群组</label>
            <select
              value={selectedGroup ?? ''}
              onChange={(e) => setSelectedGroup(e.target.value ? Number(e.target.value) : null)}
              className="block border rounded px-2 py-1 text-sm"
            >
              <option value="">选择群组</option>
              {groups?.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500">拉取天数</label>
            <input
              type="number"
              min={1}
              max={365}
              value={fromDays}
              onChange={(e) => setFromDays(Number(e.target.value))}
              className="block border rounded px-2 py-1 text-sm w-20"
            />
          </div>
          <button
            onClick={handleTriggerSync}
            disabled={!selectedGroup}
            className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
          >
            同步
          </button>
        </div>
        {triggerResult && (
          <p className="mt-2 text-xs text-green-600">
            已创建任务 {triggerResult.sync_job_id}
          </p>
        )}
      </div>

      {/* Sync jobs table */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-700">同步任务列表</h2>
        </div>
        {isLoading ? (
          <p className="px-4 py-6 text-sm text-gray-500">加载中...</p>
        ) : jobs.length === 0 ? (
          <p className="px-4 py-6 text-sm text-gray-500">暂无同步任务</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-100">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    群组 ID
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    状态
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    开始日期
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    结束日期
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    检查点消息 ID
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-100">
                {jobs.map((job) => (
                  <tr key={job.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-900">{job.group_id}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={job.status} />
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">{formatDate(job.from_ts)}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{formatDate(job.to_ts)}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {job.checkpoint_message_id ?? '-'}
                    </td>
                    <td className="px-4 py-3">
                      {canCancel(job) && (
                        <button
                          onClick={() => handleCancel(job.id)}
                          className="text-xs text-red-600 hover:text-red-800 font-medium"
                        >
                          取消
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Activity chart */}
      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">近 7 天话题活动</h2>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={chartData}>
            <XAxis dataKey="date" tick={{ fontSize: 12 }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
            <Tooltip />
            <Bar dataKey="count" fill="#3b82f6" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
