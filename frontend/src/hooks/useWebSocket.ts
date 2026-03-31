import { useEffect, useRef, useState } from 'react'
import type { WsEvent } from '../types'

export function useWebSocket() {
  const [lastEvent, setLastEvent] = useState<WsEvent | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/realtime`)
      wsRef.current = ws

      ws.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data) as WsEvent
          if (event.event !== 'ping') {
            setLastEvent(event)
          }
        } catch {
          // ignore parse errors
        }
      }

      ws.onclose = () => {
        setTimeout(connect, 3000)
      }
    }

    connect()

    return () => {
      wsRef.current?.close()
    }
  }, [])

  return lastEvent
}
