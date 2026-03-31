import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useWebSocket } from '../hooks/useWebSocket'
import { getActiveTopics } from '../api/topics'
import TopicCard from '../components/TopicCard'

export default function Home() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const lastEvent = useWebSocket()

  const { data: topics, isLoading, isError } = useQuery({
    queryKey: ['topics', 'active'],
    queryFn: () => getActiveTopics(),
  })

  useEffect(() => {
    if (lastEvent?.event === 'topic_updated') {
      queryClient.invalidateQueries({ queryKey: ['topics', 'active'] })
    }
  }, [lastEvent, queryClient])

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">正在讨论</h1>

      {isLoading && (
        <p className="text-gray-500">加载中...</p>
      )}

      {isError && (
        <p className="text-red-500">加载失败</p>
      )}

      {!isLoading && !isError && topics && topics.length === 0 && (
        <p className="text-gray-500">暂无活跃话题</p>
      )}

      {topics && topics.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {topics.map((topic) => (
            <TopicCard
              key={topic.id}
              topic={topic}
              onClick={() => navigate(`/topics?group=${topic.group_id}&topic=${topic.id}`)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
