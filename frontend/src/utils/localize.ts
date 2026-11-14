import en from "../locales/en.json";

export type TranslationKey = keyof typeof en;

/**
 * Look up a translation key. This fork ships English only.
 * The language argument is kept so existing call sites stay valid.
 * Supports simple {placeholder} interpolation.
 */
export function localize(
  key: TranslationKey,
  _language?: string,
  params?: Record<string, string | number>,
): string {
  let result: string = en[key] ?? key;

  if (params) {
    for (const [k, v] of Object.entries(params)) {
      result = result.replaceAll(`{${k}}`, String(v));
    }
  }

  return result;
}
