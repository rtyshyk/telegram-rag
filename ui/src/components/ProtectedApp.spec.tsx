import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import React from "react";
import ProtectedApp from "./ProtectedApp";

// Base mock for api module used by first two suites
vi.mock("../lib/api", () => {
  return {
    logout: vi.fn(),
    fetchModels: vi.fn().mockResolvedValue([{ label: "Model A", id: "a" }]),
    search: vi.fn((q: string) => {
      if (q === "err") return Promise.reject(new Error("Boom"));
      if (!q.trim()) return Promise.resolve([]);
      // delay to let loading state be observable
      return new Promise((resolve) =>
        setTimeout(
          () =>
            resolve([
              {
                id: "1",
                text: "Result one about " + q,
                chat_id: "chat",
                message_id: 1,
                chunk_idx: 0,
                score: 0.9,
              },
            ]),
          20,
        ),
      );
    }),
  };
});

describe("ProtectedApp search panel", () => {
  afterEach(() => {
    cleanup();
  });

  it("shows loading then results", async () => {
    render(<ProtectedApp />);
    const textarea = screen.getByPlaceholderText(/Type your message/i);
    fireEvent.change(textarea, { target: { value: "hello" } });
    // loading indicator
    await screen.findByText((t) => t.startsWith("Searching"));
    await screen.findByText(/Result one about hello/);
  }, 10000);

  it("shows error and retry works", async () => {
    render(<ProtectedApp />);
    const textarea = screen.getByPlaceholderText(/Type your message/i);
    fireEvent.change(textarea, { target: { value: "err" } });
    await screen.findByText(/Boom/);
    fireEvent.change(textarea, { target: { value: "ok" } });
    await screen.findByText((t) => t.startsWith("Searching"));
    await screen.findByText(/Result one about ok/);
  }, 10000);
});

// Integration smoke test removed (no dedicated search input); covered by first test.
