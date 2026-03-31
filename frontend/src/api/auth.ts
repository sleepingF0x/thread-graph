import client from './client'
import type { AuthStatus } from '../types'

export const getAuthStatus = () =>
  client.get<AuthStatus>('/auth/status').then((r) => r.data)

export const sendLoginCode = (phone: string) =>
  client.post('/auth/login', { phone }).then((r) => r.data)

export const verifyCode = (code: string, password?: string) =>
  client.post('/auth/verify', { code, password }).then((r) => r.data)
