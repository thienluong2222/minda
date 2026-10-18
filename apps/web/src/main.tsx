import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "sonner";
import { Check } from "lucide-react";
import App from "./app";
import "./index.css";
import "./styles.css";
import "./motion.css";
const client = new QueryClient({
  defaultOptions: {
    queries: { retry: false, staleTime: 1000, refetchOnWindowFocus: true },
  },
});
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <App />
        <Toaster
          position="top-right"
          richColors
          closeButton
          icons={{
            success: <Check className="confirmation-check" size={18} />,
          }}
        />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
