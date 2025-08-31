import React, { useState, useRef, useEffect } from "react";
import ModelPicker from "./ModelPicker";
import {
  logout,
  search,
  SearchResult,
  chatStream,
  ChatCitation,
  ChatStreamChunk,
  ChatMessage,
  ChatUsage,
} from "../lib/api";

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

const formatDate = (timestamp?: number) => {
  if (!timestamp) return "Unknown date";
  return new Date(timestamp * 1000).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};
const formatTelegramLink = (
  chatId: string,
  messageId: number,
  sourceTitle?: string,
  chatType?: string,
) => {
  console.log("Formatting Telegram link:", {
    chatId,
    messageId,
    sourceTitle,
    chatType,
  });

  // For Saved Messages, try the standard web format first
  if (sourceTitle === "Saved Messages") {
    // For Saved Messages, we can try opening the direct message link
    // but it might not work in browser - fallback to opening Saved Messages
    const link = `https://web.telegram.org/k/#@me`;
    console.log("Saved Messages link:", link);
    return link;
  }

  // Handle different chat ID formats for Telegram message links
  // Based on the documentation: Message links section

  // For supergroups and channels (negative IDs starting with -100)
  if (chatId.startsWith("-100")) {
    // Remove the -100 prefix to get the channel ID
    const cleanChatId = chatId.substring(4);
    // Use the private message link format: t.me/c/<channel>/<id>
    const link = `https://t.me/c/${cleanChatId}/${messageId}`;
    console.log("Supergroup/channel link:", link);
    return link;
  }
  // For regular groups (negative IDs starting with -)
  else if (chatId.startsWith("-")) {
    // Remove the - prefix
    const cleanChatId = chatId.substring(1);
    // Use the private message link format: t.me/c/<channel>/<id>
    const link = `https://t.me/c/${cleanChatId}/${messageId}`;
    console.log("Group link:", link);
    return link;
  }
  // For private chats (positive user IDs) - can't link to specific messages via HTTP
  else {
    // For private chats, we can't link to specific messages via HTTP links
    // Just open Telegram Web
    const link = `https://web.telegram.org/k/`;
    console.log("Private chat link (no specific message):", link);
    return link;
  }
};

