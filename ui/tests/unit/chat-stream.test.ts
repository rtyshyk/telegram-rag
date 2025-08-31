import { describe, it, expect, vi, beforeEach } from "vitest";
import { chatStream, ChatStreamChunk } from "../../src/lib/api";

// Mock fetch
const mockFetch = vi.fn();
global.fetch = mockFetch;

describe("Chat Streaming API", () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  it("should make correct API call with basic parameters", async () => {
    // Mock streaming response
    const mockResponse = {
      ok: true,
      status: 200,
      body: {
        getReader: () => ({
          read: vi
            .fn()
            .mockResolvedValueOnce({
              done: false,
              value: new TextEncoder().encode(
                'data: {"type":"content","content":"Test"}\n\n',
              ),
            })
            .mockResolvedValueOnce({
              done: true,
              value: null,
            }),
          releaseLock: vi.fn(),
        }),
      },
    };

    mockFetch.mockResolvedValue(mockResponse);

    const chunks: ChatStreamChunk[] = [];
    for await (const chunk of chatStream("test query")) {
      chunks.push(chunk);
    }

    expect(mockFetch).toHaveBeenCalledWith(
      "/chat",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          q: "test query",
          k: 12,
          model_id: undefined,
          filters: undefined,
          use_current_filters: true,
        }),
      }),
    );
  });

  it("should make correct API call with all parameters", async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      body: {
        getReader: () => ({
          read: vi.fn().mockResolvedValueOnce({
            done: true,
            value: null,
          }),
          releaseLock: vi.fn(),
        }),
      },
    };

    mockFetch.mockResolvedValue(mockResponse);

    const generator = chatStream("test query", {
      k: 5,
      model_id: "gpt-5",
      filters: { chat_ids: ["-123"] },
      use_current_filters: false,
    });

    // Consume the generator
    for await (const chunk of generator) {
      // Process chunks
    }

    expect(mockFetch).toHaveBeenCalledWith(
      "/chat",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          q: "test query",
          k: 5,
          model_id: "gpt-5",
          filters: { chat_ids: ["-123"] },
          use_current_filters: false,
        }),
      }),
    );
  });

  it("should stream chat response correctly", async () => {
    // Mock streaming response
    const mockResponse = {
      ok: true,
      status: 200,
      body: {
        getReader: () => ({
          read: vi
            .fn()
            .mockResolvedValueOnce({
              done: false,
              value: new TextEncoder().encode(
                'data: {"type":"search","content":"Searching..."}\n\n',
              ),
            })
            .mockResolvedValueOnce({
              done: false,
              value: new TextEncoder().encode(
                'data: {"type":"content","content":"Hello"}\n\n',
              ),
            })
            .mockResolvedValueOnce({
              done: false,
              value: new TextEncoder().encode(
                'data: {"type":"content","content":" world"}\n\n',
              ),
            })
            .mockResolvedValueOnce({
              done: false,
              value: new TextEncoder().encode(
                'data: {"type":"end","usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}\n\n',
              ),
            })
            .mockResolvedValueOnce({
              done: true,
              value: null,
            }),
          releaseLock: vi.fn(),
        }),
      },
    };

    mockFetch.mockResolvedValue(mockResponse);

    const chunks: ChatStreamChunk[] = [];
    for await (const chunk of chatStream("test query")) {
      chunks.push(chunk);
    }

    expect(chunks).toHaveLength(4);
    expect(chunks[0].type).toBe("search");
    expect(chunks[1].type).toBe("content");
    expect(chunks[1].content).toBe("Hello");
    expect(chunks[2].type).toBe("content");
    expect(chunks[2].content).toBe(" world");
    expect(chunks[3].type).toBe("end");
    expect(chunks[3].usage?.total_tokens).toBe(15);
  });

  it("should handle unauthorized streaming", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 401,
      text: () => Promise.resolve("Unauthorized"),
    });

    await expect(async () => {
      for await (const chunk of chatStream("test query")) {
        // Should not reach here
      }
    }).rejects.toThrow("Unauthorized");
  });

  it("should handle streaming errors", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve("Internal error"),
    });

    await expect(async () => {
      for await (const chunk of chatStream("test query")) {
        // Should not reach here
      }
    }).rejects.toThrow("Chat failed: 500 Internal error");
  });

  it("should handle rate limiting", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 429,
      text: () => Promise.resolve("Rate limit exceeded"),
    });

    await expect(async () => {
      for await (const chunk of chatStream("test query")) {
        // Should not reach here
      }
    }).rejects.toThrow("Chat failed: 429 Rate limit exceeded");
  });
});
