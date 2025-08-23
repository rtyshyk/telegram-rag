import React from "react";
import { render, waitFor, fireEvent } from "@testing-library/react";
import ModelPicker from "../ModelPicker";
import { vi, test, expect } from "vitest";

vi.mock("../../lib/api", () => {
  const models = [
    { label: "gpt 5", id: "gpt-5" },
    { label: "gpt5 mini", id: "gpt-5-mini" },
  ];
  return { fetchModels: vi.fn().mockResolvedValue(models) };
});

const { fetchModels } = await import("../../lib/api");

test("ModelPicker loads options and stores selection", async () => {
  const { getByRole } = render(<ModelPicker />);
  await waitFor(() => {
    expect(fetchModels).toHaveBeenCalled();
  });
  const select = getByRole("combobox") as HTMLSelectElement;
  fireEvent.change(select, { target: { value: "gpt5 mini" } });
  await waitFor(() => {
    expect(window.localStorage.getItem("selected_model_label")).toBe(
      "gpt5 mini",
    );
  });
});
