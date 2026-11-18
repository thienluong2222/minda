import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { branding, iconMimeType, withAssetVersion } from "@/config/branding";

export type BrandContext = "public" | "login" | "sidebar" | "rail" | "mobile";
export type BrandVariant = "full" | "mark";

export interface BrandProps {
  variant?: BrandVariant;
  context?: BrandContext;
  to?: string | null;
  label?: string;
  subtitle?: string;
  className?: string;
}

const CONTEXT_DIMENSIONS: Record<
  BrandContext,
  { maxHeight: number; maxWidth: number; markSize: number }
> = {
  public: { maxHeight: 36, maxWidth: 180, markSize: 32 },
  login: { maxHeight: 40, maxWidth: 200, markSize: 36 },
  sidebar: { maxHeight: 32, maxWidth: 160, markSize: 32 },
  rail: { maxHeight: 32, maxWidth: 32, markSize: 32 },
  mobile: { maxHeight: 32, maxWidth: 32, markSize: 32 },
};

function FallbackMarkSvg({ size }: { size: number }) {
  return (
    <svg
      className="minda-brand-fallback-svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M2 10v3" />
      <path d="M6 6v11" />
      <path d="M10 3v18" />
      <path d="M14 8v7" />
      <path d="M18 5v13" />
      <path d="M22 10v3" />
    </svg>
  );
}

export function syncBrandingHead() {
  if (typeof document === "undefined") return;
  const faviconHref = withAssetVersion(branding.faviconUrl);
  let iconLink = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (faviconHref) {
    if (!iconLink) {
      iconLink = document.createElement("link");
      iconLink.rel = "icon";
      document.head.appendChild(iconLink);
    }
    const mime = iconMimeType(branding.faviconUrl);
    if (iconLink.type !== mime) iconLink.type = mime;
    if (iconLink.getAttribute("href") !== faviconHref) {
      iconLink.setAttribute("href", faviconHref);
    }
  } else if (iconLink) {
    iconLink.remove();
  }

  const appleHref = withAssetVersion(branding.appleTouchIconUrl);
  let appleLink = document.querySelector<HTMLLinkElement>(
    'link[rel="apple-touch-icon"]',
  );
  if (appleHref) {
    if (!appleLink) {
      appleLink = document.createElement("link");
      appleLink.rel = "apple-touch-icon";
      document.head.appendChild(appleLink);
    }
    if (appleLink.getAttribute("href") !== appleHref) {
      appleLink.setAttribute("href", appleHref);
    }
  } else if (appleLink) {
    appleLink.remove();
  }
}

export function Brand({
  variant = "full",
  context = "sidebar",
  to = null,
  label,
  subtitle,
  className = "",
}: BrandProps) {
  const effectiveVariant: BrandVariant =
    context === "rail" || context === "mobile" ? "mark" : variant;
  const dims = CONTEXT_DIMENSIONS[context];

  const fullSrc = withAssetVersion(branding.fullLogoUrl);
  const markSrc = withAssetVersion(branding.markLogoUrl);

  const [failedFullSrc, setFailedFullSrc] = useState<string | null>(null);
  const [failedMarkSrc, setFailedMarkSrc] = useState<string | null>(null);

  useEffect(() => {
    syncBrandingHead();
  }, []);

  const canUseFullImage =
    effectiveVariant === "full" &&
    Boolean(fullSrc) &&
    failedFullSrc !== fullSrc;
  const canUseMarkImage = Boolean(markSrc) && failedMarkSrc !== markSrc;

  const isLinked = Boolean(to);
  const accessibleName = label || branding.name;
  const showWordmarkText = effectiveVariant === "full" && !canUseFullImage;

  const content = canUseFullImage ? (
    <span
      className="minda-brand-full-slot"
      style={{
        height: `${dims.maxHeight}px`,
        width: `${dims.maxWidth}px`,
      }}
    >
      <img
        src={fullSrc!}
        alt={isLinked ? "" : accessibleName}
        aria-hidden={isLinked ? "true" : undefined}
        className="minda-brand-full-img"
        style={{
          maxHeight: `${dims.maxHeight}px`,
          maxWidth: `${dims.maxWidth}px`,
        }}
        onError={() => setFailedFullSrc(fullSrc)}
      />
    </span>
  ) : (
    <>
      <span
        className="minda-brand-mark-slot"
        style={{
          width: `${dims.markSize}px`,
          height: `${dims.markSize}px`,
        }}
        aria-hidden={isLinked || showWordmarkText ? "true" : undefined}
      >
        {canUseMarkImage ? (
          <img
            src={markSrc!}
            alt={isLinked || showWordmarkText ? "" : accessibleName}
            aria-hidden={isLinked || showWordmarkText ? "true" : undefined}
            width={dims.markSize}
            height={dims.markSize}
            className="minda-brand-mark-img"
            onError={() => setFailedMarkSrc(markSrc)}
          />
        ) : (
          <FallbackMarkSvg size={Math.round(dims.markSize * 0.56)} />
        )}
      </span>
      {showWordmarkText ? (
        <span className="minda-brand-wordmark">
          <strong className="minda-brand-name">{branding.name}</strong>
          {subtitle ? (
            <small className="minda-brand-subtitle">{subtitle}</small>
          ) : null}
        </span>
      ) : !isLinked && !canUseMarkImage ? (
        <span className="sr-only">{accessibleName}</span>
      ) : null}
    </>
  );

  const rootClassName = [
    "minda-brand",
    `minda-brand--${context}`,
    `minda-brand--${effectiveVariant}`,
    canUseFullImage ? "minda-brand--image-wordmark" : "minda-brand--composed",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  if (to) {
    return (
      <Link to={to} className={rootClassName} aria-label={accessibleName}>
        {content}
      </Link>
    );
  }

  return (
    <div
      className={rootClassName}
      role={!showWordmarkText && !canUseFullImage ? "img" : undefined}
      aria-label={
        !showWordmarkText && !canUseFullImage ? accessibleName : undefined
      }
    >
      {content}
    </div>
  );
}
