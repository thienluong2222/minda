import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";
import {
  branding,
  iconMimeType,
  withAssetVersion,
} from "./src/config/branding";

function mindaBrandingHtmlPlugin(): Plugin {
  return {
    name: "minda-branding-html",
    transformIndexHtml(html) {
      const faviconHref = withAssetVersion(branding.faviconUrl);
      const appleHref = withAssetVersion(branding.appleTouchIconUrl);
      const tags: string[] = [
        `<meta name="application-name" content="${branding.name}">`,
      ];
      if (faviconHref) {
        const mime = iconMimeType(branding.faviconUrl);
        tags.push(`<link rel="icon" type="${mime}" href="${faviconHref}">`);
      }
      if (appleHref) {
        tags.push(`<link rel="apple-touch-icon" href="${appleHref}">`);
      }
      tags.push(`<title>${branding.name} · Trợ lý biên bản cuộc họp</title>`);
      return html.replace("<!-- MINDA_BRANDING_HEAD -->", tags.join("\n    "));
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), mindaBrandingHtmlPlugin()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: { proxy: { "/api": "http://127.0.0.1:8010" } },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: [
            "react",
            "react-dom",
            "react-router-dom",
            "@tanstack/react-query",
          ],
          ui: ["radix-ui", "sonner", "class-variance-authority"],
        },
      },
    },
  },
});
