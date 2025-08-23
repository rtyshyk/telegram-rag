const API_BASE = import.meta.env.PUBLIC_API_URL || "";

async function fetchWithTimeout(
  url: string,
  options: RequestInit = {},
  timeoutMs = 10000,
) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("Request timeout");
    }
    throw error;
  }
}

export async function login(username: string, password: string) {
  const res = await fetchWithTimeout(
    `${API_BASE}/auth/login`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ username, password }),
    },
    10000,
  );
  if (!res.ok) throw res;
}

export async function logout() {
  const res = await fetchWithTimeout(
    `${API_BASE}/auth/logout`,
    {
      method: "POST",
      credentials: "include",
    },
    5000,
  );
  if (!res.ok) throw res;
}

export async function fetchModels() {
  const res = await fetchWithTimeout(
    `${API_BASE}/models`,
    {
      credentials: "include",
    },
    5000,
  );
  if (!res.ok) throw res;
  return res.json();
}
