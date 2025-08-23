import React, { useState } from "react";
import ModelPicker from "./ModelPicker";
import { logout } from "../lib/api";

export default function ProtectedApp() {
  const [messages, setMessages] = useState<string[]>([]);
  const [input, setInput] = useState("");

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    setMessages((m) => [...m, input]);
    setInput("");
  };

  const handleLogout = async () => {
    try {
      await logout();
    } finally {
      window.location.href = "/login";
    }
  };

  return (
    <div className="chat-container">
      <header className="chat-header">
        <ModelPicker />
        <button className="logout" onClick={handleLogout}>
          Logout
        </button>
      </header>
      <div className="chat-messages">
        {messages.map((m, i) => (
          <div key={i} className="chat-message">
            {m}
          </div>
        ))}
      </div>
      <form className="chat-input" onSubmit={handleSend}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
        />
      </form>
    </div>
  );
}

