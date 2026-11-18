export const branding = {
  name: "Minda",
  fullLogoUrl: "/branding/logo.svg" as string | null,
  markLogoUrl: "/branding/logo-mark.svg" as string | null,
  faviconUrl: "/branding/favicon.svg" as string | null,
  appleTouchIconUrl: null as string | null,
  assetVersion: "2",
};

export function withAssetVersion(
  url: string | null | undefined,
  version: string = branding.assetVersion,
): string | null {
  if (!url) return null;
  const trimmed = url.trim();
  if (!trimmed) return null;
  if (!version) return trimmed;
  const separator = trimmed.includes("?") ? "&" : "?";
  return `${trimmed}${separator}v=${encodeURIComponent(version)}`;
}

export function iconMimeType(url: string | null | undefined): string {
  if (!url) return "image/svg+xml";
  const clean = url.split("?")[0].split("#")[0].toLowerCase();
  if (clean.endsWith(".svg")) return "image/svg+xml";
  if (clean.endsWith(".png")) return "image/png";
  if (clean.endsWith(".webp")) return "image/webp";
  if (clean.endsWith(".ico")) return "image/x-icon";
  return "image/svg+xml";
}
