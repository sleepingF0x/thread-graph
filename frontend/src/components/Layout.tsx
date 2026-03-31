import { NavLink, Outlet } from 'react-router-dom'
import { Home, MessageSquare, Clock, BookOpen, Settings } from 'lucide-react'

const navItems = [
  { to: '/', label: '总览', icon: Home, end: true },
  { to: '/topics', label: '话题', icon: MessageSquare, end: false },
  { to: '/history', label: '历史', icon: Clock, end: false },
  { to: '/glossary', label: '术语库', icon: BookOpen, end: false },
  { to: '/settings', label: '设置', icon: Settings, end: false },
]

export default function Layout() {
  return (
    <div className="flex h-screen bg-gray-50">
      <aside className="w-48 bg-white border-r border-gray-200 flex flex-col py-4">
        <div className="px-4 mb-6">
          <h1 className="text-lg font-bold text-gray-900">Thread Graph</h1>
        </div>
        <nav className="flex-1 space-y-1 px-2">
          {navItems.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-gray-600 hover:bg-gray-100'
                }`
              }
            >
              <Icon className="w-4 h-4" />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  )
}
