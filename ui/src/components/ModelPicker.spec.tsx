import React from "react";
import { render, waitFor, fireEvent } from "@testing-library/react";
import ModelPicker from "./ModelPicker";
import { vi, test, expect } from "vitest";

vi.mock("../lib/api", () => {
  const models = [
    { label: "gpt 5", id: "gpt-5" },
    { label: "gpt5 mini", id: "gpt-5-mini" },
    { label: "gpt5 nano", id: "gpt-5-nano" },
  ];
  return { fetchModels: vi.fn().mockResolvedValue(models) };
});

const { fetchModels } = await import("../lib/api");

test("ModelPicker loads options and stores selection", async () => {
  const mockOnModelChange = vi.fn();
  const { getByRole } = render(
    <ModelPicker onModelChange={mockOnModelChange} />,
  );
  await waitFor(() => {
    expect(fetchModels).toHaveBeenCalled();
  });

  // The component uses a button, not a combobox
  const button = getByRole("button", { name: /gpt 5/ });
  expect(button).toBeDefined();

  expect(button.textContent).toContain("gpt 5");

  // Verify that the callback is called with the model ID, not label
  await waitFor(() => {
    expect(mockOnModelChange).toHaveBeenCalledWith("gpt-5");
  });
});
