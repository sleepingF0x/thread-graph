import type { Topic } from '../types'

interface Props {
  topic: Topic
  onClick?: () => void
}

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}

export default function TopicCard({ topic, onClick }: Props) {
  return (
    <div
      onClick={onClick}
      className="bg-white rounded-lg border border-gray-200 p-4 hover:border-blue-300 hover:shadow-sm transition-all cursor-pointer"
    >
      {topic.group_name && (
        <span className="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">
          {topic.group_name}
        </span>
      )}
      <h3 className="mt-2 text-base font-semibold text-gray-900 line-clamp-1">
        {topic.name || '(未命名话题)'}
      </h3>
      <p className="mt-1 text-sm text-gray-500 line-clamp-2">
        {topic.summary || '暂无摘要'}
      </p>
      <div className="mt-3 flex items-center justify-between text-xs text-gray-400">
        <span>{topic.slice_count} 个片段</span>
        {topic.time_end && <span>{timeAgo(topic.time_end)}</span>}
      </div>
    </div>
  )
}
