// Use only explicitly provided PUBLIC_API_URL; fail fast if undefined in runtime usage paths.
const API_BASE_RAW = import.meta.env.PUBLIC_API_URL;
const API_BASE: string = API_BASE_RAW ? API_BASE_RAW.replace(/\/$/, "") : "";

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

export interface SearchResult {
  id: string;
  text: string;
  chat_id: string;
  message_id: number;
  chunk_idx: number;
  score: number;
  sender?: string;
  sender_username?: string;
  message_date?: number;
  source_title?: string;
  chat_type?: string;
  edit_date?: number;
  thread_id?: number;
  has_link?: boolean;
}

export async function search(
  q: string,
  opts: {
    limit?: number;
    chatId?: string;
    threadId?: number;
    hybrid?: boolean;
  } = {},
): Promise<SearchResult[]> {
  const payload: any = { q, limit: opts.limit ?? 8 };
  if (opts.chatId) payload.chat_id = opts.chatId;
  if (typeof opts.threadId === "number") payload.thread_id = opts.threadId;
  if (typeof opts.hybrid === "boolean") payload.hybrid = opts.hybrid;
  const res = await fetchWithTimeout(
    `${API_BASE}/search`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(payload),
    },
    15000,
  );
  if (res.status === 401) {
    // Redirect to login if unauthorized
    window.location.href = "/login";
    return [];
  }
  if (!res.ok) throw res;
  const data = await res.json();
  if (!data.ok) return [];
  return data.results as SearchResult[];
}
