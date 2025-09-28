import { ChatCitation } from "./api";
import { formatTelegramLink } from "./telegram_links";

export const formatDate = (timestamp?: number) => {
  if (!timestamp) return "Unknown date";
  const ms = timestamp > 1e12 ? timestamp : timestamp * 1000;
  return new Date(ms).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

export const getChatTypeLabel = (chatType?: string) => {
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

export const formatTime = (date: Date) => {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

export const formatCitationLink = (citation: ChatCitation) => {
  return formatTelegramLink({
    chatId: citation.chat_id,
    messageId: citation.message_id,
    sourceTitle: citation.source_title,
    chatType: citation.chat_type,
    chatUsername: citation.chat_username,
    threadId: citation.thread_id,
  });
};

export const formatCitationAuthor = (citation: ChatCitation) => {
  const usernameRaw = citation.sender_username?.trim();
  const handle = usernameRaw
    ? usernameRaw.startsWith("@")
      ? usernameRaw
      : `@${usernameRaw}`
    : "";
  const displayName = citation.sender?.trim() ?? "";

  if (handle && displayName) {
    return `${handle} (${displayName})`;
  }

  if (handle) {
    return handle;
  }

  if (displayName) {
    return displayName;
  }

  return `message ${citation.message_id}`;
};

export const getReferencedCitationIndices = (
  content: string | undefined,
  citationCount: number,
): number[] => {
  if (!content || citationCount <= 0) {
    return [];
  }

  const referenced = new Set<number>();
  const regex = /\[(\d+)\]/g;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(content)) !== null) {
    const num = Number.parseInt(match[1], 10);
    if (!Number.isNaN(num) && num >= 1 && num <= citationCount) {
      referenced.add(num - 1);
    }
  }

  return Array.from(referenced).sort((a, b) => a - b);
};