const getChatTypeLabel = (chatType?: string) => {
  switch (chatType) {
    case "private":
      return "Private";
    case "group":
      return "Group";
    case "supergroup":
      return "Supergroup";
    case "channel":
      return "Channel";
    default:
      return "Chat";
  }
};

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
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [chatError, setChatError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const searchAbortRef = useRef<AbortController | null>(null);
  // Monotonic sequence to avoid race conditions between overlapping searches
  const searchSeqRef = useRef(0);

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

    // Preserve original ordering priority by first occurrence (already ranked by backend)
    const groups = new Map<
      string,
      {
        base: SearchResult;
        parts: {
          idx: number;
          text: string;
          chunk_idx: number;
          score: number;
        }[];
        maxScore: number;
      }
    >();

    const headerRegex = /^\[[^\]]+\]\n\n?/; // matches leading header like [2025-08-31 10:00 • Alice]

    results.forEach((r, orderIdx) => {
      const key = `${r.chat_id}:${r.message_id}`;
      if (!groups.has(key)) {
        groups.set(key, {
          base: { ...r, id: key, chunk_idx: 0 },
          parts: [],
          maxScore: r.score,
        });
      }
      const g = groups.get(key)!;
      g.maxScore = Math.max(g.maxScore, r.score);
      // Extract chunk body (remove duplicated header after first chunk)
      let text = r.text || "";
      // For non-first chunk in a message, strip header if present to avoid repetition
      if (g.parts.length > 0) {
        text = text.replace(headerRegex, "").trimStart();
      }
      g.parts.push({
        idx: orderIdx,
        text,
        chunk_idx: r.chunk_idx,
        score: r.score,
      });
    });

    // Build aggregated messages keeping original ordering by first appearance
    const aggregated: SearchResult[] = [];
    for (const [, g] of groups) {
      // Sort parts by chunk_idx ascending to reconstruct message
      g.parts.sort((a, b) => a.chunk_idx - b.chunk_idx);
      const fullText = g.parts
        .map((p) => p.text)
        .join("\n")
        .trim();
      aggregated.push({
        ...g.base,
        text: fullText,
        score: g.maxScore, // represent best score among chunks
        chunk_idx: 0,
      });
    }

    // Order aggregated messages by their highest score (desc), tie-break by message_id
    aggregated.sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      if (a.chat_id === b.chat_id) return a.message_id - b.message_id;
      return a.chat_id.localeCompare(b.chat_id);
    });
    return aggregated;
  };

  const runSearch = async (
    q: string,
    opts: { preserveOnEmpty?: boolean } = {},
  ) => {
    const trimmed = q.trim();
    if (!trimmed) {
      if (!opts.preserveOnEmpty) {
        // User manually cleared input: clear panel
        setSearchResults([]);
        setCurrentSearchQuery("");
      }
      return;
    }

    const seq = ++searchSeqRef.current; // capture sequence id
    setSearchLoading(true);
    setSearchError(null);
    try {
      const results = await search(trimmed, { limit: 12, hybrid: true });
      // Ignore if a newer search started meanwhile
      if (seq !== searchSeqRef.current) return;
      const aggregated = aggregateSearchResults(results);
      setSearchResults(aggregated);
      setCurrentSearchQuery(trimmed);
    } catch (err: any) {
      if (seq !== searchSeqRef.current) return; // stale
      setSearchError(err?.message || "Search failed");
    } finally {
      if (seq === searchSeqRef.current) setSearchLoading(false);
    }
  };

  useEffect(() => {
    if (!input.trim()) return; // keep prior results if input cleared after send
    const h = setTimeout(() => {
      runSearch(input, { preserveOnEmpty: false });
    }, 350);
    return () => clearTimeout(h);
  }, [input]);

  const handleSend = async (message: string) => {
    if (!message.trim() || isLoading) return;

    setIsLoading(true);
    setChatError(null);

    // Add only the user message now; delay assistant bubble until first content token
    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: message,
      timestamp: new Date(),
    };
    const assistantMessageId = (Date.now() + 1).toString();
    let assistantAdded = false;

    setMessages((prev) => [...prev, userMessage]);

    // Update search panel to show relevant full messages for the just-sent query (before clearing input)
    try {
      await runSearch(message, { preserveOnEmpty: true });
    } catch {
      // ignore search errors here; main chat flow continues
    }
    setInput("");

    // Extract conversation history
    const history = messages.map((msg) => ({
      role: msg.role,
      content: msg.content,
    }));

    try {
      let fullContent = "";
      let finalCitations: ChatCitation[] = [];
      let finalUsage: ChatUsage | undefined;
      let finalTiming: number | undefined;
      let reformulatedQuery = "";

      console.log("Starting chat stream with history:", history);

      for await (const chunk of chatStream(message, {
        model_id: selectedModel,
        history: history,
      })) {
        console.log("Received chunk:", chunk);

        if (chunk.type === "reformulate") {
          if (chunk.reformulated_query) {
            reformulatedQuery = chunk.reformulated_query;
            console.log("Query reformulated:", reformulatedQuery);
          }
        } else if (chunk.type === "content") {
          if (chunk.content) {
            // First token: create assistant message and remove typing indicator
            if (!assistantAdded) {
              assistantAdded = true;
              setIsLoading(false); // hide typing indicator once real content starts
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
          // Fire a search using the (possibly) reformulated query so the side panel reflects actual context
          const qForPanel = reformulatedQuery.trim() || message;
          runSearch(qForPanel, { preserveOnEmpty: true });
        } else if (chunk.type === "end") {
          if (chunk.usage) finalUsage = chunk.usage;
          if (chunk.timing_seconds) finalTiming = chunk.timing_seconds;
          // Final update with all metadata (may still be empty content)
          if (!assistantAdded) {
            // No content streamed; create an (empty) assistant message to attach metadata
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
                    }
                  : msg,
              ),
            );
          }
          // Ensure final panel populated even if no citations chunk arrived earlier
          const qForPanel = reformulatedQuery.trim() || message;
          runSearch(qForPanel, { preserveOnEmpty: true });
        } else if (chunk.type === "error") {
          throw new Error(chunk.content || "Unknown streaming error");
        }
      }

      // No additional fallback injection; an empty assistant message signals no content was produced
    } catch (error: any) {
      setChatError(error?.message || "Chat request failed");

      // Update the assistant message with error content
      // If assistant message already added, update it; else create error message
      setMessages((prev) => {
        const exists = prev.some((m) => m.id === assistantMessageId);
        if (!exists) {
          return [
            ...prev,
            {
              id: assistantMessageId,
              role: "assistant",
              content: `Error: ${
                error?.message || "Failed to generate response"
              }`,
              timestamp: new Date(),
            },
          ];
        }
        return prev.map((msg) =>
          msg.id === assistantMessageId
            ? {
                ...msg,
                content: `Error: ${
                  error?.message || "Failed to generate response"
                }`,
              }
            : msg,
        );
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleLogout = async () => {
    try {
      await logout();
    } finally {
      window.location.href = "/login";
    }
  };

  const formatTime = (date: Date) => {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  const formatCitationLink = (citation: ChatCitation) => {
    return formatTelegramLink(
      citation.chat_id,
      citation.message_id,
      citation.source_title,
      undefined, // We don't have chat_type in citations
    );
  };

  const renderMessageContent = (message: Message) => {
    // Basic markdown-style rendering for citations
    let content = message.content;

    // If there are citations, make [n] clickable
    if (message.citations && message.citations.length > 0 && content) {
      message.citations.forEach((citation, index) => {
        const citationNum = index + 1;
        const regex = new RegExp(`\\[${citationNum}\\]`, "g");
        content = content.replace(
          regex,
          `<span class="text-blue-600 cursor-pointer font-medium underline hover:bg-blue-50 px-1 py-0.5 rounded transition-colors citation-link" data-citation="${index}">[${citationNum}]</span>`,
        );
      });
    }

    return (
      <div>
        <div
          className="text-sm leading-relaxed whitespace-pre-wrap"
          dangerouslySetInnerHTML={{ __html: content || "" }}
          onClick={(e) => {
            const target = e.target as HTMLElement;
            if (target.classList.contains("citation-link")) {
              const citationIndex = parseInt(target.dataset.citation || "0");
              if (message.citations && message.citations[citationIndex]) {
                const citation = message.citations[citationIndex];
                window.open(formatCitationLink(citation), "_blank");
              }
            }
          }}
        />

        {/* Always render styled citations list if citations are available */}
        {message.citations && message.citations.length > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-200">
            <div className="text-xs text-gray-600 mb-2 font-medium">
              Sources:
            </div>
            <div className="space-y-1">
              {message.citations.map((citation, index) => (
                <div key={citation.id} className="text-xs text-gray-600">
                  <button
                    onClick={() =>
                      window.open(formatCitationLink(citation), "_blank")
                    }
                    className="hover:text-blue-600 hover:underline text-left"
                  >
                    [{index + 1}]{" "}
                    {citation.source_title || `Chat ${citation.chat_id}`} —{" "}
                    {citation.message_date
                      ? new Date(
                          citation.message_date * 1000,
                        ).toLocaleDateString("en-US", {
                          year: "numeric",
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "Unknown date"}{" "}
                    — message {citation.message_id}
                  </button>
                </div>
              ))}
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

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold text-gray-800">RAG Chat</h1>
          <ModelPicker value={selectedModel} onModelChange={setSelectedModel} />
          {messages.length > 0 && (
            <button
              onClick={() => setMessages([])}
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
                  Found {searchResults.length} message
                  {searchResults.length !== 1 ? "s" : ""}
                  {currentSearchQuery &&
                    ` for "${currentSearchQuery.substring(0, 30)}${
                      currentSearchQuery.length > 30 ? "..." : ""
                    }"`}
                </p>
              )}
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
                  onClick={() => runSearch(input)}
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
                Type to search indexed messages…
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
                      {r.sender && (
                        <span className="text-gray-700">
                          by{" "}
                          {r.sender_username
                            ? `@${r.sender_username}`
                            : r.sender}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <span className="text-[10px] px-2 py-1 rounded-full bg-blue-50 text-blue-600 font-medium">
                      {r.score.toFixed(3)}
                    </span>
                    <button
                      onClick={() =>
                        window.open(
                          formatTelegramLink(
                            r.chat_id,
                            r.message_id,
                            r.source_title,
                            r.chat_type,
                          ),
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
              onChange={(e) => setInput(e.target.value)}
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
