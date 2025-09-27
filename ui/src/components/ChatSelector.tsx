import React, { useState, useEffect, useRef } from "react";
import { fetchChats, ChatInfo } from "../lib/api";

interface ChatSelectorProps {
  value: string;
  onChatChange: (chatId: string) => void;
}

export default function ChatSelector({
  value,
  onChatChange,
}: ChatSelectorProps) {
  const [chats, setChats] = useState<ChatInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadChats();
  }, []);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
        setSearchTerm("");
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  const loadChats = async () => {
    try {
      setLoading(true);
      setError(null);
      const chatsData = await fetchChats();
      setChats(chatsData);

      // Load saved chat from localStorage
      const savedChat = localStorage.getItem("selectedChatId");
      if (savedChat && chatsData.some((chat) => chat.chat_id === savedChat)) {
        onChatChange(savedChat);
      } else if (chatsData.length > 0 && !value) {
        // Default to "All Chats" (empty value)
        onChatChange("");
      }
    } catch (err: any) {
      setError(err?.message || "Failed to load chats");
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (chatId: string) => {
    onChatChange(chatId);
    // Save to localStorage
    if (chatId) {
      localStorage.setItem("selectedChatId", chatId);
    } else {
      localStorage.removeItem("selectedChatId");
    }
  };

  const getChatLabel = (chat: ChatInfo) => {
    if (chat.source_title) {
      return chat.source_title;
    }

    // Format chat_id for display
    if (chat.chat_id.startsWith("-100")) {
      return `Supergroup ${chat.chat_id.substring(4)}`;
    } else if (chat.chat_id.startsWith("-")) {
      return `Group ${chat.chat_id.substring(1)}`;
    } else {
      return `Private ${chat.chat_id}`;
    }
  };

  // Filter chats based on search term
  const filteredChats = chats.filter((chat) => {
    if (!searchTerm) return true;

    const searchLower = searchTerm.toLowerCase();
    const chatLabel = getChatLabel(chat).toLowerCase();
    const chatId = chat.chat_id.toLowerCase();

    return chatLabel.includes(searchLower) || chatId.includes(searchLower);
  });

  const getChatTypeIcon = (chatType?: string) => {
    switch (chatType) {
      case "private":
        return "👤";
      case "group":
        return "👥";
      case "supergroup":
        return "👥";
      case "channel":
        return "📢";
      default:
        return "💬";
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-100 rounded-lg">
        <div className="w-4 h-4 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin" />
        <span className="text-sm text-gray-600">Loading chats...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-red-50 border border-red-200 rounded-lg">
        <span className="text-sm text-red-600">Failed to load chats</span>
        <button
          onClick={loadChats}
          className="text-xs px-2 py-1 bg-red-600 text-white rounded hover:bg-red-700"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-gray-600 font-medium">Chat:</span>
      <div className="relative min-w-[200px]" ref={dropdownRef}>
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          className="w-full px-3 py-2 text-left text-sm border border-gray-300 rounded-lg bg-white hover:border-blue-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-200 transition-colors flex items-center justify-between"
        >
          <span className="truncate">
            {value
              ? (() => {
                  const selectedChat = chats.find(
                    (chat) => chat.chat_id === value,
                  );
                  return selectedChat
                    ? `${getChatTypeIcon(
                        selectedChat.chat_type,
                      )} ${getChatLabel(selectedChat)} ${
                        selectedChat.message_count > 0
                          ? `(${selectedChat.message_count})`
                          : ""
                      }`
                    : `Chat ${value}`;
                })()
              : `All Chats (${chats.length})`}
          </span>
          <svg
            className="w-4 h-4 text-gray-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </button>

        {isOpen && (
          <div className="absolute z-50 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-hidden">
            {/* Search input */}
            <div className="p-2 border-b border-gray-200">
              <input
                type="text"
                placeholder="Search chats..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full px-2 py-1 text-sm border border-gray-300 rounded focus:border-blue-500 focus:ring-1 focus:ring-blue-200 outline-none"
                autoFocus
              />
            </div>

            {/* Options list */}
            <div className="max-h-48 overflow-y-auto">
              <button
                onClick={() => {
                  handleChange("");
                  setIsOpen(false);
                  setSearchTerm("");
                }}
                className="w-full px-3 py-2 text-left text-sm hover:bg-blue-50 focus:bg-blue-50 outline-none"
              >
                All Chats ({chats.length})
              </button>

              {filteredChats.map((chat) => (
                <button
                  key={chat.chat_id}
                  onClick={() => {
                    handleChange(chat.chat_id);
                    setIsOpen(false);
                    setSearchTerm("");
                  }}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-blue-50 focus:bg-blue-50 outline-none flex items-center gap-1"
                >
                  <span>{getChatTypeIcon(chat.chat_type)}</span>
                  <span className="truncate">{getChatLabel(chat)}</span>
                  {chat.message_count > 0 && (
                    <span className="text-gray-500">
                      ({chat.message_count})
                    </span>
                  )}
                </button>
              ))}

              {filteredChats.length === 0 && searchTerm && (
                <div className="px-3 py-2 text-sm text-gray-500">
                  No chats found matching "{searchTerm}"
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
