// Use only explicitly provided PUBLIC_API_URL; fail fast if undefined in runtime usage paths.
/// <reference path="../env.d.ts" />

const API_BASE_RAW = import.meta.env.PUBLIC_API_URL;
const API_BASE: string = API_BASE_RAW ? API_BASE_RAW.replace(/\/$/, "") : "";

export const DEFAULT_SEARCH_LIMIT = 5;

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
  const res = await fetch(`${API_BASE}/models`, {
    credentials: "include",
  });
  if (!res.ok) throw res;
  return res.json();
}

export interface ChatInfo {
  chat_id: string;
  source_title?: string;
  chat_type?: string;
  message_count: number;
}

export async function fetchChats(): Promise<ChatInfo[]> {
  const res = await fetch(`${API_BASE}/chats`, {
    credentials: "include",
  });
  if (res.status === 401) {
    window.location.href = "/login";
    return [];
  }
  if (!res.ok) throw res;
  const data = await res.json();
  return data.ok ? data.chats : [];
}

export interface SearchSpan {
  start_id: number;
  end_id: number;
  start_ts?: number;
  end_ts?: number;
}

export interface SearchResult {
  id: string;
  text: string;
  chat_id: string;
  message_id: number;
  chunk_idx: number;
  score: number;
  seed_score: number;
  span: SearchSpan;
  message_count: number;
  sender?: string;
  sender_username?: string;
  chat_username?: string;
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
    expansionLevel?: number;
  } = {},
): Promise<SearchResult[]> {
  const payload: any = { q, limit: opts.limit ?? DEFAULT_SEARCH_LIMIT };
  if (opts.chatId) payload.chat_id = opts.chatId;
  if (typeof opts.threadId === "number") payload.thread_id = opts.threadId;
  if (typeof opts.hybrid === "boolean") payload.hybrid = opts.hybrid;
  if (typeof opts.expansionLevel === "number")
    payload.expansion_level = opts.expansionLevel;
  const res = await fetch(`${API_BASE}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  });
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

export interface ChatFilters {
  chat_ids?: string[];
  date_from?: string;
  date_to?: string;
  thread_id?: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatCitation {
  id: string;
  chat_id: string;
  message_id: number;
  chunk_idx: number;
  source_title?: string;
  message_date?: number;
  chat_username?: string;
  thread_id?: number;
  chat_type?: string;
  sender?: string;
  sender_username?: string;
}

export interface ChatUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd?: number;
}

export interface ChatStreamChunk {
  type:
    | "search"
    | "reformulate"
    | "start"
    | "content"
    | "citations"
    | "usage"
    | "end"
    | "error";
  content?: string;
  citations?: ChatCitation[];
  usage?: ChatUsage;
  timing_seconds?: number;
  search_results_count?: number;
  reformulated_query?: string;
}

export async function* chatStream(
  q: string,
  opts: {
    k?: number;
    model_id?: string;
    filters?: ChatFilters;
    use_current_filters?: boolean;
    history?: ChatMessage[];
  } = {},
): AsyncGenerator<ChatStreamChunk, void, unknown> {
  const payload: any = {
    q,
    k: opts.k ?? DEFAULT_SEARCH_LIMIT,
    model_id: opts.model_id,
    filters: opts.filters,
    use_current_filters: opts.use_current_filters ?? true,
    history: opts.history,
  };

  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  });

  if (res.status === 401) {
    const canRedirect =
      typeof window !== "undefined" &&
      typeof window.location !== "undefined" &&
      import.meta.env.MODE !== "test";

    if (canRedirect) {
      try {
        window.location.href = "/login";
      } catch (err) {
        if (
          !(err instanceof Error) ||
          !err.message.includes("Not implemented: navigation")
        ) {
          throw err;
        }
      }
    }
    throw new Error("Unauthorized");
  }

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Chat failed: ${res.status} ${errorText}`);
  }

  if (!res.body) {
    throw new Error("No response body");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value);
      const lines = chunk.split("\n");

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6));
            yield data as ChatStreamChunk;
          } catch (e) {
            console.warn("Failed to parse SSE data:", line);
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
