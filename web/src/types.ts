export type RateLabel = "value" | "buy" | "sell" | string;

export interface RateValue {
  label: RateLabel;
  amount: string;
}

export interface RateSnapshot {
  key: string;
  kind: "subscription" | "calculated";
  source: string;
  pair: string;
  values: RateValue[];
  formula?: string | null;
  details: string[];
  fetchedAt: string;
  status: "fresh" | "stale" | "error";
  error?: string | null;
}

export interface Subscription {
  id: string;
  provider: string;
  symbol: string;
}

export interface CatalogPair {
  symbol: string;
  label: string;
  subscribed: boolean;
}

export interface CatalogProvider {
  name: string;
  pairs: CatalogPair[];
}

export interface User {
  telegramId: number;
  username: string;
  firstName: string;
}

export type ThemeChoice = "system" | "light" | "dark";
export type TabId = "rates" | "calculated" | "calculator" | "settings";
