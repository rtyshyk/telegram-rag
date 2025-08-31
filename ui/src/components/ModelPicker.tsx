import React, { useEffect, useState } from "react";
import { fetchModels } from "../lib/api";

interface Model {
  label: string;
  id: string;
}

interface ModelPickerProps {
  onModelChange?: (modelId: string) => void;
  value?: string;
}

export default function ModelPicker({
  onModelChange,
  value,
}: ModelPickerProps) {
  const [models, setModels] = useState<Model[]>([]);
  const [selected, setSelected] = useState<string>(value || "");
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    fetchModels()
      .then((data) => {
        setModels(data);
        if (!value) {
          const stored = localStorage.getItem("selected_model_id");
          const initialModel = stored || data[0]?.id || "";
          setSelected(initialModel);
          if (onModelChange && initialModel) {
            onModelChange(initialModel);
          }
        }
      })
      .catch((res) => {
        if (res.status === 401) window.location.href = "/login";
      });
  }, [value, onModelChange]);

  useEffect(() => {
    if (value !== undefined) {
      setSelected(value);
    }
  }, [value]);

  useEffect(() => {
    if (selected) localStorage.setItem("selected_model_id", selected);
  }, [selected]);

  const handleModelSelect = (modelId: string) => {
    setSelected(modelId);
    setIsOpen(false);
    if (onModelChange) {
      onModelChange(modelId);
    }
  };

  if (!models.length) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-100 rounded-lg">
        <div className="w-4 h-4 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin"></div>
        <span className="text-sm text-gray-600">Loading models...</span>
      </div>
    );
  }

  const selectedModel = models.find((m) => m.id === selected);

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors text-sm font-medium text-gray-700"
      >
        <div className="w-2 h-2 bg-green-500 rounded-full"></div>
        <span>{selectedModel?.label || "Select Model"}</span>
        <svg
          className={`w-4 h-4 transition-transform ${
            isOpen ? "rotate-180" : ""
          }`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </button>

      {isOpen && (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={() => setIsOpen(false)}
          ></div>
          <div className="absolute top-full left-0 mt-1 w-64 bg-white rounded-lg shadow-lg border border-gray-200 z-20">
            <div className="p-2">
              <div className="text-xs font-medium text-gray-500 px-3 py-2 border-b border-gray-100">
                Available Models
              </div>
              <div className="py-1">
                {models.map((model) => (
                  <button
                    key={model.id}
                    onClick={() => handleModelSelect(model.id)}
                    className={`w-full text-left px-3 py-2 text-sm rounded-md transition-colors ${
                      selected === model.id
                        ? "bg-blue-50 text-blue-700 font-medium"
                        : "text-gray-700 hover:bg-gray-50"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <div
                        className={`w-2 h-2 rounded-full ${
                          selected === model.id ? "bg-blue-500" : "bg-gray-300"
                        }`}
                      ></div>
                      <span>{model.label}</span>
                      {selected === model.id && (
                        <svg
                          className="w-4 h-4 ml-auto text-blue-500"
                          fill="currentColor"
                          viewBox="0 0 20 20"
                        >
                          <path
                            fillRule="evenodd"
                            d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                            clipRule="evenodd"
                          />
                        </svg>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
