import React from "react";
import { fireEvent, render, waitFor } from "@testing-library/react";
import ModelPicker from "./ModelPicker";
import { vi, test, expect, beforeEach, afterEach } from "vitest";
import * as api from "../lib/api";

const models = [
  { label: "Test Chat", id: "test/chat-model" },
  { label: "Another", id: "test/another" },
];

beforeEach(() => {
  vi.stubGlobal("localStorage", {
    getItem: vi.fn(() => null),
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
  });
  vi.spyOn(api, "fetchModels").mockResolvedValue(models);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("ModelPicker loads options and stores selection", async () => {
  const mockOnModelChange = vi.fn();
  const { getByRole } = render(
    <ModelPicker onModelChange={mockOnModelChange} />,
  );
  await waitFor(() => {
    expect(api.fetchModels).toHaveBeenCalled();
  });

  const button = await waitFor(() =>
    getByRole("button", { name: /Test Chat/ }),
  );
  expect(button.textContent).toContain("Test Chat");

  await waitFor(() => {
    expect(mockOnModelChange).toHaveBeenCalledWith("test/chat-model");
  });
});

test("ModelPicker dropdown list is scrollable", async () => {
  const { getByRole, getByText } = render(<ModelPicker />);
  const trigger = await waitFor(() =>
    getByRole("button", { name: /Test Chat/ }),
  );
  fireEvent.click(trigger);
  const list = await waitFor(
    () => getByText("Available Models").nextElementSibling,
  );
  expect(list?.className).toContain("overflow-y-auto");
  expect(list?.className).toContain("max-h-48");
});

test("ModelPicker shows error when models fail to load", async () => {
  vi.mocked(api.fetchModels).mockRejectedValue({ status: 502 });
  const { getByRole } = render(<ModelPicker />);
  await waitFor(() => {
    expect(getByRole("alert")).toHaveTextContent(
      "Could not load models from the API.",
    );
  });
});
