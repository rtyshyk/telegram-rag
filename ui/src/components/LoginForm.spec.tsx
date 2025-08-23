import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react";
import LoginForm from "./LoginForm";
import { vi, test, expect } from "vitest";

vi.mock("../lib/api", () => ({
  login: vi.fn().mockResolvedValue(undefined),
}));

const { login } = await import("../lib/api");

test("LoginForm posts credentials", async () => {
  Object.defineProperty(window, "location", {
    value: { href: "", assign: vi.fn() },
    writable: true,
  });
  const { getByLabelText, getByRole } = render(<LoginForm />);
  fireEvent.change(getByLabelText(/Username/), { target: { value: "a" } });
  fireEvent.change(getByLabelText(/Password/), { target: { value: "b" } });
  fireEvent.click(getByRole("button", { name: /Sign in/ }));
  await waitFor(() => {
    expect(login).toHaveBeenCalledWith("a", "b");
  });
});
