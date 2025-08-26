import React, { useState, useRef, useEffect } from "react";
import ModelPicker from "./ModelPicker";
import { logout, search, SearchResult } from "../lib/api";

interface Message {
  id: string;
  content: string;
  role: "user" | "assistant";
  timestamp: Date;
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
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [showContext, setShowContext] = useState(true);
  const [currentSearchQuery, setCurrentSearchQuery] = useState<string>("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const searchAbortRef = useRef<AbortController | null>(null);

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

  const runSearch = async (q: string) => {
    if (!q.trim()) {
      setSearchResults([]);
      setCurrentSearchQuery("");
      return;
    }
    setSearchLoading(true);
    setSearchError(null);
    try {
      const results = await search(q, { limit: 6, hybrid: true });
      setSearchResults(results);
      setCurrentSearchQuery(q);
    } catch (err: any) {
      setSearchError(err?.message || "Search failed");
    } finally {
      setSearchLoading(false);
    }
  };

  useEffect(() => {
    const h = setTimeout(() => {
      runSearch(input);
    }, 350);
    return () => clearTimeout(h);
  }, [input]);

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      content: input.trim(),
      role: "user",
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    // Ensure we have search results for the sent message even if user pressed Enter before debounce fired
    (async () => {
      if (currentSearchQuery !== userMessage.content) {
        try {
          await runSearch(userMessage.content);
        } catch {
          // ignore search error here; UI panel already reflects any error
        }
      }
      // TODO: Replace with real RAG generation using searchResults
      setTimeout(() => {
        const assistantMessage: Message = {
          id: (Date.now() + 1).toString(),
          content: `This is a simulated response to: "${
            userMessage.content
          }".\n\nTop context:\n${searchResults
            .slice(0, 3)
            .map(
              (r, i) =>
                `${i + 1}. [${(r.score || 0).toFixed(3)}] ${r.text.substring(
                  0,
                  200,
                )}`,
            )
            .join("\n")}`,
          role: "assistant",
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, assistantMessage]);
        setIsLoading(false);
      }, 1000);
    })();
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

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold text-gray-800">RAG Chat</h1>
          <ModelPicker />
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
                    <p className="text-sm leading-relaxed whitespace-pre-wrap">
                      {message.content}
                    </p>
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
                      AI is thinking...
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
            {!searchLoading && searchResults.length === 0 && input.trim() && (
              <div className="text-gray-400">No matches yet.</div>
            )}
            {!input.trim() && (
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
                  handleSend(e as any);
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
            onClick={(e) => handleSend(e as any)}
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
