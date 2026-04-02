import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getAuthStatus, getTelegramDialogs, sendLoginCode, verifyCode } from '../api/auth'
import { getApiErrorMessage } from '../api/client'
import { getGroups, addGroup, removeGroup } from '../api/groups'

export default function Settings() {
  const queryClient = useQueryClient()

  // --- Auth ---
  const { data: authStatus, refetch: refetchAuth } = useQuery({
    queryKey: ['auth-status'],
    queryFn: getAuthStatus,
  })

  const [showLoginForm, setShowLoginForm] = useState(false)
  const [phone, setPhone] = useState('')
  const [codeSent, setCodeSent] = useState(false)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [loginError, setLoginError] = useState('')
  const [dialogSearch, setDialogSearch] = useState('')

  const authConfigMessage =
    authStatus?.configured === false
      ? '请先在项目根目录 .env 中配置 TELEGRAM_API_ID 和 TELEGRAM_API_HASH，然后重启 backend 容器。'
      : ''

  const handleSendCode = async () => {
    setLoginError('')
    try {
      await sendLoginCode(phone)
      setCodeSent(true)
    } catch (error) {
      const message = getApiErrorMessage(error, '发送验证码失败')
      setLoginError(
        message.includes('Telegram API credentials are not configured')
          ? authConfigMessage || message
          : message
      )
    }
  }

  const handleVerify = async () => {
    setLoginError('')
    try {
      await verifyCode(code, password || undefined)
      setCodeSent(false)
      setShowLoginForm(false)
      setPhone('')
      setCode('')
      setPassword('')
      refetchAuth()
    } catch (error) {
      const message = getApiErrorMessage(error, '验证失败')
      setLoginError(
        message.includes('Telegram API credentials are not configured')
          ? authConfigMessage || message
          : message
      )
    }
  }

  const {
    data: telegramDialogs = [],
    error: dialogsError,
    isLoading: dialogsLoading,
    refetch: refetchDialogs,
  } = useQuery({
    queryKey: ['telegram-dialogs'],
    queryFn: getTelegramDialogs,
    enabled: authStatus?.authorized === true && authStatus?.configured === true,
  })

  // --- Groups ---
  const { data: groups = [] } = useQuery({
    queryKey: ['groups'],
    queryFn: getGroups,
  })

  const handleRemoveGroup = async (id: number) => {
    if (!confirm(`确认停止监听群组 ${id}？`)) return
    await removeGroup(id)
    queryClient.invalidateQueries({ queryKey: ['groups'] })
  }

  const [newGroupId, setNewGroupId] = useState('')
  const [newGroupName, setNewGroupName] = useState('')
  const [newGroupType, setNewGroupType] = useState('group')
  const [addResult, setAddResult] = useState('')

  const normalizedDialogSearch = dialogSearch.trim().toLowerCase()
  const filteredDialogs = telegramDialogs
    .filter((dialog) => {
      if (!normalizedDialogSearch) return true

      const haystacks = [
        dialog.name ?? '',
        dialog.username ?? '',
        String(dialog.raw_id ?? ''),
        String(dialog.dialog_id),
      ]

      return haystacks.some((value) => value.toLowerCase().includes(normalizedDialogSearch))
    })
    .sort((a, b) => {
      if (a.is_group_like !== b.is_group_like) {
        return a.is_group_like ? -1 : 1
      }
      return (a.name ?? '').localeCompare(b.name ?? '', 'zh-CN')
    })

  const handleSelectDialog = (dialog: {
    raw_id: number | null
    name: string | null
    type: string
  }) => {
    if (dialog.raw_id === null) return

    setNewGroupId(String(dialog.raw_id))
    setNewGroupName(dialog.name ?? '')
    setNewGroupType(
      dialog.type === 'channel' || dialog.type === 'supergroup' || dialog.type === 'group'
        ? dialog.type
        : 'group'
    )
    setAddResult('已将该会话信息填入下方表单')
  }

  const handleAddGroup = async () => {
    if (!newGroupId || !newGroupName) return
    try {
      const result = await addGroup(Number(newGroupId), newGroupName, newGroupType)
      setAddResult(`已添加，同步任务 ${result.sync_job_id}`)
      setNewGroupId('')
      setNewGroupName('')
      queryClient.invalidateQueries({ queryKey: ['groups'] })
    } catch {
      setAddResult('添加失败，请检查群组 ID')
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-xl font-bold text-gray-900">设置</h1>

      {/* Section 1: Telegram 连接 */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Telegram 连接</h2>

        {authStatus?.configured === false ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 space-y-2">
            <p className="text-sm text-amber-900 font-medium">Telegram API 尚未配置</p>
            <p className="text-sm text-amber-800">
              请先在项目根目录 <code className="bg-amber-100 px-1 rounded">.env</code> 中填写
              <code className="bg-amber-100 px-1 rounded ml-1">TELEGRAM_API_ID</code>
              和
              <code className="bg-amber-100 px-1 rounded ml-1">TELEGRAM_API_HASH</code>
              ，然后重启 backend 容器。
            </p>
            {authStatus.detail && (
              <p className="text-xs text-amber-700 break-all">{authStatus.detail}</p>
            )}
          </div>
        ) : authStatus?.authorized && !showLoginForm ? (
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green-500"></span>
            <span className="text-sm text-gray-700">已连接</span>
            <button
              onClick={() => setShowLoginForm(true)}
              className="text-xs text-gray-400 hover:text-gray-600 ml-2"
            >
              重新登录
            </button>
          </div>
        ) : (
          <div className="space-y-3 max-w-sm">
            {!codeSent ? (
              <>
                <div>
                  <label className="text-xs text-gray-500">手机号码</label>
                  <input
                    type="tel"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    placeholder="+8613800000000"
                    className="block w-full border rounded px-3 py-2 text-sm mt-1"
                  />
                </div>
                <button
                  onClick={handleSendCode}
                  disabled={!phone.trim()}
                  className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
                >
                  发送验证码
                </button>
              </>
            ) : (
              <>
                <div>
                  <label className="text-xs text-gray-500">验证码</label>
                  <input
                    type="text"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    className="block w-full border rounded px-3 py-2 text-sm mt-1"
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-500">两步验证密码（可选）</label>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="block w-full border rounded px-3 py-2 text-sm mt-1"
                  />
                </div>
                <button
                  onClick={handleVerify}
                  disabled={!code.trim()}
                  className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
                >
                  验证
                </button>
              </>
            )}
            {loginError && <p className="text-xs text-red-500">{loginError}</p>}
          </div>
        )}
      </section>

      {/* Section 2: 群组管理 */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">群组管理</h2>

        {authStatus?.authorized && (
          <div className="mb-5 rounded-lg border border-gray-200 bg-gray-50 p-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-gray-800">查找 Telegram 会话</h3>
                <p className="text-xs text-gray-500 mt-1">
                  可按名称、用户名或 ID 搜索。点击结果会自动填入下方表单。
                </p>
              </div>
              <button
                onClick={() => refetchDialogs()}
                className="px-3 py-1.5 text-xs border border-gray-300 rounded text-gray-600 hover:bg-white"
              >
                刷新列表
              </button>
            </div>

            <input
              value={dialogSearch}
              onChange={(e) => setDialogSearch(e.target.value)}
              placeholder="搜索群名、@username 或 ID"
              className="block w-full border rounded px-3 py-2 text-sm bg-white"
            />

            {dialogsLoading ? (
              <p className="text-sm text-gray-500">正在加载 Telegram 会话…</p>
            ) : dialogsError ? (
              <div className="space-y-2">
                <p className="text-sm text-red-500">
                  {getApiErrorMessage(dialogsError, '加载 Telegram 会话失败')}
                </p>
                <p className="text-xs text-gray-500">你仍然可以手动填写下方群组 ID。</p>
              </div>
            ) : filteredDialogs.length > 0 ? (
              <div className="max-h-80 overflow-y-auto rounded border border-gray-200 bg-white">
                {filteredDialogs.map((dialog) => (
                  <div
                    key={`${dialog.dialog_id}-${dialog.raw_id ?? 'na'}`}
                    className="flex items-start justify-between gap-3 border-b border-gray-100 px-3 py-3 last:border-0"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-800 break-words">
                        {dialog.name || '(未命名会话)'}
                      </p>
                      <div className="mt-1 flex flex-wrap gap-2 text-xs text-gray-500">
                        <span>类型: {dialog.type}</span>
                        {dialog.username && <span>@{dialog.username}</span>}
                        <span>raw_id: {dialog.raw_id ?? '不可用'}</span>
                        <span>dialog_id: {dialog.dialog_id}</span>
                      </div>
                    </div>
                    <button
                      onClick={() => handleSelectDialog(dialog)}
                      disabled={dialog.raw_id === null}
                      className="shrink-0 px-3 py-1.5 rounded text-xs border border-blue-300 text-blue-600 hover:bg-blue-50 disabled:opacity-50 disabled:hover:bg-transparent"
                    >
                      选择
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-500">没有匹配的会话。</p>
            )}
          </div>
        )}

        {groups.length > 0 ? (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-gray-100">
                <th className="pb-2 font-medium">名称</th>
                <th className="pb-2 font-medium">类型</th>
                <th className="pb-2 font-medium">上次同步</th>
                <th className="pb-2"></th>
              </tr>
            </thead>
            <tbody>
              {groups.map((group) => (
                <tr key={group.id} className="border-b border-gray-50 last:border-0">
                  <td className="py-2 text-gray-800">{group.name}</td>
                  <td className="py-2 text-gray-500">{group.type}</td>
                  <td className="py-2 text-gray-500">
                    {group.last_synced_at
                      ? new Date(group.last_synced_at).toLocaleString('zh-CN')
                      : '-'}
                  </td>
                  <td className="py-2 text-right">
                    <button
                      onClick={() => handleRemoveGroup(group.id)}
                      className="text-xs text-red-500 hover:text-red-700"
                    >
                      移除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-gray-400 mb-3">暂无群组</p>
        )}

        {/* Add group form */}
        <div className="grid grid-cols-4 gap-2 items-end mt-3">
          <div>
            <label className="text-xs text-gray-500">群组 ID</label>
            <input
              type="number"
              value={newGroupId}
              onChange={(e) => setNewGroupId(e.target.value)}
              className="block w-full border rounded px-2 py-1 text-sm mt-1"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500">名称</label>
            <input
              value={newGroupName}
              onChange={(e) => setNewGroupName(e.target.value)}
              className="block w-full border rounded px-2 py-1 text-sm mt-1"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500">类型</label>
            <select
              value={newGroupType}
              onChange={(e) => setNewGroupType(e.target.value)}
              className="block w-full border rounded px-2 py-1 text-sm mt-1"
            >
              <option value="group">group</option>
              <option value="channel">channel</option>
              <option value="supergroup">supergroup</option>
            </select>
          </div>
          <button
            onClick={handleAddGroup}
            disabled={!newGroupId || !newGroupName}
            className="px-3 py-1.5 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
          >
            添加
          </button>
        </div>
        {addResult && <p className="mt-2 text-xs text-green-600">{addResult}</p>}
      </section>

      {/* Section 3: 系统配置 */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">系统配置</h2>
        <div className="space-y-2 text-sm text-gray-600">
          <p>
            Embedding 和 Qdrant 配置通过{' '}
            <code className="bg-gray-100 px-1 rounded">.env</code> 文件管理。
          </p>
          <p>修改配置后重启 backend 容器生效。</p>
          <div className="mt-3 pt-3 border-t border-gray-100">
            <button
              onClick={() =>
                alert('功能暂未开放：请手动删除 Qdrant slices collection 后重启以重建。')
              }
              className="px-3 py-1.5 border border-red-300 text-red-600 rounded text-sm hover:bg-red-50"
            >
              重建 Qdrant Collection
            </button>
            <p className="mt-1 text-xs text-gray-400">
              警告：这将删除所有向量索引，切片需要重新处理。
            </p>
          </div>
        </div>
      </section>
    </div>
  )
}
