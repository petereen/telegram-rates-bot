import type {
  CatalogProvider,
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

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
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
  miniAppLogin: (initData: string) =>
    request<{ user: User }>("/api/auth/mini-app", {
      method: "POST",
      body: JSON.stringify({ initData }),
    }),
  me: () => request<{ user: User }>("/api/me"),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  rates: () => request<{ rates: RateSnapshot[] }>("/api/rates"),
  calculated: () => request<{ rates: RateSnapshot[] }>("/api/calculated"),
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
  share: (rateKeys: string[], calculationTokens?: Array<string | number>) =>
    request<{
      preparedMessageId: string;
      inlineQuery: string;
      handoffUrl: string | null;
      inlineFallback: string | null;
    }>("/api/shares", {
      method: "POST",
      body: JSON.stringify({ rateKeys, calculationTokens }),
    }),
  prepareBundle: (token: string) =>
    request<{ preparedMessageId: string }>(`/api/shares/${token}/prepare`, {
      method: "POST",
    }),
};
