const API_BASE = import.meta.env.PUBLIC_API_URL || "";

export async function login(username: string, password: string) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw res;
}

export async function logout() {
  const res = await fetch(`${API_BASE}/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) throw res;
}

export async function fetchModels() {
  const res = await fetch(`${API_BASE}/models`, { credentials: "include" });
  if (!res.ok) throw res;
  return res.json();
}
