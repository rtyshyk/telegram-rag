import { defineConfig } from "vitest/config";
import react from "@astrojs/react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
  },
});
