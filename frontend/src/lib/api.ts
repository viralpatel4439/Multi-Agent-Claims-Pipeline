import axios from 'axios'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api'

export const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
})

export async function fetchMembers() {
  const res = await api.get('/members')
  return res.data
}

export async function submitClaim(claimData: any) {
  const res = await api.post('/claims', claimData)
  return res.data
}

export async function fetchClaim(claimId: string) {
  const res = await api.get(`/claims/${claimId}`)
  return res.data
}

export async function fetchClaims() {
  const res = await api.get('/claims')
  return res.data
}
