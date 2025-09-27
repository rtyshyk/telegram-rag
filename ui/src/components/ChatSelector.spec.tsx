import React from "react";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import ChatSelector from "./ChatSelector";
import * as api from "../lib/api";

// Mock the API module
vi.mock("../lib/api", () => ({
  fetchChats: vi.fn(),
}));

const { fetchChats } = await import("../lib/api");

// Mock localStorage
const localStorageMock = {
  getItem: vi.fn(),
  setItem: vi.fn(),
  removeItem: vi.fn(),
};
Object.defineProperty(window, "localStorage", {
  value: localStorageMock,
});

describe("ChatSelector", () => {
  const mockOnChatChange = vi.fn();
  const mockChats = [
    {
      chat_id: "123456789",
      source_title: "Saved Messages",
      chat_type: "private",
      message_count: 50,
    },
    {
      chat_id: "-100987654321",
      source_title: "Test Supergroup",
      chat_type: "supergroup",
      message_count: 150,
    },
    {
      chat_id: "-987654322",
      source_title: undefined,
      chat_type: "group",
      message_count: 25,
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.getItem.mockReturnValue(null);
  });

  afterEach(() => {
    cleanup();
  });

  it("renders loading state initially", () => {
    vi.mocked(fetchChats).mockImplementation(
      () => new Promise(() => {}), // Never resolves
    );

    render(<ChatSelector value="" onChatChange={mockOnChatChange} />);

    expect(screen.getByText("Loading chats...")).toBeDefined();
  });

  it("renders dropdown button after loading", async () => {
    vi.mocked(fetchChats).mockResolvedValue(mockChats);

    render(<ChatSelector value="" onChatChange={mockOnChatChange} />);

    await waitFor(() => {
      const button = screen.getByRole("button", { name: /All Chats/ });
      expect(button).toHaveTextContent("All Chats (3)");
    });
  });

  it("opens dropdown when button is clicked and shows search input", async () => {
    vi.mocked(fetchChats).mockResolvedValue(mockChats);

    render(<ChatSelector value="" onChatChange={mockOnChatChange} />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /All Chats/ })).toHaveTextContent("All Chats (3)");
    });

    fireEvent.click(screen.getByRole("button", { name: /All Chats/ }));

    await waitFor(() => {
      expect(screen.getByPlaceholderText("Search chats...")).toBeInTheDocument();
      expect(screen.getAllByRole("button", { name: /All Chats \(3\)/ })).toHaveLength(2);
      expect(screen.getByText("Saved Messages")).toBeInTheDocument();
    });
  });

  it("filters chats based on search input", async () => {
    vi.mocked(fetchChats).mockResolvedValue(mockChats);

    render(<ChatSelector value="" onChatChange={mockOnChatChange} />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /All Chats/ })).toHaveTextContent("All Chats (3)");
    });

    fireEvent.click(screen.getByRole("button", { name: /All Chats/ }));

    await waitFor(() => {
      expect(screen.getByPlaceholderText("Search chats...")).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText("Search chats...");
    fireEvent.change(searchInput, { target: { value: "saved" } });

    await waitFor(() => {
      expect(screen.getByText("Saved Messages")).toBeInTheDocument();
      expect(screen.queryByText("Test Supergroup")).not.toBeInTheDocument();
    });
  });

  it("shows no results message when search has no matches", async () => {
    vi.mocked(fetchChats).mockResolvedValue(mockChats);

    render(<ChatSelector value="" onChatChange={mockOnChatChange} />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /All Chats/ })).toHaveTextContent("All Chats (3)");
    });

    fireEvent.click(screen.getByRole("button", { name: /All Chats/ }));

    await waitFor(() => {
      expect(screen.getByPlaceholderText("Search chats...")).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText("Search chats...");
    fireEvent.change(searchInput, { target: { value: "nonexistent" } });

    await waitFor(() => {
      expect(screen.getByText('No chats found matching "nonexistent"')).toBeInTheDocument();
    });
  });

  it("handles chat selection and saves to localStorage", async () => {
    vi.mocked(fetchChats).mockResolvedValue(mockChats);

    render(<ChatSelector value="" onChatChange={mockOnChatChange} />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /All Chats/ })).toHaveTextContent("All Chats (3)");
    });

    fireEvent.click(screen.getByRole("button", { name: /All Chats/ }));

    await waitFor(() => {
      expect(screen.getByText("Saved Messages")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Saved Messages"));

    expect(mockOnChatChange).toHaveBeenCalledWith("123456789");
    expect(localStorageMock.setItem).toHaveBeenCalledWith("selectedChatId", "123456789");
  });

  it("displays selected chat correctly", async () => {
    vi.mocked(fetchChats).mockResolvedValue(mockChats);

    render(<ChatSelector value="123456789" onChatChange={mockOnChatChange} />);

    await waitFor(() => {
      const button = screen.getByRole("button", { name: /Saved Messages/ });
      expect(button).toHaveTextContent("👤 Saved Messages (50)");
    });
  });

  it("removes from localStorage when 'All Chats' is selected", async () => {
    vi.mocked(fetchChats).mockResolvedValue(mockChats);

    render(<ChatSelector value="123456789" onChatChange={mockOnChatChange} />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Saved Messages/ })).toHaveTextContent("👤 Saved Messages (50)");
    });

    fireEvent.click(screen.getByRole("button", { name: /Saved Messages/ }));

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: /All Chats \(3\)/ })).toHaveLength(1);
    });

    fireEvent.click(screen.getAllByRole("button", { name: /All Chats \(3\)/ })[0]);

    expect(mockOnChatChange).toHaveBeenCalledWith("");
    expect(localStorageMock.removeItem).toHaveBeenCalledWith("selectedChatId");
  });

  it("displays chat with correct formatting when source_title is null", async () => {
    vi.mocked(fetchChats).mockResolvedValue(mockChats);

    render(<ChatSelector value="" onChatChange={mockOnChatChange} />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /All Chats/ })).toHaveTextContent("All Chats (3)");
    });

    fireEvent.click(screen.getByRole("button", { name: /All Chats/ }));

    await waitFor(() => {
      expect(screen.getByText("Group 987654322")).toBeInTheDocument();
    });
  });
});
