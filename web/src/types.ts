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
  formulaFields: Array<{ key: string; label: string }>;
}

export interface CatalogProvider {
  name: string;
  label: string;
  pairs: CatalogPair[];
}

export interface User {
  telegramId: number;
  username: string;
  firstName: string;
}

export interface RateOperand {
  kind: "rate";
  provider: string;
  symbol: string;
  field: string;
}

export interface ConstantOperand {
  kind: "constant";
  value: string;
}

export type FormulaOperand = RateOperand | ConstantOperand;

export interface FormulaDefinition {
  id: string;
  title: string;
  left: RateOperand;
  operator: "+" | "-" | "*" | "/";
  right: FormulaOperand;
  adjustmentPercent: string | null;
  precision: number;
  enabled: boolean;
  sortOrder: number;
  updatedAt?: string | null;
}

export interface BrandingSettings {
  appLogoUrl: string | null;
  appUpdatedAt?: string | null;
  sourceLogos: Record<
    string,
    { url: string | null; updatedAt?: string | null }
  >;
}

export type CalculationShareMode = "full" | "hundredths";

export type CalculatorMode = "legacy" | "tape";

export interface AppSettings {
  calculatorMode: CalculatorMode;
  rateAlertsEnabled?: boolean;
  updatedAt?: string | null;
}

export interface CalculationStep {
  operator: "+" | "-" | "*" | "/";
  operand: string;
  subtotal: string;
  percentage?: boolean;
}

export interface CalculationResult {
  expression: string;
  result: string;
  steps: CalculationStep[];
}

export interface TapeShareEntry {
  operator: "+" | "-" | "*" | "/";
  value: string;
  percentage?: boolean;
  label?: string;
}

export interface CalculationTapeShare {
  title: string;
  entries: TapeShareEntry[];
}

export type ThemeChoice = "system" | "light" | "dark";
export type TabId = "rates" | "calculated" | "calculator" | "settings";
