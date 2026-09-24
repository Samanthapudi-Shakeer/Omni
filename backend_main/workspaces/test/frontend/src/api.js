const TOKEN_KEY = 'aider_token';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || '';
}

function authHeaders(extra = {}) {
  const token = getToken();
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

export async function apiGet(path) {
  const res = await fetch(path, { headers: authHeaders() });
  return handle(res);
}

export async function apiPost(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return handle(res);
}

export async function apiUpload(path, formData) {
  const res = await fetch(path, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });
  return handle(res);
}

async function handle(res) {
  let body = null;
  try {
    body = await res.json();
  } catch (_) {
    /* no json body */
  }
  if (!res.ok) {
    const message = (body && (body.detail || body.error)) || `Request failed (${res.status})`;
    throw new Error(message);
  }
  return body;
}
