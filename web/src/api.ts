import type {
  BrandingSettings,
  CalculationShareMode,
  CatalogProvider,
  FormulaDefinition,
  RateSnapshot,
  Subscription,
  User,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let accessToken: string | null = null;
const ACCESS_TOKEN_STORAGE_KEY = "oyuns-rates-access-token";
const DEFAULT_REQUEST_TIMEOUT_MS = 25_000;
const AUTH_REQUEST_TIMEOUT_MS = 12_000;

try {
  accessToken = window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
} catch {
  // Storage may be unavailable in privacy-restricted webviews.
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
  try {
    if (token) window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token);
    else window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
  } catch {
    // The HttpOnly session cookie remains the primary auth mechanism.
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const abortFromCaller = () => controller.abort();
  options.signal?.addEventListener("abort", abortFromCaller, { once: true });
  if (options.signal?.aborted) controller.abort();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(path, {
      ...options,
      signal: controller.signal,
      credentials: "include",
      headers: {
        ...(!(options.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...(options.headers || {}),
      },
    });
  } catch (error) {
    if (controller.signal.aborted) {
      throw new ApiError(408, "Холболтын хугацаа дууслаа. Дахин оролдоно уу.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
    options.signal?.removeEventListener("abort", abortFromCaller);
  }
  if (!response.ok) {
    let message = "Алдаа гарлаа";
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // Retain the default message for non-JSON failures.
    }
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  miniAppLogin: (initData: string, apiKey: string) =>
    request<{ user: User; accessToken: string }>("/api/auth/mini-app", {
      method: "POST",
      body: JSON.stringify({ initData, apiKey }),
    }, AUTH_REQUEST_TIMEOUT_MS),
  apiKeyLogin: (apiKey: string) =>
    request<{ ok: boolean }>("/api/auth/key", {
      method: "POST",
      body: JSON.stringify({ apiKey }),
    }, AUTH_REQUEST_TIMEOUT_MS),
  me: async () => {
    try {
      return await request<{ user: User }>("/api/me", {}, AUTH_REQUEST_TIMEOUT_MS);
    } catch (error) {
      // A persisted access token may have expired while the HttpOnly cookie
      // is still valid. Retry once without the token before showing login.
      if (error instanceof ApiError && error.status === 401 && accessToken) {
        setAccessToken(null);
        return request<{ user: User }>("/api/me", {}, AUTH_REQUEST_TIMEOUT_MS);
      }
      throw error;
    }
  },
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  rates: () => request<{ rates: RateSnapshot[] }>("/api/rates"),
  searchRates: (query: string) =>
    request<{ rates: RateSnapshot[] }>(
      `/api/rates/search?q=${encodeURIComponent(query)}`,
    ),
  calculated: () => request<{ rates: RateSnapshot[] }>("/api/calculated"),
  formulas: () => request<{ formulas: FormulaDefinition[] }>("/api/formulas"),
  createFormula: (formula: Omit<FormulaDefinition, "id" | "sortOrder" | "updatedAt">) =>
    request<{ formula: FormulaDefinition }>("/api/formulas", {
      method: "POST",
      body: JSON.stringify(formula),
    }),
  updateFormula: (
    id: string,
    formula: Omit<FormulaDefinition, "id" | "sortOrder" | "updatedAt">,
  ) =>
    request<{ formula: FormulaDefinition }>(`/api/formulas/${id}`, {
      method: "PUT",
      body: JSON.stringify(formula),
    }),
  deleteFormula: (id: string) =>
    request<{ removed: boolean }>(`/api/formulas/${id}`, { method: "DELETE" }),
  orderFormulas: (ids: string[]) =>
    request<{ formulas: FormulaDefinition[] }>("/api/formulas/order", {
      method: "PUT",
      body: JSON.stringify({ ids }),
    }),
  branding: () => request<BrandingSettings>("/api/branding"),
  uploadAppLogo: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<BrandingSettings>("/api/branding/app-logo", {
      method: "PUT",
      body,
    });
  },
  deleteAppLogo: () =>
    request<BrandingSettings>("/api/branding/app-logo", { method: "DELETE" }),
  uploadSourceLogo: (provider: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<BrandingSettings>(
      `/api/branding/sources/${encodeURIComponent(provider)}`,
      { method: "PUT", body },
    );
  },
  deleteSourceLogo: (provider: string) =>
    request<BrandingSettings>(
      `/api/branding/sources/${encodeURIComponent(provider)}`,
      { method: "DELETE" },
    ),
  catalog: () => request<{ providers: CatalogProvider[] }>("/api/catalog"),
  subscriptions: () =>
    request<{ subscriptions: Subscription[] }>("/api/subscriptions"),
  subscribe: (provider: string, symbol: string) =>
    request<{ subscription: Subscription }>("/api/subscriptions", {
      method: "POST",
      body: JSON.stringify({ provider, symbol }),
    }),
  unsubscribe: (id: string) =>
    request<{ removed: boolean }>(`/api/subscriptions/${id}`, {
      method: "DELETE",
    }),
  clearSubscriptions: () =>
    request<{ removed: number }>("/api/subscriptions", { method: "DELETE" }),
  refresh: (keys: string[]) =>
    request<{ rates: RateSnapshot[] }>("/api/rates/refresh", {
      method: "POST",
      body: JSON.stringify({ keys }),
    }),
  calculate: (tokens: Array<string | number>) =>
    request<{ expression: string; result: string }>("/api/calculate", {
      method: "POST",
      body: JSON.stringify({ tokens }),
    }),
  share: (
    rateKeys: string[],
    calculationTokens?: Array<string | number>,
    calculationResultMode: CalculationShareMode = "full",
  ) =>
    request<{
      preparedMessageId: string;
      inlineQuery: string;
      handoffUrl: string | null;
      inlineFallback: string | null;
    }>("/api/shares", {
      method: "POST",
      body: JSON.stringify({
        rateKeys,
        calculationTokens,
        calculationResultMode,
      }),
    }),
  prepareBundle: (token: string) =>
    request<{ preparedMessageId: string }>(`/api/shares/${token}/prepare`, {
      method: "POST",
    }),
};
