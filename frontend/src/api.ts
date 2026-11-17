export const API = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(API + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  const v = await r.json();
  if (!r.ok) throw Error(typeof v.detail === 'string' ? v.detail : JSON.stringify(v.detail));
  return v;
}
