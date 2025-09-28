import React, { useState, useRef, useEffect } from "react";
import ModelPicker from "./ModelPicker";
import ChatSelector from "./ChatSelector";
import {
  logout,
  search,
  SearchResult,
  chatStream,
  ChatCitation,
  ChatUsage,
  DEFAULT_SEARCH_LIMIT,
} from "../lib/api";
import { formatTelegramLink } from "../lib/telegram_links";
import {
  formatDate,
  formatTime,
  getChatTypeLabel,
  formatCitationLink,
  formatCitationAuthor,
  getReferencedCitationIndices,
} from "../lib/chatFormatters";

const CONTEXT_LIMIT_STORAGE_KEY = "searchContextLimit";
const MIN_CONTEXT_LIMIT = 1;
const MAX_CONTEXT_LIMIT = 25;
const DEFAULT_CONTEXT_LIMIT = DEFAULT_SEARCH_LIMIT;

const clampContextLimit = (value: number): number => {
  const numeric = Number.isFinite(value) ? value : DEFAULT_CONTEXT_LIMIT;
  return Math.min(MAX_CONTEXT_LIMIT, Math.max(MIN_CONTEXT_LIMIT, numeric));
};

const readStoredContextLimit = (): number => {
  if (typeof window === "undefined") return DEFAULT_CONTEXT_LIMIT;
  try {
    const raw = window.localStorage.getItem(CONTEXT_LIMIT_STORAGE_KEY);
    if (!raw) return DEFAULT_CONTEXT_LIMIT;
    const parsed = Number.parseInt(raw, 10);
    if (Number.isNaN(parsed)) return DEFAULT_CONTEXT_LIMIT;
    return clampContextLimit(parsed);
  } catch {
    return DEFAULT_CONTEXT_LIMIT;
  }
};

type ConversationHistoryEntry = {
  role: "user" | "assistant";
  content: string;
};

interface Message {
  id: string;
  content: string;
  role: "user" | "assistant";
  timestamp: Date;
  citations?: ChatCitation[];
  usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    cost_usd?: number;
  };
  timing_seconds?: number;
  reformulated_query?: string;
}

