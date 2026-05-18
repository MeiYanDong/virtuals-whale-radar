export const BRAND_LOGO_SRC = import.meta.env.DEV
  ? "/brand/logo-mark.png"
  : "/admin/brand/logo-mark.png";

export const BRAND_LOGO_FALLBACK_SRC = import.meta.env.DEV
  ? "/admin/brand/logo-mark.png"
  : "/brand/logo-mark.png";

export function buildBrandLogoCandidates() {
  return [BRAND_LOGO_SRC, BRAND_LOGO_FALLBACK_SRC].filter(
    (value, index, items) => value && items.indexOf(value) === index,
  );
}

export function getBrandLogoUrl() {
  return new URL(BRAND_LOGO_SRC, window.location.origin).toString();
}
