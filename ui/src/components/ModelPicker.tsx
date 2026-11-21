import React, { useEffect, useState } from "react";
import { fetchModels } from "../lib/api";

interface Model {
  label: string;
  id: string;
}

type LoadState = "loading" | "ready" | "error" | "empty";

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
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [errorMessage, setErrorMessage] = useState<string>("");

  useEffect(() => {
    setLoadState("loading");
    setErrorMessage("");
    fetchModels()
      .then((data) => {
        if (!data?.length) {
          setModels([]);
          setLoadState("empty");
          return;
        }
        setModels(data);
        setLoadState("ready");
        if (value === undefined) {
          let stored: string | null = null;
          try {
            stored = localStorage.getItem("selected_model_id");
          } catch {
            stored = null;
          }
          const storedValid = data.some((m) => m.id === stored);
          const initialModel = (storedValid && stored) || data[0]?.id || "";
          setSelected(initialModel);
          if (onModelChange && initialModel) {
            onModelChange(initialModel);
          }
        }
      })
      .catch((res) => {
        if (res?.status === 401) {
          window.location.href = "/login";
          return;
        }
        setModels([]);
        setLoadState("error");
        setErrorMessage("Could not load models from the API.");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (value !== undefined) {
      setSelected(value);
    }
  }, [value]);

  useEffect(() => {
    if (!selected) return;
    try {
      localStorage.setItem("selected_model_id", selected);
    } catch {
      // Ignore when storage is unavailable (e.g. private mode, test env).
    }
  }, [selected]);

  const handleModelSelect = (modelId: string) => {
    setSelected(modelId);
    setIsOpen(false);
    if (onModelChange) {
      onModelChange(modelId);
    }
  };

  if (loadState === "loading") {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-100 rounded-lg">
        <div className="w-4 h-4 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin"></div>
        <span className="text-sm text-gray-600">Loading models...</span>
      </div>
    );
  }

  if (loadState === "error") {
    return (
      <div
        className="flex items-center gap-2 px-3 py-2 bg-red-50 rounded-lg border border-red-200"
        role="alert"
      >
        <span className="text-sm text-red-700">{errorMessage}</span>
      </div>
    );
  }

  if (loadState === "empty") {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-amber-50 rounded-lg border border-amber-200">
        <span className="text-sm text-amber-800">
          No chat models available.
        </span>
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
        <span className="max-w-48 truncate" title={selectedModel?.label}>
          {selectedModel?.label || "Select Model"}
        </span>
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
          <div className="absolute top-full left-0 mt-1 w-80 max-h-60 overflow-hidden bg-white rounded-lg shadow-lg border border-gray-200 z-20">
            <div className="p-2">
              <div className="text-xs font-medium text-gray-500 px-3 py-2 border-b border-gray-100">
                Available Models
              </div>
              <div className="py-1 max-h-48 overflow-y-auto">
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
                      <span
                        className="truncate min-w-0 flex-1"
                        title={model.label}
                      >
                        {model.label}
                      </span>
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
