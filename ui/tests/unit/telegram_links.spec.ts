import { describe, expect, it } from "vitest";
import { formatTelegramLink } from "../../src/lib/telegram_links";

describe("formatTelegramLink", () => {
  it("returns DM link for username-based private chat", () => {
    const link = formatTelegramLink({
      chatId: "12345",
      messageId: 42,
      chatType: "private",
      chatUsername: "someone",
    });
    expect(link).toBe("https://web.telegram.org/k/#@someone");
  });

  it("returns DM link for numeric private chat without username", () => {
    const link = formatTelegramLink({
      chatId: "890506398",
      messageId: 123,
      chatType: "private",
    });
    expect(link).toBe("https://web.telegram.org/k/#890506398");
  });

  it("falls back to DM link when type unknown and username absent", () => {
    const link = formatTelegramLink({
      chatId: "890506398",
      messageId: 86032,
      chatType: "unknown",
    });
    expect(link).toBe("https://web.telegram.org/k/#890506398");
  });

  it("falls back to DM link when type missing but username provided", () => {
    const link = formatTelegramLink({
      chatId: "890506398",
      messageId: 86032,
      chatUsername: "friendlyuser",
    });
    expect(link).toBe("https://t.me/friendlyuser/86032");
  });

  it("returns t.me link for username-based channel when type unknown", () => {
    const link = formatTelegramLink({
      chatId: "1271266957",
      messageId: 94357,
      chatType: "unknown",
      chatUsername: "replies",
    });
    expect(link).toBe("https://t.me/replies/94357");
  });

  it("returns t.me link for username-based group", () => {
    const link = formatTelegramLink({
      chatId: "-1001271266957",
      messageId: 59739,
      chatType: "unknown",
      chatUsername: "replies",
    });
    expect(link).toBe("https://t.me/replies/59739");
  });

  it("returns private group link for numeric chat id", () => {
    const link = formatTelegramLink({
      chatId: "-2307581122",
      messageId: 3266,
      chatType: "group",
    });
    expect(link).toBe("https://t.me/c/2307581122/3266");
  });

  it("returns saved messages link", () => {
    const link = formatTelegramLink({
      chatId: "self",
      messageId: 1,
      sourceTitle: "Saved Messages",
    });
    expect(link).toBe("https://web.telegram.org/k/#@me");
  });
});