export default function ProtectedApp() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [loadingPhase, setLoadingPhase] = useState<string>("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [showContext, setShowContext] = useState(true);
  const [currentSearchQuery, setCurrentSearchQuery] = useState<string>("");
  const [searchLimit, setSearchLimit] = useState<number>(() =>
    readStoredContextLimit(),
  );
  const [contextLimitDraft, setContextLimitDraft] = useState<string>(() =>
    String(readStoredContextLimit()),
  );
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [selectedChat, setSelectedChat] = useState<string>("");
  const [chatError, setChatError] = useState<string | null>(null);
  const [isHydrated, setIsHydrated] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const searchLimitRef = useRef(searchLimit);
  // Monotonic sequence to avoid race conditions between overlapping searches
  const searchSeqRef = useRef(0);

  useEffect(() => {
    searchLimitRef.current = searchLimit;
    setContextLimitDraft(String(searchLimit));
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(
        CONTEXT_LIMIT_STORAGE_KEY,
        String(searchLimit),
      );
    } catch {
      // ignore storage write errors
    }
  }, [searchLimit]);

  useEffect(() => {
    setIsHydrated(true);
  }, []);

  const scrollToBottom = () => {
    const el = messagesEndRef.current;
    if (el && typeof el.scrollIntoView === "function") {
      try {
        el.scrollIntoView({ behavior: "smooth" });
      } catch {
        // noop
      }
    }
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Aggregate multiple chunk results for the same (chat_id, message_id) into a single full message
  const aggregateSearchResults = (results: SearchResult[]): SearchResult[] => {
    if (!results || results.length === 0) return [];
    // Return a shallow copy so state updates remain isolated.
    return results.map((result) => ({ ...result }));
  };

  const handleLogout = async () => {
    try {
      await logout();
    } finally {
      window.location.href = "/login";
    }
  };

  const runSearch = async (
    q: string,
    opts: {
      preserveOnEmpty?: boolean;
      limitOverride?: number;
    } = {},
  ) => {
    const trimmed = q.trim();
    const limitSource =
      typeof opts.limitOverride === "number"
        ? opts.limitOverride
        : searchLimitRef.current || searchLimit;
    const targetLimit = clampContextLimit(limitSource);

    if (!trimmed) {
      if (!opts.preserveOnEmpty) {
        // User manually cleared input: clear panel
        setSearchResults([]);
        setCurrentSearchQuery("");
      }
      searchLimitRef.current = targetLimit;
      return;
    }

    searchLimitRef.current = targetLimit;

    const seq = ++searchSeqRef.current; // capture sequence id
    setSearchLoading(true);
    setSearchError(null);
    setCurrentSearchQuery(trimmed);
    try {
      const searchOpts: any = {
        limit: targetLimit,
        hybrid: true,
      };
      if (selectedChat) {
        searchOpts.chatId = selectedChat;
      }
      const results = await search(trimmed, searchOpts);
      // Ignore if a newer search started meanwhile
      if (seq !== searchSeqRef.current) return;
      const aggregated = aggregateSearchResults(results);
      setSearchResults(aggregated);
    } catch (err: any) {
      if (seq !== searchSeqRef.current) return; // stale
      setSearchError(err?.message || "Search failed");
    } finally {
      if (seq === searchSeqRef.current) setSearchLoading(false);
    }
  };

  const streamAssistantResponse = async ({
    prompt,
    history,
    assistantMessageId,
    modelId,
    chatId,
  }: {
    prompt: string;
    history: ConversationHistoryEntry[];
    assistantMessageId: string;
    modelId?: string;
    chatId?: string;
  }) => {
    setChatError(null);
    setIsLoading(true);

    let assistantAdded = false;
    let fullContent = "";
    let finalCitations: ChatCitation[] = [];
    let finalUsage: ChatUsage | undefined;
    let finalTiming: number | undefined;
    let reformulatedQuery = "";
    let loadingCleared = false;

    const chatOpts: any = {
      model_id: modelId,
      history,
    };

    chatOpts.k = Math.max(1, searchLimitRef.current);

    if (chatId) {
      chatOpts.filters = {
        chat_ids: [chatId],
      };
    }

    try {
      for await (const chunk of chatStream(prompt, chatOpts)) {
        if (chunk.type === "reformulate") {
          if (chunk.reformulated_query) {
            reformulatedQuery = chunk.reformulated_query;
          }
        } else if (chunk.type === "content") {
          if (chunk.content) {
            if (!loadingCleared) {
              setIsLoading(false);
              loadingCleared = true;
            }
            if (!assistantAdded) {
              assistantAdded = true;
              fullContent = chunk.content;
              setMessages((prev) => [
                ...prev,
                {
                  id: assistantMessageId,
                  role: "assistant",
                  content: fullContent,
                  timestamp: new Date(),
                },
              ]);
            } else {
              fullContent += chunk.content;
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === assistantMessageId
                    ? { ...msg, content: fullContent }
                    : msg,
                ),
              );
            }
          }
        } else if (chunk.type === "citations") {
          if (chunk.citations) finalCitations = chunk.citations;
          const qForPanel = reformulatedQuery.trim() || prompt;
          runSearch(qForPanel, { preserveOnEmpty: true });
        } else if (chunk.type === "end") {
          if (chunk.usage) finalUsage = chunk.usage;
          if (chunk.timing_seconds) finalTiming = chunk.timing_seconds;
          if (!assistantAdded) {
            assistantAdded = true;
            setMessages((prev) => [
              ...prev,
              {
                id: assistantMessageId,
                role: "assistant",
                content: fullContent,
                citations: finalCitations,
                usage: finalUsage,
                timing_seconds: finalTiming,
                reformulated_query: reformulatedQuery,
                timestamp: new Date(),
              },
            ]);
          } else {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMessageId
                  ? {
                      ...msg,
                      content: fullContent,
                      citations: finalCitations,
                      usage: finalUsage,
                      timing_seconds: finalTiming,
                      reformulated_query: reformulatedQuery,
                      timestamp: new Date(),
                    }
                  : msg,
              ),
            );
          }
          const qForPanel = reformulatedQuery.trim() || prompt;
          runSearch(qForPanel, { preserveOnEmpty: true });
        } else if (chunk.type === "error") {
          throw new Error(chunk.content || "Unknown streaming error");
        }
      }
    } catch (error: any) {
      const message = error?.message || "Chat request failed";
      setChatError(message);
      setMessages((prev) => {
        const exists = prev.some((m) => m.id === assistantMessageId);
        if (!exists) {
          return [
            ...prev,
            {
              id: assistantMessageId,
              role: "assistant",
              content: `Error: ${message}`,
              timestamp: new Date(),
            },
          ];
        }
        return prev.map((msg) =>
          msg.id === assistantMessageId
            ? {
                ...msg,
                content: `Error: ${message}`,
                citations: undefined,
                usage: undefined,
                timing_seconds: undefined,
                reformulated_query: undefined,
                timestamp: new Date(),
              }
            : msg,
        );
      });
    } finally {
      setIsLoading(false);
    }
  };

  const regenerateLastAssistantResponse = async () => {
    if (isLoading) return;
    if (messages.length === 0) return;

    const lastUserIndex = (() => {
      for (let i = messages.length - 1; i >= 0; i -= 1) {
        if (messages[i].role === "user") {
          return i;
        }
      }
      return -1;
    })();

    if (lastUserIndex === -1) return;

    const lastAssistantIndex = (() => {
      for (let i = messages.length - 1; i > lastUserIndex; i -= 1) {
        if (messages[i].role === "assistant") {
          return i;
        }
      }
      return -1;
    })();

    const prompt = messages[lastUserIndex]?.content.trim();
    if (!prompt) return;

    const historyEntries: ConversationHistoryEntry[] = messages
      .slice(0, lastUserIndex)
      .map((msg) => ({ role: msg.role, content: msg.content }));

    if (lastAssistantIndex !== -1) {
      const updatedMessages = [
        ...messages.slice(0, lastAssistantIndex),
        ...messages.slice(lastAssistantIndex + 1),
      ];
      setMessages(updatedMessages);
    }

    const assistantMessageId = `${Date.now()}-regen`;

    await streamAssistantResponse({
      prompt,
      history: historyEntries,
      assistantMessageId,
      modelId: selectedModel,
      chatId: selectedChat,
    });
  };

  const commitContextLimit = async (
    nextValue: number,
    { rerunSearch = true }: { rerunSearch?: boolean } = {},
  ) => {
    const clamped = clampContextLimit(nextValue);
    searchLimitRef.current = clamped;
    setContextLimitDraft(String(clamped));

    const limitChanged = clamped !== searchLimit;
    if (limitChanged) {
      setSearchLimit(clamped);
    }

    if (rerunSearch && limitChanged && currentSearchQuery.trim()) {
      await runSearch(currentSearchQuery, {
        preserveOnEmpty: true,
        limitOverride: clamped,
      });
      await regenerateLastAssistantResponse();
    }
  };

  const handleContextLimitBlur = () => {
    if (!contextLimitDraft.trim()) {
      setContextLimitDraft(String(searchLimit));
      return;
    }
    const parsed = Number.parseInt(contextLimitDraft, 10);
    if (Number.isNaN(parsed)) {
      setContextLimitDraft(String(searchLimit));
      return;
    }
    void commitContextLimit(parsed);
  };

  const handleContextLimitKeyDown = (
    event: React.KeyboardEvent<HTMLInputElement>,
  ) => {
    if (event.key === "Enter") {
      event.preventDefault();
      handleContextLimitBlur();
      return;
    } else if (event.key === "Escape") {
      event.preventDefault();
      setContextLimitDraft(String(searchLimit));
      return;
    }
  };

  const adjustContextLimit = (delta: number) => {
    void commitContextLimit(searchLimit + delta);
  };

  // Re-run the most recent query when the chat filter changes
  useEffect(() => {
    if (!currentSearchQuery.trim()) return;
    runSearch(currentSearchQuery, { preserveOnEmpty: true });
  }, [selectedChat]);

  const handleSend = async (message: string) => {
    if (!message.trim() || isLoading) return;

    setIsLoading(true);
    setChatError(null);

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: message,
      timestamp: new Date(),
    };
    const assistantMessageId = (Date.now() + 1).toString();

    setMessages((prev) => [...prev, userMessage]);

    try {
      await runSearch(message, {
        preserveOnEmpty: true,
      });
    } catch {
      // ignore search errors here; main chat flow continues
    }
    setInput("");

    const history = messages.map((msg) => ({
      role: msg.role,
      content: msg.content,
    }));

    await streamAssistantResponse({
      prompt: message,
      history,
      assistantMessageId,
      modelId: selectedModel,
      chatId: selectedChat,
    });
  };

  const renderMessageContent = (message: Message) => {
    const citations = message.citations ?? [];
    const referencedIndices = getReferencedCitationIndices(
      message.content,
      citations.length,
    );
    const referencedSet = new Set(referencedIndices);

    let content = message.content ?? "";

    if (citations.length > 0 && referencedSet.size > 0 && content) {
      referencedIndices.forEach((citationIndex) => {
        const citationNum = citationIndex + 1;
        const regex = new RegExp(`\\[${citationNum}\\]`, "g");
        content = content.replace(
          regex,
          `<span class="text-blue-600 cursor-pointer font-medium underline hover:bg-blue-50 px-1 py-0.5 rounded transition-colors citation-link" data-citation="${citationIndex}">[${citationNum}]</span>`,
        );
      });
    }

    return (
      <div>
        <div
          className="text-sm leading-relaxed whitespace-pre-wrap"
          dangerouslySetInnerHTML={{ __html: content }}
          onClick={(e) => {
            const target = e.target as HTMLElement;
            if (!target.classList.contains("citation-link")) return;

            const citationIndex = Number.parseInt(
              target.dataset.citation || "",
              10,
            );

            if (
              Number.isNaN(citationIndex) ||
              !referencedSet.has(citationIndex)
            ) {
              return;
            }

            const citation = citations[citationIndex];
            if (citation) {
              window.open(formatCitationLink(citation), "_blank");
            }
          }}
        />

        {citations.length > 0 && referencedIndices.length > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-200">
            <div className="text-xs text-gray-600 mb-2 font-medium">
              Sources:
            </div>
            <div className="space-y-1">
              {referencedIndices.map((citationIndex) => {
                const citation = citations[citationIndex];
                if (!citation) return null;
                const citationNumber = citationIndex + 1;
                return (
                  <div
                    key={`${citation.id}-${citationNumber}`}
                    className="text-xs text-gray-600"
                  >
                    <button
                      onClick={() =>
                        window.open(formatCitationLink(citation), "_blank")
                      }
                      className="hover:text-blue-600 hover:underline text-left"
                    >
                      [{citationNumber}]{" "}
                      {citation.source_title || `Chat ${citation.chat_id}`} —{" "}
                      {formatDate(citation.message_date)} —{" "}
                      {formatCitationAuthor(citation)}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Render usage stats if available */}
        {message.usage && (
          <div className="mt-2 pt-2 border-t border-gray-100">
            <div className="text-xs text-gray-500 flex items-center gap-4">
              <span>🧠 {message.usage.total_tokens} tokens</span>
              {message.usage.cost_usd && (
                <span>💰 ${message.usage.cost_usd.toFixed(6)}</span>
              )}
              {message.timing_seconds && (
                <span>⏱️ {message.timing_seconds}s</span>
              )}
            </div>
          </div>
        )}

        {/* Show reformulated query if available */}
        {message.reformulated_query && (
          <div className="mt-2 pt-2 border-t border-gray-100">
            <div className="text-xs text-gray-500">
              <span className="font-medium">Enhanced query:</span>{" "}
              <span className="italic">"{message.reformulated_query}"</span>
            </div>
          </div>
        )}
      </div>
    );
  };

  const limitLabel = `${searchLimit} snippet${searchLimit !== 1 ? "s" : ""}`;
  const canIncreaseLimit =
    searchLimit < MAX_CONTEXT_LIMIT && !searchLoading && !isLoading;
  const canDecreaseLimit =
    searchLimit > MIN_CONTEXT_LIMIT && !searchLoading && !isLoading;

  return (
    <div
      className="flex flex-col h-screen bg-gray-50"
      data-testid="chat-app"
      data-hydrated={isHydrated ? "true" : "false"}
    >
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold text-gray-800">RAG Chat</h1>
          <ModelPicker value={selectedModel} onModelChange={setSelectedModel} />
          <ChatSelector value={selectedChat} onChatChange={setSelectedChat} />
          {messages.length > 0 && (
            <button
              onClick={() => {
                setMessages([]);
              }}
              className="px-3 py-1.5 text-sm font-medium text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors border border-gray-300"
            >
              Clear Chat
            </button>
          )}
        </div>
        <button
          onClick={handleLogout}
          className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
        >
          Logout
        </button>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Main messages area */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-gray-500">
              <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mb-4">
                <svg
                  className="w-8 h-8 text-blue-600"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                  />
                </svg>
              </div>
              <p className="text-lg font-medium">Start a conversation</p>
              <p className="text-sm">Ask me anything about your documents</p>
            </div>
          ) : (
            messages.map((message) => (
              <div
                key={message.id}
                className={`flex ${
                  message.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                <div
                  className={`max-w-[70%] ${
                    message.role === "user" ? "order-2" : "order-1"
                  }`}
                >
                  <div
                    className={`px-4 py-3 rounded-2xl ${
                      message.role === "user"
                        ? "bg-blue-600 text-white"
                        : "bg-white border border-gray-200 text-gray-800"
                    }`}
                  >
                    {message.role === "user" ? (
                      <p className="text-sm leading-relaxed whitespace-pre-wrap">
                        {message.content}
                      </p>
                    ) : (
                      renderMessageContent(message)
                    )}
                  </div>
                  <div
                    className={`mt-1 px-2 ${
                      message.role === "user" ? "text-right" : "text-left"
                    }`}
                  >
                    <span className="text-xs text-gray-500">
                      {formatTime(message.timestamp)}
                    </span>
                  </div>
                </div>
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium ${
                    message.role === "user"
                      ? "bg-blue-600 text-white order-1 ml-3"
                      : "bg-gray-200 text-gray-600 order-2 mr-3"
                  }`}
                >
                  {message.role === "user" ? "U" : "AI"}
                </div>
              </div>
            ))
          )}

          {chatError && (
            <div className="mx-6 mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <div className="flex items-center gap-2 text-red-700">
                <svg
                  className="w-4 h-4"
                  fill="currentColor"
                  viewBox="0 0 20 20"
                >
                  <path
                    fillRule="evenodd"
                    d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z"
                    clipRule="evenodd"
                  />
                </svg>
                <span className="text-sm font-medium">
                  Chat Error: {chatError}
                </span>
                <button
                  onClick={() => setChatError(null)}
                  className="ml-auto text-red-500 hover:text-red-700"
                >
                  ×
                </button>
              </div>
            </div>
          )}

          {isLoading && (
            <div className="flex justify-start">
              <div className="max-w-[70%] order-1">
                <div className="px-4 py-3 rounded-2xl bg-white border border-gray-200">
                  <div className="flex items-center space-x-2">
                    <div className="flex space-x-1">
                      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                      <div
                        className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                        style={{ animationDelay: "0.1s" }}
                      ></div>
                      <div
                        className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                        style={{ animationDelay: "0.2s" }}
                      ></div>
                    </div>
                    <span className="text-sm text-gray-500">
                      {loadingPhase || "AI is thinking..."}
                    </span>
                  </div>
                </div>
              </div>
              <div className="w-8 h-8 rounded-full bg-gray-200 text-gray-600 flex items-center justify-center text-xs font-medium order-2 mr-3">
                AI
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Floating toggle button when context panel is hidden */}
        {!showContext && (
          <button
            onClick={() => setShowContext(true)}
            className="fixed top-20 right-4 z-10 bg-blue-600 hover:bg-blue-700 text-white p-3 rounded-full shadow-lg transition-colors"
            title="Show search results panel"
          >
            <svg
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
          </button>
        )}

        {/* Context / Search panel */}
        <div
          className={`w-96 border-l border-gray-200 flex flex-col bg-white ${
            showContext ? "" : "hidden"
          }`}
        >
          <div className="p-4 flex items-center justify-between border-b border-gray-100">
            <div>
              <h2 className="text-sm font-semibold text-gray-700">
                Search Results
              </h2>
              {searchResults.length > 0 && !searchLoading && (
                <p className="text-xs text-gray-500 mt-1">
                  Found {searchResults.length} context
                  {searchResults.length !== 1 ? "s" : ""}
                  {currentSearchQuery &&
                    ` for "${currentSearchQuery.substring(0, 30)}${
                      currentSearchQuery.length > 30 ? "..." : ""
                    }"`}
                </p>
              )}
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <span className="text-[11px] uppercase tracking-wide text-gray-500 font-medium">
                  Context limit
                </span>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min={MIN_CONTEXT_LIMIT}
                    max={MAX_CONTEXT_LIMIT}
                    step={1}
                    value={contextLimitDraft}
                    onChange={(event) =>
                      setContextLimitDraft(event.target.value)
                    }
                    onBlur={handleContextLimitBlur}
                    onKeyDown={handleContextLimitKeyDown}
                    className="w-16 px-2 py-1 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    aria-label="Context limit"
                  />
                  <div className="flex flex-col overflow-hidden rounded-md border border-gray-300">
                    <button
                      type="button"
                      onClick={() => adjustContextLimit(1)}
                      disabled={!canIncreaseLimit}
                      className="text-xs leading-none px-3 py-1 bg-white hover:bg-gray-100 disabled:opacity-40 disabled:hover:bg-white"
                      aria-label="Increase context limit"
                      title="Increase context limit"
                    >
                      +
                    </button>
                    <button
                      type="button"
                      onClick={() => adjustContextLimit(-1)}
                      disabled={!canDecreaseLimit}
                      className="text-xs leading-none px-3 py-1 bg-white hover:bg-gray-100 border-t border-gray-200 disabled:opacity-40 disabled:hover:bg-white"
                      aria-label="Decrease context limit"
                      title="Decrease context limit"
                    >
                      −
                    </button>
                  </div>
                </div>
                <span className="text-[11px] text-gray-500">
                  Shared across search and chat • {limitLabel}
                </span>
              </div>
            </div>
            <button
              onClick={() => setShowContext(!showContext)}
              className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
            >
              {showContext ? (
                <>
                  <svg
                    className="w-3 h-3"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M9 5l7 7-7 7"
                    />
                  </svg>
                  Hide
                </>
              ) : (
                <>
                  <svg
                    className="w-3 h-3"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M15 19l-7-7 7-7"
                    />
                  </svg>
                  Show
                </>
              )}
            </button>
          </div>
          <div className="p-3 overflow-y-auto space-y-3 text-sm flex-1">
            {searchLoading && (
              <div className="flex items-center gap-2 text-gray-500">
                <div className="w-4 h-4 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin" />
                <span>Searching…</span>
              </div>
            )}
            {searchError && !searchLoading && (
              <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded p-2 flex flex-col gap-2">
                <div>{searchError}</div>
                <button
                  onClick={() => {
                    const retryQuery = currentSearchQuery || input;
                    if (retryQuery.trim()) {
                      runSearch(retryQuery, { preserveOnEmpty: true });
                    }
                  }}
                  className="self-start px-2 py-1 text-[10px] font-medium bg-red-600 text-white rounded hover:bg-red-700"
                >
                  Retry
                </button>
              </div>
            )}
            {!searchLoading &&
              searchResults.length === 0 &&
              currentSearchQuery.trim() && (
                <div className="text-gray-400">No matches yet.</div>
              )}
            {!currentSearchQuery.trim() && searchResults.length === 0 && (
              <div className="text-gray-400">
                Send a message to surface relevant context here.
              </div>
            )}
            {searchResults.map((r) => (
              <div
                key={r.id}
                className="group border border-gray-200 rounded-lg p-3 hover:border-blue-400 hover:shadow-md transition-all duration-200"
              >
                {/* Header with metadata */}
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 text-xs text-gray-600 mb-1">
                      <span className="bg-blue-100 text-blue-700 px-2 py-1 rounded-full font-medium">
                        {getChatTypeLabel(r.chat_type)}
                      </span>
                      {r.source_title && (
                        <span className="font-medium text-gray-800 truncate">
                          {r.source_title}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-gray-500">
                      <span className="font-mono">
                        {r.chat_id}:{r.message_id}
                      </span>
                      {r.span && (
                        <span className="text-gray-600">
                          {`Range ${
                            r.span.start_id === r.span.end_id
                              ? r.span.start_id
                              : `${r.span.start_id}–${r.span.end_id}`
                          } • ${r.message_count} msg${
                            r.message_count !== 1 ? "s" : ""
                          }`}
                        </span>
                      )}
                      {r.sender && (
                        <span className="text-gray-600">
                          Sent by{" "}
                          {r.sender_username
                            ? `@${r.sender_username}`
                            : r.sender}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-1 text-right">
                    {typeof r.score === "number" && (
                      <span className="text-[10px] px-2 py-1 rounded-full bg-blue-50 text-blue-600 font-medium">
                        Rerank {r.score.toFixed(3)}
                      </span>
                    )}
                    {typeof r.seed_score === "number" && (
                      <span className="text-[10px] px-2 py-1 rounded-full bg-gray-100 text-gray-700">
                        Seed {r.seed_score.toFixed(3)}
                      </span>
                    )}
                    <button
                      onClick={() =>
                        window.open(
                          formatTelegramLink({
                            chatId: r.chat_id,
                            messageId: r.message_id,
                            sourceTitle: r.source_title,
                            chatType: r.chat_type,
                            chatUsername: r.chat_username,
                            threadId: r.thread_id,
                          }),
                          "_blank",
                        )
                      }
                      className="text-[10px] px-2 py-1 rounded bg-gray-100 hover:bg-blue-100 hover:text-blue-700 transition-colors flex items-center gap-1"
                      title={
                        r.source_title === "Saved Messages"
                          ? "Open Saved Messages"
                          : "Open in Telegram"
                      }
                    >
                      <svg
                        className="w-3 h-3"
                        viewBox="0 0 24 24"
                        fill="currentColor"
                      >
                        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06-.01.24-.02.38z" />
                      </svg>
                      {r.source_title === "Saved Messages" ? "Saved" : "Open"}
                    </button>
                  </div>
                </div>

                {/* Message content */}
                <div className="bg-gray-50 rounded-lg p-3 mb-2">
                  <p className="text-sm leading-relaxed text-gray-800 whitespace-pre-wrap">
                    {r.text}
                  </p>
                </div>

                {/* Footer with timestamps and additional info */}
                <div className="flex items-center justify-between text-xs text-gray-500">
                  <div className="flex items-center gap-3">
                    <span>📅 {formatDate(r.message_date)}</span>
                    {r.edit_date && (
                      <span className="text-orange-600">
                        ✏️ Edited {formatDate(r.edit_date)}
                      </span>
                    )}
                    {r.has_link && (
                      <span className="text-blue-600">🔗 Contains links</span>
                    )}
                  </div>
                  {r.chunk_idx > 0 && (
                    <span className="bg-gray-200 text-gray-700 px-2 py-1 rounded text-[10px]">
                      Chunk {r.chunk_idx + 1}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Input */}
      <div className="bg-white border-t border-gray-200 px-6 py-4">
        <div className="flex gap-3">
          <div className="flex-1">
            <textarea
              value={input}
              onChange={(e) => {
                const nextValue = e.target.value;
                setInput(nextValue);
                if (!nextValue.trim()) {
                  setSearchResults([]);
                  setCurrentSearchQuery("");
                }
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend(input);
                }
              }}
              placeholder="Type your message... (Enter to send, Shift+Enter for new line)"
              className="w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none h-[52px] leading-6"
              rows={1}
              disabled={isLoading}
              style={{ height: "52px", minHeight: "52px", maxHeight: "128px" }}
            />
          </div>
          <button
            type="button"
            onClick={() => handleSend(input)}
            disabled={!input.trim() || isLoading}
            className="w-[72px] h-[52px] bg-blue-600 text-white rounded-xl hover:bg-blue-700 focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1 flex-shrink-0"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
              />
            </svg>
            <span className="text-sm">Send</span>
          </button>
        </div>
      </div>
    </div>
  );
}
