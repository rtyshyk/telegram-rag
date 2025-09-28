export interface TelegramLinkOptions {
  chatId: string;
  messageId: number;
  sourceTitle?: string;
  chatType?: string;
  chatUsername?: string | null;
  threadId?: number | null;
}

const normalizeUsername = (username?: string | null) =>
  username?.trim().replace(/^@/, "") || "";

const isNumericId = (value: string) => /^-?\d+$/.test(value);

export const formatTelegramLink = ({
  chatId,
  messageId,
  sourceTitle,
  chatType,
  chatUsername,
  threadId,
}: TelegramLinkOptions): string => {
  const normalizedUsername = normalizeUsername(chatUsername);
  const rawId = chatId?.trim() ?? "";
  const chatTypeLower = chatType?.toLowerCase();
  const isPrivateType =
    chatTypeLower === "private" ||
    chatTypeLower === "user" ||
    chatTypeLower === "bot";
  const isGroupLikeType =
    chatTypeLower === "group" ||
    chatTypeLower === "supergroup" ||
    chatTypeLower === "channel" ||
    chatTypeLower === "broadcast";
  const isUnknownType = !chatTypeLower || chatTypeLower === "unknown";
  const isNumeric = isNumericId(rawId);
  const isLikelyDirectId = isNumeric && !rawId.startsWith("-");
  const directChat =
    isPrivateType ||
    (!isGroupLikeType &&
      isUnknownType &&
      !normalizedUsername &&
      isLikelyDirectId);

  if (normalizedUsername) {
    if (isPrivateType) {
      return `https://web.telegram.org/k/#@${normalizedUsername}`;
    }
    return `https://t.me/${normalizedUsername}/${messageId}`;
  }

  if (sourceTitle === "Saved Messages") {
    return "https://web.telegram.org/k/#@me";
  }

  if (!rawId) {
    return "https://web.telegram.org/k/";
  }

  if (directChat) {
    return `https://web.telegram.org/k/#${rawId}`;
  }

  if (isNumericId(rawId)) {
    const sanitized = rawId.replace(/^-(100)?/, "").replace(/^0+/, "");
    if (sanitized) {
      const threadSegment =
        typeof threadId === "number" && threadId > 0 ? `/${threadId}` : "";
      return `https://t.me/c/${sanitized}${threadSegment}/${messageId}`;
    }
  }

  const slug = rawId.replace(/^@/, "").replace(/[^a-zA-Z0-9_]/g, "_");
  if (slug) {
    return `https://t.me/${slug}/${messageId}`;
  }

  return `https://web.telegram.org/k/#${rawId}`;
};

export default formatTelegramLink;
