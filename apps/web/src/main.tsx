import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { Toaster } from "sonner";
import { Check } from "lucide-react";
import App from "./app";
import "./index.css";
import "./styles.css";
import "./motion.css";
import "./workspace.css";
import "./styles/base.css";
import "./styles/layout.css";
import "./styles/components.css";
import "./styles/experience.css";
const client = new QueryClient({
  defaultOptions: {
    queries: { retry: false, staleTime: 1000, refetchOnWindowFocus: true },
  },
});
const router = createBrowserRouter([{ path: "*", element: <App /> }]);
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
      <Toaster
        position="top-right"
        richColors
        closeButton
        icons={{
          success: <Check className="confirmation-check" size={18} />,
        }}
      />
    </QueryClientProvider>
  </React.StrictMode>,
);
