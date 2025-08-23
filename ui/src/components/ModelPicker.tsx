import React, { useEffect, useState } from "react";
import { fetchModels } from "../lib/api";

interface Model {
  label: string;
  id: string;
}

export default function ModelPicker() {
  const [models, setModels] = useState<Model[]>([]);
  const [selected, setSelected] = useState<string>("");

  useEffect(() => {
    fetchModels()
      .then((data) => {
        setModels(data);
        const stored = localStorage.getItem("selected_model_label");
        setSelected(stored || data[0]?.label || "");
      })
      .catch((res) => {
        if (res.status === 401) window.location.href = "/login";
      });
  }, []);

  useEffect(() => {
    if (selected) localStorage.setItem("selected_model_label", selected);
  }, [selected]);

  if (!models.length) return <p>Loading...</p>;

  return (
    <select
      className="model-picker"
      value={selected}
      onChange={(e) => setSelected(e.target.value)}
    >
      {models.map((m) => (
        <option key={m.id} value={m.label}>
          {m.label}
        </option>
      ))}
    </select>
  );
}
