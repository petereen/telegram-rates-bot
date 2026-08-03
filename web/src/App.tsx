import {
  Calculator,
  Check,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  CircleHelp,
  Eye,
  EyeOff,
  Image as ImageIcon,
  Moon,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings,
  Share2,
  SlidersHorizontal,
  Sun,
  Trash2,
  Upload,
  WalletCards,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { FormEvent } from "react";
import { api, setAccessToken } from "./api";
import { TapeCalculatorPage } from "./TapeCalculator";
import {
  getTelegramInitData,
  getTelegramWebApp,
  haptic,
  isTelegramLaunch,
  sharePreparedMessage,
} from "./telegram";
import type {
  BrandingSettings,
  AppSettings,
  CalculationResult,
  CalculationTapeShare,
  CalculatorMode,
  CalculationShareMode,
  CatalogProvider,
  FormulaDefinition,
  FormulaOperand,
  RateSnapshot,
  Subscription,
  TabId,
  ThemeChoice,
  User,
} from "./types";

const AUTO_REFRESH_MS = 5 * 60 * 1000;
const LONG_PRESS_MS = 500;

const TABS: Array<{
  id: TabId;
  label: string;
  icon: typeof WalletCards;
}> = [
  { id: "rates", label: "Ханш", icon: WalletCards },
  { id: "calculated", label: "Тооцоолсон", icon: SlidersHorizontal },
  { id: "calculator", label: "Тооны машин", icon: Calculator },
  { id: "settings", label: "Тохиргоо", icon: Settings },
];

function formatTime(value: string): string {
  try {
    return new Intl.DateTimeFormat("mn-MN", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Asia/Ulaanbaatar",
    }).format(new Date(value));
  } catch {
    return "—";
  }
}

function rateLabel(label: string): string {
  return { buy: "Авах", sell: "Зарах", value: "Ханш" }[label] || label;
}

function upsertRates(
  current: RateSnapshot[],
  incoming: RateSnapshot[],
): RateSnapshot[] {
  const next = new Map(current.map((item) => [item.key, item]));
  incoming.forEach((item) => next.set(item.key, item));
  return Array.from(next.values());
}

function LogoImage({
  src,
  alt,
  className = "source-logo",
}: {
  src?: string | null;
  alt: string;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  if (!src || failed) {
    return (
      <span className={`${className} logo-fallback`} aria-hidden="true">
        <ImageIcon size={14} />
      </span>
    );
  }
  return (
    <img
      className={className}
      src={src}
      alt={alt}
      onError={() => setFailed(true)}
    />
  );
}

function BrandMark({ src, className }: { src?: string | null; className: string }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  if (!src || failed) return <div className={className}>Ө</div>;
  return (
    <div className={`${className} has-image`}>
      <img src={src} alt="Апп лого" onError={() => setFailed(true)} />
    </div>
  );
}

interface RateRowsProps {
  rates: RateSnapshot[];
  sharing: boolean;
  selected: Set<string>;
  refreshing: Set<string>;
  onToggle(key: string): void;
  onBeginSelection(key: string): void;
  onRefresh(key: string): void;
  onShare(keys: string[]): void;
  sourceLogos: BrandingSettings["sourceLogos"];
}

function RateRows({
  rates,
  sharing,
  selected,
  refreshing,
  onToggle,
  onBeginSelection,
  onRefresh,
  onShare,
  sourceLogos,
}: RateRowsProps) {
  const pressTimers = useRef(new Map<string, number>());
  const pressStarts = useRef(new Map<string, { x: number; y: number }>());
  const suppressedClicks = useRef(new Set<string>());
  const groups = useMemo(() => {
    const result = new Map<string, RateSnapshot[]>();
    rates.forEach((rate) => {
      const group = rate.kind === "calculated" ? "Тооцоолсон ханш" : rate.source;
      result.set(group, [...(result.get(group) || []), rate]);
    });
    return Array.from(result.entries());
  }, [rates]);

  const cancelPress = (key: string) => {
    const timer = pressTimers.current.get(key);
    if (timer !== undefined) window.clearTimeout(timer);
    pressTimers.current.delete(key);
    pressStarts.current.delete(key);
  };

  useEffect(
    () => () => {
      pressTimers.current.forEach((timer) => window.clearTimeout(timer));
      pressTimers.current.clear();
      pressStarts.current.clear();
    },
    [],
  );

  return (
    <div className="rate-groups">
      {groups.map(([source, items]) => (
        <section className="ledger-group" key={source}>
          <div className="group-heading">
            <span>
              {source !== "Тооцоолсон ханш" && (
                <LogoImage
                  src={sourceLogos[source]?.url}
                  alt={`${source} лого`}
                />
              )}
              {source}
            </span>
            <span>{items.length.toString().padStart(2, "0")}</span>
          </div>
          {items.map((rate) => (
            <article
              className={`rate-row ${selected.has(rate.key) ? "is-selected" : ""}`}
              key={rate.key}
              onPointerDown={(event) => {
                if (
                  sharing ||
                  (event.target as HTMLElement).closest("button")
                ) return;
                pressStarts.current.set(rate.key, {
                  x: event.clientX,
                  y: event.clientY,
                });
                pressTimers.current.set(rate.key, window.setTimeout(() => {
                  suppressedClicks.current.add(rate.key);
                  onBeginSelection(rate.key);
                  cancelPress(rate.key);
                }, LONG_PRESS_MS));
              }}
              onPointerMove={(event) => {
                const start = pressStarts.current.get(rate.key);
                if (
                  start &&
                  Math.hypot(event.clientX - start.x, event.clientY - start.y) > 10
                ) cancelPress(rate.key);
              }}
              onPointerUp={() => cancelPress(rate.key)}
              onPointerCancel={() => cancelPress(rate.key)}
              onPointerLeave={() => cancelPress(rate.key)}
              onClick={() => {
                if (suppressedClicks.current.has(rate.key)) {
                  suppressedClicks.current.delete(rate.key);
                  return;
                }
                if (sharing) onToggle(rate.key);
              }}
            >
              {sharing && (
                <button
                  className="selection-box"
                  aria-label={`${rate.pair} сонгох`}
                  onClick={(event) => {
                    event.stopPropagation();
                    onToggle(rate.key);
                  }}
                >
                  {selected.has(rate.key) && <Check size={15} strokeWidth={2.5} />}
                </button>
              )}
              <div className="rate-copy">
                <div className="rate-title-line">
                  <strong>{rate.pair}</strong>
                  {rate.status !== "fresh" && (
                    <span className={`status-dot ${rate.status}`}>
                      {rate.status === "stale" ? "хуучин" : "алдаа"}
                    </span>
                  )}
                </div>
                {rate.formula && <p className="formula">{rate.formula}</p>}
                {rate.error && <p className="rate-error">{rate.error}</p>}
                <span className="timestamp">{formatTime(rate.fetchedAt)} шинэчлэгдсэн</span>
              </div>
              <div className="rate-values">
                {rate.values.map((value) => (
                  <div className="rate-value" key={`${rate.key}-${value.label}`}>
                    <span>{rateLabel(value.label)}</span>
                    <strong>{value.amount}</strong>
                  </div>
                ))}
              </div>
              {!sharing && (
                <div className="row-actions">
                  <button
                    aria-label="Шинэчлэх"
                    className="icon-button"
                    disabled={refreshing.has(rate.key)}
                    onClick={() => onRefresh(rate.key)}
                  >
                    <RefreshCw
                      size={17}
                      className={refreshing.has(rate.key) ? "spin" : ""}
                    />
                  </button>
                  <button
                    aria-label="Хуваалцах"
                    className="icon-button"
                    onClick={() => onShare([rate.key])}
                  >
                    <Share2 size={17} />
                  </button>
                </div>
              )}
            </article>
          ))}
        </section>
      ))}
    </div>
  );
}

interface ManageSheetProps {
  open: boolean;
  catalog: CatalogProvider[];
  subscriptions: Subscription[];
  onClose(): void;
  onChanged(): Promise<void>;
  notify(message: string, error?: boolean): void;
  sourceLogos: BrandingSettings["sourceLogos"];
}

function ManageSheet({
  open,
  catalog,
  subscriptions,
  onClose,
  onChanged,
  notify,
  sourceLogos,
}: ManageSheetProps) {
  const [query, setQuery] = useState("");
  const [providerFilter, setProviderFilter] = useState("Бүгд");
  const [busy, setBusy] = useState<string | null>(null);
  const subscriptionsByKey = useMemo(
    () =>
      new Map(
        subscriptions.map((item) => [
          `${item.provider}:${item.symbol}`,
          item,
        ]),
      ),
    [subscriptions],
  );
  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return catalog
      .filter(
        (provider) =>
          providerFilter === "Бүгд" || provider.name === providerFilter,
      )
      .map((provider) => ({
        ...provider,
        pairs: provider.pairs.filter(
          (pair) =>
            !normalized ||
                  `${provider.name} ${provider.label} ${pair.symbol} ${pair.label}`
              .toLowerCase()
              .includes(normalized),
        ),
      }))
      .filter((provider) => provider.pairs.length);
  }, [catalog, providerFilter, query]);

  if (!open) return null;

  const toggle = async (provider: string, symbol: string) => {
    const key = `${provider}:${symbol}`;
    setBusy(key);
    try {
      const existing = subscriptionsByKey.get(key);
      if (existing) await api.unsubscribe(existing.id);
      else await api.subscribe(provider, symbol);
      haptic("success");
      await onChanged();
    } catch (error) {
      notify(error instanceof Error ? error.message : "Алдаа гарлаа", true);
    } finally {
      setBusy(null);
    }
  };

  const clear = async () => {
    if (!window.confirm("Хадгалсан бүх ханшийг хасах уу?")) return;
    setBusy("clear");
    try {
      await api.clearSubscriptions();
      await onChanged();
      notify("Хадгалсан ханшуудыг цэвэрлэлээ");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Алдаа гарлаа", true);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="sheet-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label="Ханш тохируулах"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="sheet-handle" />
        <header className="sheet-header">
          <div>
            <span className="eyebrow">ЖАГСААЛТ</span>
            <h2>Ханш нэмэх</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Хаах">
            <X size={20} />
          </button>
        </header>
        <label className="search-field">
          <Search size={18} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Эх сурвалж эсвэл хослол хайх"
            autoFocus
          />
        </label>
        <div className="filter-strip">
          {[
            { name: "Бүгд", label: "Бүгд" },
            ...catalog.map((item) => ({ name: item.name, label: item.label })),
          ].map(({ name, label }) => (
            <button
              key={name}
              className={providerFilter === name ? "active" : ""}
              onClick={() => setProviderFilter(name)}
            >
              {name !== "Бүгд" && (
                <LogoImage
                  src={sourceLogos[name]?.url}
                  alt={`${name} лого`}
                />
              )}
              {label}
            </button>
          ))}
        </div>
        <div className="catalog-list">
          {filtered.map((provider) => (
            <section key={provider.name}>
              <div className="catalog-provider">
                <LogoImage
                  src={sourceLogos[provider.name]?.url}
                  alt={`${provider.name} лого`}
                />
                {provider.label}
              </div>
              {provider.pairs.map((pair) => {
                const key = `${provider.name}:${pair.symbol}`;
                const checked = subscriptionsByKey.has(key);
                return (
                  <button
                    className="catalog-row"
                    key={key}
                    disabled={busy === key}
                    onClick={() => toggle(provider.name, pair.symbol)}
                  >
                    <span>
                      <strong>{pair.symbol}</strong>
                      <small>{pair.label}</small>
                    </span>
                    <span className={`toggle ${checked ? "checked" : ""}`}>
                      {checked && <Check size={14} />}
                    </span>
                  </button>
                );
              })}
            </section>
          ))}
        </div>
        {subscriptions.length > 0 && (
          <button
            className="danger-button"
            disabled={busy === "clear"}
            onClick={clear}
          >
            <Trash2 size={17} />
            Бүх хадгалсан ханшийг цэвэрлэх
          </button>
        )}
      </section>
    </div>
  );
}

interface CalculatorPageProps {
  availableRates: RateSnapshot[];
  onShare(
    tokens: Array<string | number>,
    mode: CalculationShareMode,
  ): void;
  notify(message: string, error?: boolean): void;
  sourceLogos: BrandingSettings["sourceLogos"];
  tokens: Array<string | number>;
  setTokens: React.Dispatch<React.SetStateAction<Array<string | number>>>;
  result: CalculationResult | null;
  setResult: React.Dispatch<React.SetStateAction<CalculationResult | null>>;
}

function LegacyCalculatorPage({
  availableRates,
  onShare,
  notify,
  sourceLogos,
  tokens,
  setTokens,
  result,
  setResult,
}: CalculatorPageProps) {
  const [picker, setPicker] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<RateSnapshot[] | null>(null);
  const [searching, setSearching] = useState(false);
  const searchSequence = useRef(0);
  const [busy, setBusy] = useState(false);

  const appendDigit = (digit: string) => {
    setResult(null);
    setTokens((current) => {
      const last = current.at(-1);
      if (
        typeof last === "string" &&
        !["+", "-", "*", "/"].includes(last) &&
        !last.endsWith("%")
      ) {
        if (digit === "." && last.includes(".")) return current;
        return [...current.slice(0, -1), `${last}${digit}`];
      }
      return [...current, digit === "." ? "0." : digit];
    });
  };

  const appendOperator = (operator: string) => {
    setResult(null);
    setTokens((current) => {
      if (!current.length) return current;
      const last = current.at(-1);
      if (typeof last === "string" && ["+", "-", "*", "/"].includes(last)) {
        return [...current.slice(0, -1), operator];
      }
      return [...current, operator];
    });
  };

  const calculate = async () => {
    if (!tokens.length) return;
    setBusy(true);
    try {
      setResult(await api.calculate(tokens));
      haptic("success");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Тооцоолох боломжгүй", true);
    } finally {
      setBusy(false);
    }
  };

  const closePicker = () => {
    setPicker(false);
    setSearchQuery("");
    setSearchResults(null);
    setSearching(false);
  };

  const chooseRate = (amount: string) => {
    setTokens((current) => [...current, amount]);
    setResult(null);
    closePicker();
    haptic();
  };

  useEffect(() => {
    if (!picker) return;
    const query = searchQuery.trim();
    if (!query) {
      setSearchResults(null);
      setSearching(false);
      return;
    }

    const sequence = ++searchSequence.current;
    const timer = window.setTimeout(() => {
      setSearching(true);
      void api.searchRates(query)
        .then((data) => {
          if (sequence !== searchSequence.current) return;
          const normalized = query.toLowerCase();
          const matchingCalculated = availableRates.filter(
            (rate) =>
              rate.kind === "calculated" &&
              `${rate.source} ${rate.pair} ${rate.formula || ""}`
                .toLowerCase()
                .includes(normalized),
          );
          setSearchResults(upsertRates(data.rates, matchingCalculated));
        })
        .catch(() => {
          if (sequence === searchSequence.current) setSearchResults([]);
        })
        .finally(() => {
          if (sequence === searchSequence.current) setSearching(false);
        });
    }, 300);

    return () => window.clearTimeout(timer);
  }, [availableRates, picker, searchQuery]);

  const pickerRates = searchQuery.trim() ? searchResults || [] : availableRates;

  return (
    <div className="page calculator-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">ХАНШТАЙ ТООЦООЛОХ</span>
          <h1>Тооны машин</h1>
        </div>
      </header>
      <section className="calculator-shell">
        <div className="expression-display">
          <span>ИЛЭРХИЙЛЭЛ</span>
          <div>{tokens.length ? tokens.join(" ").replaceAll("*", "×").replaceAll("/", "÷") : "0"}</div>
          {result && (
            <strong>
              = <code>{result.result}</code>
            </strong>
          )}
        </div>
        <button className="rate-picker-button" onClick={() => setPicker(true)}>
          <WalletCards size={18} />
          Ханш сонгож оруулах
          <ChevronRight size={18} />
        </button>
        <div className="percent-strip">
          {["+0.5%", "+1%", "-1%"].map((value) => (
            <button key={value} onClick={() => setTokens((items) => [...items, value])}>
              {value}
            </button>
          ))}
        </div>
        <div className="keypad">
          {["7", "8", "9", "/", "4", "5", "6", "*", "1", "2", "3", "-", "0", ".", "⌫", "+"].map(
            (key) => (
              <button
                key={key}
                className={["/", "*", "-", "+"].includes(key) ? "operator" : ""}
                onClick={() => {
                  if (key === "⌫") setTokens((items) => items.slice(0, -1));
                  else if (["/", "*", "-", "+"].includes(key)) appendOperator(key);
                  else appendDigit(key);
                }}
              >
                {key === "*" ? "×" : key === "/" ? "÷" : key}
              </button>
            ),
          )}
          <button
            className="clear-key"
            onClick={() => {
              setTokens([]);
              setResult(null);
            }}
          >
            Цэвэрлэх
          </button>
          <button className="equals-key" disabled={busy} onClick={calculate}>
            =
          </button>
        </div>
        {result && (
          <div className="calculation-share-actions">
            <button
              className="primary-button"
              onClick={() => onShare(tokens, "full")}
            >
              <Send size={17} />
              Бүтэн дүн
            </button>
            <button
              className="secondary-button"
              onClick={() => onShare(tokens, "hundredths")}
            >
              <Send size={17} />
              2 орны дүн
            </button>
          </div>
        )}
      </section>
      {picker && (
        <div className="sheet-backdrop" onMouseDown={closePicker}>
          <section
            className="sheet rate-picker-sheet"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="sheet-handle" />
            <header className="sheet-header">
              <div>
                <span className="eyebrow">ОРЛУУЛАХ УТГА</span>
                <h2>Ханш сонгох</h2>
              </div>
              <button className="icon-button" onClick={closePicker} aria-label="Хаах">
                <X size={20} />
              </button>
            </header>
            <div className="picker-search">
              <Search size={17} />
              <input
                autoFocus
                value={searchQuery}
                placeholder="Бүх эх сурвалжаас хайх"
                onChange={(event) => setSearchQuery(event.target.value)}
                aria-label="Ханш хайх"
              />
              {searchQuery && (
                <button
                  type="button"
                  className="picker-search-clear"
                  onClick={() => setSearchQuery("")}
                  aria-label="Хайлтыг цэвэрлэх"
                >
                  <X size={15} />
                </button>
              )}
            </div>
            <p className="picker-caption">
              {searchQuery.trim() ? "Бүх эх сурвалж" : "Миний хадгалсан ханш"}
            </p>
            <div className="picker-list">
              {searching ? (
                <p className="picker-empty">Хайж байна…</p>
              ) : pickerRates
                .filter((rate) => rate.values.length)
                .map((rate) => (
                  <div className="picker-row" key={rate.key}>
                    <span>
                      <strong>{rate.pair}</strong>
                      <small>
                        {rate.kind === "subscription" && (
                          <LogoImage
                            src={sourceLogos[rate.source]?.url}
                            alt={`${rate.source} лого`}
                          />
                        )}
                        {rate.source}
                      </small>
                    </span>
                    <div>
                      {rate.values.map((value) => (
                        <button
                          key={value.label}
                          onClick={() => chooseRate(value.amount)}
                        >
                          <small>{rateLabel(value.label)}</small>
                          {value.amount}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              {!searching &&
                !pickerRates.some((rate) => rate.values.length) && (
                  <p className="picker-empty">
                    {searchQuery.trim()
                      ? "Тохирох ханш олдсонгүй"
                      : "Хадгалсан ханш алга. Дээрх хайлтаар бүх эх сурвалжаас хайна уу."}
                  </p>
                )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

type FormulaDraft = Omit<
  FormulaDefinition,
  "id" | "sortOrder" | "updatedAt"
>;

interface FormulaRateOption {
  key: string;
  label: string;
  operand: {
    kind: "rate";
    provider: string;
    symbol: string;
    field: string;
  };
}

function FormulaManager({
  open,
  formulas,
  catalog,
  onClose,
  onChanged,
  notify,
}: {
  open: boolean;
  formulas: FormulaDefinition[];
  catalog: CatalogProvider[];
  onClose(): void;
  onChanged(): Promise<void>;
  notify(message: string, error?: boolean): void;
}) {
  const options = useMemo<FormulaRateOption[]>(
    () =>
      catalog.flatMap((provider) =>
        provider.pairs.flatMap((pair) =>
          (pair.formulaFields || []).map((field) => ({
            key: `${provider.name}\u001f${pair.symbol}\u001f${field.key}`,
            label: `${provider.label} · ${pair.symbol} · ${field.label}`,
            operand: {
              kind: "rate" as const,
              provider: provider.name,
              symbol: pair.symbol,
              field: field.key,
            },
          })),
        ),
      ),
    [catalog],
  );
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<FormulaDraft | null>(null);
  const [busy, setBusy] = useState(false);

  const startNew = () => {
    if (!options.length) return;
    setEditingId(null);
    setDraft({
      title: "",
      left: options[0].operand,
      operator: "*",
      right: { kind: "constant", value: "1" },
      adjustmentPercent: null,
      precision: 2,
      enabled: true,
    });
  };

  const startEdit = (formula: FormulaDefinition) => {
    setEditingId(formula.id);
    setDraft({
      title: formula.title,
      left: formula.left,
      operator: formula.operator,
      right: formula.right,
      adjustmentPercent: formula.adjustmentPercent,
      precision: formula.precision,
      enabled: formula.enabled,
    });
  };

  const chooseRate = (key: string) =>
    options.find((option) => option.key === key)?.operand;
  const operandKey = (operand: FormulaOperand) =>
    operand.kind === "rate"
      ? `${operand.provider}\u001f${operand.symbol}\u001f${operand.field}`
      : "";
  const operandLabel = (operand: FormulaOperand) => {
    if (operand.kind === "constant") return operand.value || "—";
    return (
      options.find((option) => option.key === operandKey(operand))?.label ||
      `${operand.provider} · ${operand.symbol} · ${operand.field}`
    );
  };
  const draftPreview = draft
    ? [
        operandLabel(draft.left),
        { "*": "×", "/": "÷", "+": "+", "-": "−" }[draft.operator],
        operandLabel(draft.right),
        draft.adjustmentPercent
          ? `${Number(draft.adjustmentPercent) > 0 ? "+" : ""}${draft.adjustmentPercent}%`
          : "",
      ]
        .filter(Boolean)
        .join(" ")
    : "";

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    try {
      if (editingId) await api.updateFormula(editingId, draft);
      else await api.createFormula(draft);
      await onChanged();
      setDraft(null);
      setEditingId(null);
      notify("Томьёог хадгаллаа");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Томьёо хадгалах боломжгүй", true);
    } finally {
      setBusy(false);
    }
  };

  const updateExisting = async (
    formula: FormulaDefinition,
    changes: Partial<FormulaDraft>,
  ) => {
    setBusy(true);
    try {
      await api.updateFormula(formula.id, {
        title: formula.title,
        left: formula.left,
        operator: formula.operator,
        right: formula.right,
        adjustmentPercent: formula.adjustmentPercent,
        precision: formula.precision,
        enabled: formula.enabled,
        ...changes,
      });
      await onChanged();
    } catch (error) {
      notify(error instanceof Error ? error.message : "Томьёо шинэчлэх боломжгүй", true);
    } finally {
      setBusy(false);
    }
  };

  const move = async (index: number, direction: -1 | 1) => {
    const destination = index + direction;
    if (destination < 0 || destination >= formulas.length) return;
    const ids = formulas.map((formula) => formula.id);
    [ids[index], ids[destination]] = [ids[destination], ids[index]];
    setBusy(true);
    try {
      await api.orderFormulas(ids);
      await onChanged();
    } catch (error) {
      notify(error instanceof Error ? error.message : "Дараалал хадгалах боломжгүй", true);
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  return (
    <div className="sheet-backdrop" onMouseDown={onClose}>
      <section
        className="sheet formula-manager-sheet"
        role="dialog"
        aria-modal="true"
        aria-label="Томьёо тохируулах"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="sheet-handle" />
        <header className="sheet-header">
          <div>
            <span className="eyebrow">ГЛОБАЛ ТОХИРГОО</span>
            <h2>Томьёо тохируулах</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Хаах">
            <X size={20} />
          </button>
        </header>
        <div className="formula-manager-body">
          {!draft ? (
            <>
              <button
                className="primary-button formula-add-button"
                onClick={startNew}
                disabled={!options.length || busy}
              >
                <Plus size={17} />
                Шинэ томьёо
              </button>
              <div className="formula-definition-list">
                {formulas.map((formula, index) => (
                  <article
                    className={`formula-definition-row ${formula.enabled ? "" : "disabled"}`}
                    key={formula.id}
                  >
                    <div>
                      <strong>{formula.title}</strong>
                      <small>
                        {formula.left.provider} {formula.left.symbol}{" "}
                        {formula.operator === "*" ? "×" : formula.operator === "/" ? "÷" : formula.operator}{" "}
                        {formula.right.kind === "constant"
                          ? formula.right.value
                          : `${formula.right.provider} ${formula.right.symbol}`}
                        {formula.adjustmentPercent
                          ? ` · ${Number(formula.adjustmentPercent) > 0 ? "+" : ""}${formula.adjustmentPercent}%`
                          : ""}
                      </small>
                    </div>
                    <div className="formula-row-actions">
                      <button
                        className="icon-button"
                        aria-label="Дээш"
                        disabled={busy || index === 0}
                        onClick={() => void move(index, -1)}
                      >
                        <ChevronUp size={16} />
                      </button>
                      <button
                        className="icon-button"
                        aria-label="Доош"
                        disabled={busy || index === formulas.length - 1}
                        onClick={() => void move(index, 1)}
                      >
                        <ChevronDown size={16} />
                      </button>
                      <button
                        className="icon-button"
                        aria-label="Засах"
                        disabled={busy}
                        onClick={() => startEdit(formula)}
                      >
                        <Pencil size={16} />
                      </button>
                      <button
                        className={`compact-toggle ${formula.enabled ? "active" : ""}`}
                        disabled={busy}
                        onClick={() =>
                          void updateExisting(formula, { enabled: !formula.enabled })
                        }
                      >
                        {formula.enabled ? "Идэвхтэй" : "Унтраасан"}
                      </button>
                      <button
                        className="icon-button danger-icon"
                        aria-label="Устгах"
                        disabled={busy}
                        onClick={() => {
                          if (!window.confirm(`“${formula.title}” томьёог устгах уу?`)) return;
                          setBusy(true);
                          void api
                            .deleteFormula(formula.id)
                            .then(onChanged)
                            .catch((error) =>
                              notify(
                                error instanceof Error ? error.message : "Устгах боломжгүй",
                                true,
                              ),
                            )
                            .finally(() => setBusy(false));
                        }}
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </>
          ) : (
            <>
              <div className="formula-draft-preview" aria-live="polite">
                <span>Одоогийн томьёо</span>
                <output>{draftPreview}</output>
              </div>
              <div className="formula-editor">
                <label>
                  <span>Нэр</span>
                  <input
                    maxLength={80}
                    value={draft.title}
                    onChange={(event) =>
                      setDraft({ ...draft, title: event.target.value })
                    }
                  />
                </label>
                <label>
                  <span>Ханш</span>
                  <select
                    value={operandKey(draft.left)}
                    onChange={(event) => {
                      const selected = chooseRate(event.target.value);
                      if (selected) setDraft({ ...draft, left: selected });
                    }}
                  >
                    {options.map((option) => (
                      <option key={option.key} value={option.key}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Үйлдэл</span>
                  <select
                    value={draft.operator}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        operator: event.target.value as FormulaDraft["operator"],
                      })
                    }
                  >
                    <option value="+">+</option>
                    <option value="-">−</option>
                    <option value="*">×</option>
                    <option value="/">÷</option>
                  </select>
                </label>
                <label>
                  <span>Утгын төрөл</span>
                  <select
                    value={draft.right.kind}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        right:
                          event.target.value === "constant"
                            ? { kind: "constant", value: "1" }
                            : options[0].operand,
                      })
                    }
                  >
                    <option value="constant">Тогтмол тоо</option>
                    <option value="rate">Ханш</option>
                  </select>
                </label>
                {draft.right.kind === "constant" ? (
                  <label>
                    <span>Тогтмол утга</span>
                    <input
                      inputMode="decimal"
                      value={draft.right.value}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          right: { kind: "constant", value: event.target.value },
                        })
                      }
                    />
                  </label>
                ) : (
                  <label>
                    <span>Баруун ханш</span>
                    <select
                      value={operandKey(draft.right)}
                      onChange={(event) => {
                        const selected = chooseRate(event.target.value);
                        if (selected) setDraft({ ...draft, right: selected });
                      }}
                    >
                      {options.map((option) => (
                        <option key={option.key} value={option.key}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <div className="formula-editor-grid">
                  <label>
                    <span>Нэмэлт хувь, %</span>
                    <input
                      inputMode="decimal"
                      placeholder="Ж: 1 эсвэл -0.5"
                      value={draft.adjustmentPercent || ""}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          adjustmentPercent: event.target.value || null,
                        })
                      }
                    />
                  </label>
                  <label>
                    <span>Бүхэлдэх аравтын орон</span>
                    <input
                      type="number"
                      min={0}
                      max={8}
                      value={draft.precision}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          precision: Number(event.target.value),
                        })
                      }
                    />
                  </label>
                </div>
                <label className="formula-enabled">
                  <input
                    type="checkbox"
                    checked={draft.enabled}
                    onChange={(event) =>
                      setDraft({ ...draft, enabled: event.target.checked })
                    }
                  />
                  <span>Идэвхтэй</span>
                </label>
                <div className="formula-editor-actions">
                  <button
                    className="secondary-button"
                    onClick={() => {
                      setDraft(null);
                      setEditingId(null);
                    }}
                  >
                    Болих
                  </button>
                  <button
                    className="primary-button"
                    disabled={busy || !draft.title.trim()}
                    onClick={() => void save()}
                  >
                    Хадгалах
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}

interface SettingsPageProps {
  user: User;
  theme: ThemeChoice;
  subscriptionCount: number;
  catalog: CatalogProvider[];
  branding: BrandingSettings;
  calculatorMode: CalculatorMode;
  calculatorModeBusy: boolean;
  adminIds: number[];
  adminIdsBusy: boolean;
  onTheme(theme: ThemeChoice): void;
  onManage(): void;
  onBranding(branding: BrandingSettings): void;
  onCalculatorMode(mode: CalculatorMode): void;
  onAdminIds(adminIds: number[]): void;
  notify(message: string, error?: boolean): void;
  onLogout(): void;
}

function SettingsPage({
  user,
  theme,
  subscriptionCount,
  catalog,
  branding,
  calculatorMode,
  calculatorModeBusy,
  adminIds,
  adminIdsBusy,
  onTheme,
  onManage,
  onBranding,
  onCalculatorMode,
  onAdminIds,
  notify,
  onLogout,
}: SettingsPageProps) {
  const [helpOpen, setHelpOpen] = useState(false);
  const [brandingOpen, setBrandingOpen] = useState(false);
  const [brandingBusy, setBrandingBusy] = useState<string | null>(null);
  const [adminIdsDraft, setAdminIdsDraft] = useState(adminIds.join(", "));

  const upload = async (file: File, provider?: string) => {
    setBrandingBusy(provider || "app");
    try {
      const next = provider
        ? await api.uploadSourceLogo(provider, file)
        : await api.uploadAppLogo(file);
      onBranding(next);
      notify("Лого шинэчлэгдлээ");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Лого оруулах боломжгүй", true);
    } finally {
      setBrandingBusy(null);
    }
  };

  const remove = async (provider?: string) => {
    setBrandingBusy(provider || "app");
    try {
      const next = provider
        ? await api.deleteSourceLogo(provider)
        : await api.deleteAppLogo();
      onBranding(next);
      notify("Лого устгагдлаа");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Лого устгах боломжгүй", true);
    } finally {
      setBrandingBusy(null);
    }
  };
  return (
    <div className="page settings-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">ХУВИЙН ТОХИРГОО</span>
          <h1>Тохиргоо</h1>
        </div>
      </header>
      <section className="settings-section">
        <div className="profile-line">
          <div className="avatar">
            {(user.firstName || user.username || "Х").slice(0, 1).toUpperCase()}
          </div>
          <div>
            <strong>{user.firstName || "Telegram хэрэглэгч"}</strong>
            <span>@{user.username || user.telegramId}</span>
          </div>
          <span className="access-badge">API KEY</span>
        </div>
      </section>
      {adminIds.includes(user.telegramId) && (
      <section className="settings-section">
        <span className="settings-label">ГЛОБАЛ АДМИНУУД</span>
        <p className="settings-hint">Whitelist удирдах Telegram ID-ууд. Бүх хэрэглэгчид үйлчилнэ.</p>
        <input
          className="settings-input"
          aria-label="Админ Telegram ID"
          value={adminIdsDraft}
          disabled={adminIdsBusy}
          onChange={(event) => setAdminIdsDraft(event.target.value)}
          placeholder="1447446407, 1932946217"
        />
        <button
          className="primary-button"
          disabled={adminIdsBusy}
          onClick={() => {
            const values = adminIdsDraft
              .split(",")
              .map((value) => Number(value.trim()))
              .filter((value) => Number.isInteger(value) && value > 0);
            onAdminIds([...new Set(values)]);
          }}
        >
          Хадгалах
        </button>
      </section>
      )}
      <section className="settings-section">
        <span className="settings-label">ХАРАГДАЦ</span>
        <div className="theme-control">
          {([
            ["system", "Систем", SlidersHorizontal],
            ["light", "Цайвар", Sun],
            ["dark", "Бараан", Moon],
          ] as const).map(([value, label, Icon]) => (
            <button
              key={value}
              className={theme === value ? "active" : ""}
              onClick={() => onTheme(value)}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </div>
      </section>
      <section className="settings-section">
        <span className="settings-label">ГЛОБАЛ ТООНЫ МАШИН</span>
        <p className="settings-hint">
          Энэ сонголт бүх хэрэглэгчид үйлчилнэ.
        </p>
        <div className="theme-control" role="group" aria-label="Тооны машины горим">
          {([[
            "legacy",
            "Хуучин",
          ], [
            "tape",
            "Тууз",
          ]] as const).map(([value, label]) => (
            <button
              key={value}
              className={calculatorMode === value ? "active" : ""}
              disabled={calculatorModeBusy}
              aria-pressed={calculatorMode === value}
              onClick={() => onCalculatorMode(value)}
            >
              <Calculator size={16} />
              {label}
            </button>
          ))}
        </div>
      </section>
      <section className="settings-section">
        <button
          className="settings-disclosure"
          onClick={() => setBrandingOpen((value) => !value)}
        >
          <span>
            <ImageIcon size={19} />
            Лого
          </span>
          <ChevronRight
            size={17}
            className={brandingOpen ? "chevron-open" : ""}
          />
        </button>
        {brandingOpen && (
          <div className="branding-manager">
            <p>
              Энд хийсэн өөрчлөлт API key-ээр нэвтэрсэн бүх хэрэглэгчид харагдана.
            </p>
            <div className="branding-row">
              <BrandMark src={branding.appLogoUrl} className="branding-preview" />
              <strong>Апп лого</strong>
              <label className="upload-button">
                <Upload size={15} />
                Солих
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  disabled={brandingBusy === "app"}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) void upload(file);
                    event.target.value = "";
                  }}
                />
              </label>
              {branding.appLogoUrl && (
                <button
                  className="icon-button danger-icon"
                  aria-label="Апп лого устгах"
                  disabled={brandingBusy === "app"}
                  onClick={() => void remove()}
                >
                  <Trash2 size={16} />
                </button>
              )}
            </div>
            {catalog.map((provider) => (
              <div className="branding-row" key={provider.name}>
                <LogoImage
                  src={branding.sourceLogos[provider.name]?.url}
                  alt={`${provider.name} лого`}
                  className="branding-preview"
                />
                <strong>{provider.label}</strong>
                <label className="upload-button">
                  <Upload size={15} />
                  Солих
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    disabled={brandingBusy === provider.name}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) void upload(file, provider.name);
                      event.target.value = "";
                    }}
                  />
                </label>
                {branding.sourceLogos[provider.name]?.url && (
                  <button
                    className="icon-button danger-icon"
                    aria-label={`${provider.name} лого устгах`}
                    disabled={brandingBusy === provider.name}
                    onClick={() => void remove(provider.name)}
                  >
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
      <section className="settings-section settings-links">
        <button onClick={onManage}>
          <span>
            <WalletCards size={19} />
            Хадгалсан ханш
          </span>
          <span>
            {subscriptionCount}
            <ChevronRight size={17} />
          </span>
        </button>
        <button onClick={() => setHelpOpen((value) => !value)}>
          <span>
            <CircleHelp size={19} />
            Тусламж
          </span>
          <ChevronRight
            size={17}
            className={helpOpen ? "chevron-open" : ""}
          />
        </button>
        {helpOpen && (
          <div className="help-copy">
            <p>
              “Ханш” хэсгээс валют нэмээд мөрийн хуваалцах товчоор нэг ханш,
              эсвэл дээд талын “Хуваалцах” горимоор хэд хэдэн ханш сонгоно.
            </p>
            <p>
              “Тооны машин”-д хадгалсан ханшаас утга оруулж +, −, ×, ÷ болон
              хувийн тооцоо хийнэ.
            </p>
          </div>
        )}
      </section>
      {!isTelegramLaunch() && (
        <button className="secondary-button logout-button" onClick={onLogout}>
          Гарах
        </button>
      )}
      <p className="version-note">OYUNS RATES · 1.0.0</p>
    </div>
  );
}

export default function App() {
  const [authState, setAuthState] = useState<
    "loading" | "ready" | "api-key" | "telegram-login" | "telegram-error"
  >("loading");
  const [user, setUser] = useState<User | null>(null);
  const [tab, setTab] = useState<TabId>("rates");
  const [rates, setRates] = useState<RateSnapshot[]>([]);
  const [calculated, setCalculated] = useState<RateSnapshot[]>([]);
  const [formulas, setFormulas] = useState<FormulaDefinition[]>([]);
  const [catalog, setCatalog] = useState<CatalogProvider[]>([]);
  const [branding, setBranding] = useState<BrandingSettings>({
    appLogoUrl: null,
    sourceLogos: {},
  });
  const [appSettings, setAppSettings] = useState<AppSettings>({
    calculatorMode: "tape",
    adminIds: [],
  });
  const [calculatorModeBusy, setCalculatorModeBusy] = useState(false);
  const [adminIdsBusy, setAdminIdsBusy] = useState(false);
  const [legacyTokens, setLegacyTokens] = useState<Array<string | number>>([]);
  const [legacyResult, setLegacyResult] = useState<CalculationResult | null>(null);
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [manageOpen, setManageOpen] = useState(false);
  const [formulaManagerOpen, setFormulaManagerOpen] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [refreshing, setRefreshing] = useState<Set<string>>(new Set());
  const [loadingData, setLoadingData] = useState(true);
  const [calculatedLoaded, setCalculatedLoaded] = useState(false);
  const [toast, setToast] = useState<{ text: string; error: boolean } | null>(null);
  const [telegramError, setTelegramError] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [authError, setAuthError] = useState("");
  const [authSubmitting, setAuthSubmitting] = useState(false);
  const [theme, setTheme] = useState<ThemeChoice>(
    () => (localStorage.getItem("rates-theme") as ThemeChoice) || "system",
  );
  const dataLoadCount = useRef(0);

  const notify = useCallback((text: string, error = false) => {
    setToast({ text, error });
    window.setTimeout(() => setToast(null), 3200);
  }, []);

  const beginDataLoading = useCallback(() => {
    dataLoadCount.current += 1;
    setLoadingData(true);
    return () => {
      dataLoadCount.current -= 1;
      if (dataLoadCount.current === 0) setLoadingData(false);
    };
  }, []);

  const loadReferenceData = useCallback(async () => {
    const [catalogData, subscriptionData, formulaData, brandingData, settingsData] = await Promise.all([
      api.catalog(),
      api.subscriptions(),
      api.formulas(),
      api.branding(),
      api.settings(),
    ]);
    setCatalog(catalogData.providers);
    setSubscriptions(subscriptionData.subscriptions);
    setFormulas(formulaData.formulas);
    setBranding(brandingData);
    setAppSettings(settingsData);
  }, []);

  const loadRates = useCallback(async () => {
    const finishLoading = beginDataLoading();
    try {
      const rateData = await api.rates();
      setRates(rateData.rates);
    } finally {
      finishLoading();
    }
  }, [beginDataLoading]);

  const finishLogin = useCallback(
    (session: { user: User; accessToken?: string }) => {
      if (session.accessToken) setAccessToken(session.accessToken);
      setUser(session.user);
      setAuthState("ready");
      void Promise.all([loadReferenceData(), loadRates()]).catch((error) =>
        notify(
          error instanceof Error ? error.message : "Өгөгдөл ачаалахад алдаа гарлаа",
          true,
        ),
      );
    },
    [loadRates, loadReferenceData, notify],
  );

  const loadCalculated = useCallback(async () => {
    const finishLoading = beginDataLoading();
    try {
      const formulaData = await api.calculated();
      setCalculated(formulaData.rates);
      setCalculatedLoaded(true);
    } finally {
      finishLoading();
    }
  }, [beginDataLoading]);

  const bootstrap = useCallback(async () => {
    const initData = getTelegramInitData();
    if (!initData && isTelegramLaunch()) {
      // A real Mini App must provide signed launch data. Do not silently
      // fall back to browser OIDC when its BotFather launch is misconfigured.
      setAuthState("telegram-error");
      return;
    }
    try {
      const session = await api.me();
      finishLogin(session);
    } catch {
      setAuthState("api-key");
    }
  }, [finishLogin]);

  const submitApiKey = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      setAuthSubmitting(true);
      setAuthError("");
      try {
        const initData = getTelegramInitData();
        if (initData) {
          const session = await api.miniAppLogin(initData, apiKey.trim());
          finishLogin(session);
        } else {
          await api.apiKeyLogin(apiKey.trim());
          setAuthState("telegram-login");
        }
      } catch (error) {
        setAuthError(
          error instanceof Error ? error.message : "API key шалгахад алдаа гарлаа",
        );
      } finally {
        setAuthSubmitting(false);
      }
    },
    [apiKey, finishLogin],
  );

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    if (
      authState !== "ready" ||
      (tab !== "calculated" && tab !== "calculator") ||
      calculatedLoaded
    ) return;
    void loadCalculated().catch((error) =>
      notify(
        error instanceof Error ? error.message : "Томьёо ачаалахад алдаа гарлаа",
        true,
      ),
    );
  }, [authState, calculatedLoaded, loadCalculated, notify, tab]);

  useEffect(() => {
    localStorage.setItem("rates-theme", theme);
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.dataset.theme = theme;
  }, [theme]);

  const refresh = useCallback(
    async (keys: string[] = []) => {
      setRefreshing((current) => new Set([...current, ...(keys.length ? keys : ["all"])]));
      try {
        const result = await api.refresh(keys);
        setRates((current) =>
          upsertRates(
            current,
            result.rates.filter((rate) => rate.kind === "subscription"),
          ),
        );
        setCalculated((current) =>
          upsertRates(
            current,
            result.rates.filter((rate) => rate.kind === "calculated"),
          ),
        );
        haptic("success");
      } catch (error) {
        notify(error instanceof Error ? error.message : "Шинэчлэхэд алдаа гарлаа", true);
      } finally {
        setRefreshing((current) => {
          const next = new Set(current);
          (keys.length ? keys : ["all"]).forEach((key) => next.delete(key));
          return next;
        });
      }
    },
    [notify],
  );

  useEffect(() => {
    if (authState !== "ready") return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, AUTO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [authState, refresh]);

  useEffect(() => {
    if (authState !== "ready") return;
    const refreshSettings = () => {
      if (document.visibilityState !== "visible") return;
      void api.settings().then(setAppSettings).catch(() => undefined);
    };
    window.addEventListener("focus", refreshSettings);
    document.addEventListener("visibilitychange", refreshSettings);
    return () => {
      window.removeEventListener("focus", refreshSettings);
      document.removeEventListener("visibilitychange", refreshSettings);
    };
  }, [authState]);

  const changeCalculatorMode = async (mode: CalculatorMode) => {
    if (mode === appSettings.calculatorMode) return;
    setCalculatorModeBusy(true);
    try {
      setAppSettings(await api.setCalculatorMode(mode));
      notify(mode === "tape" ? "Туузан тооны машин идэвхжлээ" : "Энгийн тооны машин идэвхжлээ");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Горим солих боломжгүй", true);
    } finally {
      setCalculatorModeBusy(false);
    }
  };

  const changeAdminIds = async (adminIds: number[]) => {
    if (!adminIds.length) return;
    setAdminIdsBusy(true);
    try {
      setAppSettings(await api.setAdminIds(adminIds));
      notify("Админууд шинэчлэгдлээ");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Админууд шинэчлэх боломжгүй", true);
    } finally {
      setAdminIdsBusy(false);
    }
  };

  useEffect(() => {
    if (authState !== "ready" || !isTelegramLaunch()) return;
    const start = getTelegramWebApp()?.initDataUnsafe?.start_param;
    if (!start?.startsWith("share_")) return;
    const token = start.slice(6);
    void api
      .prepareBundle(token)
      .then(async ({ preparedMessageId }) => {
        const successful = await sharePreparedMessage(preparedMessageId);
        if (!successful) {
          getTelegramWebApp()?.switchInlineQuery?.(`_b:${token}`, [
            "users",
            "groups",
            "channels",
          ]);
        }
      })
      .catch((error) =>
        notify(error instanceof Error ? error.message : "Хуваалцах боломжгүй", true),
      );
  }, [authState, notify]);

  const afterSubscriptionsChanged = async () => {
    await Promise.all([loadReferenceData(), loadRates()]);
  };

  const afterFormulasChanged = async () => {
    const [formulaData, calculatedData] = await Promise.all([
      api.formulas(),
      api.calculated(),
    ]);
    setFormulas(formulaData.formulas);
    setCalculated(calculatedData.rates);
    setCalculatedLoaded(true);
  };

  const doShare = async (
    rateKeys: string[],
    calculationTokens?: Array<string | number>,
    calculationResultMode: CalculationShareMode = "full",
    calculationTape?: CalculationTapeShare,
  ) => {
    try {
      const share = calculationTape
        ? await api.share(
            rateKeys,
            calculationTokens,
            calculationResultMode,
            calculationTape,
          )
        : await api.share(rateKeys, calculationTokens, calculationResultMode);
      if (isTelegramLaunch()) {
        const successful = await sharePreparedMessage(share.preparedMessageId);
        const telegramApp = getTelegramWebApp();
        if (!successful && telegramApp?.switchInlineQuery) {
          telegramApp.switchInlineQuery(share.inlineQuery, [
            "users",
            "groups",
            "channels",
          ]);
        } else if (!successful && share.handoffUrl) {
          window.location.href = share.handoffUrl;
        }
      } else if (share.handoffUrl) {
        window.location.href = share.handoffUrl;
      } else {
        throw new Error("Telegram Mini App холбоос тохируулаагүй");
      }
      setSharing(false);
      setSelected(new Set());
    } catch (error) {
      notify(error instanceof Error ? error.message : "Хуваалцах боломжгүй", true);
      haptic("error");
    }
  };

  const toggleSelected = (key: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
    haptic();
  };

  const beginSelection = (key: string) => {
    setSharing(true);
    setSelected(new Set([key]));
    haptic("success");
  };

  useEffect(() => {
    const valid = new Set([...rates, ...calculated].map((rate) => rate.key));
    setSelected((current) => {
      const next = new Set(Array.from(current).filter((key) => valid.has(key)));
      return next.size === current.size ? current : next;
    });
  }, [rates, calculated]);

  if (authState === "loading") {
    return (
      <main className="center-state">
        <BrandMark src={branding.appLogoUrl} className="brand-mark" />
        <span>Ханш бэлдэж байна…</span>
      </main>
    );
  }

  if (authState === "api-key" || authState === "telegram-login") {
    const isBrowserLogin = authState === "telegram-login";
    return (
      <main className="login-page">
        <div className="login-rule" />
        <span className="eyebrow">OYUNS ALL-IN-ONE EXCHANGE LEDGER</span>
        <h1>Илүү хялбар.<br />Илүү хурдан.</h1>
        <p>API түлхүүр оруулна уу.</p>
        {!isBrowserLogin ? (
          <form className="api-key-form" onSubmit={submitApiKey}>
            <label htmlFor="app-api-key">API key</label>
            <div className="api-key-input-wrap">
              <input
                id="app-api-key"
                type={showApiKey ? "text" : "password"}
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder="API key оруулна уу"
                autoComplete="current-password"
                autoFocus
              />
              <button
                className="show-api-key"
                type="button"
                aria-label={showApiKey ? "API key нуух" : "API key харуулах"}
                title={showApiKey ? "API key нуух" : "API key харуулах"}
                onClick={() => setShowApiKey((visible) => !visible)}
              >
                {showApiKey ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            <button className="primary-button" type="submit" disabled={authSubmitting || !apiKey.trim()}>
              {authSubmitting ? "Шалгаж байна…" : "Нэвтрэх"}
            </button>
          </form>
        ) : (
          <a className="telegram-login" href="/api/auth/telegram/start">
            <Send size={19} />
            Telegram-аар нэвтрэх
          </a>
        )}
        {authError && <p className="auth-error">{authError}</p>}
        <small>
          {isBrowserLogin
            ? "API key зөв. Telegram бүртгэлээр үргэлжлүүлнэ үү."
            : "Апп ашиглахын тулд API key шаардлагатай."}
        </small>
      </main>
    );
  }

  if (authState === "telegram-error") {
    return (
      <main className="center-state denied">
        <div className="brand-mark">!</div>
        <h1>Telegram өгөгдөл ирсэнгүй</h1>
        <p>{telegramError || "Ботын Menu товч эсвэл Main Mini App холбоосоор дахин нээнэ үү."}</p>
        <button
          className="primary-button"
          onClick={() => {
            setTelegramError("");
            setAuthState("loading");
            void bootstrap();
          }}
        >
          Дахин оролдох
        </button>
      </main>
    );
  }

  const activeRates = tab === "calculated" ? calculated : rates;
  return (
    <div className="app-shell">
      <aside className="desktop-rail">
        <BrandMark src={branding.appLogoUrl} className="rail-brand" />
        <nav>
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={tab === id ? "active" : ""}
              onClick={() => setTab(id)}
            >
              <Icon size={19} />
              {label}
            </button>
          ))}
        </nav>
        <span className="rail-footer">UB · GMT+8</span>
      </aside>
      <main className="content">
        {(tab === "rates" || tab === "calculated") && (
          <div className="page rates-page">
            <header className="page-header">
              <div>
                <span className="eyebrow">
                  {tab === "rates" ? "МИНИЙ ЖАГСААЛТ" : "ГЛОБАЛ ТОМЬЁОНУУД"}
                </span>
                <h1>{tab === "rates" ? "Ханш" : "Тооцоолсон"}</h1>
              </div>
              <div className="header-actions">
                {tab === "rates" && (
                  <button className="icon-button bordered" onClick={() => setManageOpen(true)}>
                    <Plus size={19} />
                  </button>
                )}
                {tab === "calculated" && (
                  <button
                    className="icon-button bordered"
                    onClick={() => setFormulaManagerOpen(true)}
                    aria-label="Томьёо тохируулах"
                  >
                    <Pencil size={18} />
                  </button>
                )}
                <button
                  className="icon-button bordered"
                  disabled={refreshing.has("all")}
                  onClick={() => refresh()}
                >
                  <RefreshCw size={19} className={refreshing.has("all") ? "spin" : ""} />
                </button>
                <button
                  className={`text-button ${sharing ? "active" : ""}`}
                  onClick={() => {
                    setSharing((value) => !value);
                    setSelected(new Set());
                  }}
                >
                  <Share2 size={17} />
                  {sharing ? "Болих" : "Хуваалцах"}
                </button>
              </div>
            </header>
            {loadingData ? (
              <div className="loading-ledger">
                {[1, 2, 3].map((item) => <div key={item} />)}
              </div>
            ) : activeRates.length ? (
              <RateRows
                rates={activeRates}
                sharing={sharing}
                selected={selected}
                refreshing={refreshing}
                onToggle={toggleSelected}
                onBeginSelection={beginSelection}
                onRefresh={(key) => refresh([key])}
                onShare={(keys) => void doShare(keys)}
                sourceLogos={branding.sourceLogos}
              />
            ) : (
              <section className="empty-ledger">
                <span>00</span>
                <h2>
                  {tab === "rates" ? "Хадгалсан ханш алга" : "Идэвхтэй томьёо алга"}
                </h2>
                <p>
                  {tab === "rates"
                    ? "Өдөр бүр хардаг эх сурвалж, валютын хослолоо нэмнэ үү."
                    : "Шинэ тооцоолсон ханшийн томьёо нэмэх эсвэл унтраасан томьёог идэвхжүүлнэ үү."}
                </p>
                <button
                  className="primary-button"
                  onClick={() =>
                    tab === "rates"
                      ? setManageOpen(true)
                      : setFormulaManagerOpen(true)
                  }
                >
                  <Plus size={17} />
                  {tab === "rates" ? "Ханш нэмэх" : "Томьёо тохируулах"}
                </button>
              </section>
            )}
          </div>
        )}
        {tab === "calculator" && (
          appSettings.calculatorMode === "tape" ? (
            <TapeCalculatorPage
              availableRates={upsertRates(rates, calculated)}
              onShare={(tape) => void doShare([], undefined, "hundredths", tape)}
              notify={notify}
              sourceLogos={branding.sourceLogos}
            />
          ) : (
            <LegacyCalculatorPage
              availableRates={upsertRates(rates, calculated)}
              onShare={(tokens, mode) => void doShare([], tokens, mode)}
              notify={notify}
              sourceLogos={branding.sourceLogos}
              tokens={legacyTokens}
              setTokens={setLegacyTokens}
              result={legacyResult}
              setResult={setLegacyResult}
            />
          )
        )}
        {tab === "settings" && user && (
          <SettingsPage
            user={user}
            theme={theme}
            subscriptionCount={subscriptions.length}
            catalog={catalog}
            branding={branding}
            calculatorMode={appSettings.calculatorMode}
            calculatorModeBusy={calculatorModeBusy}
            adminIds={appSettings.adminIds || []}
            adminIdsBusy={adminIdsBusy}
            onTheme={setTheme}
            onManage={() => setManageOpen(true)}
            onBranding={setBranding}
            onCalculatorMode={(mode) => void changeCalculatorMode(mode)}
            onAdminIds={(ids) => void changeAdminIds(ids)}
            notify={notify}
            onLogout={() => {
              void api.logout().then(() => {
                setAccessToken(null);
                setUser(null);
                setAuthState("api-key");
              });
            }}
          />
        )}
      </main>
      <nav className="bottom-nav">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            className={tab === id ? "active" : ""}
            onClick={() => setTab(id)}
          >
            <Icon size={20} />
            <span>{label}</span>
          </button>
        ))}
      </nav>
      {sharing && selected.size > 0 && (
        <div className="share-bar">
          <span>{selected.size} сонгосон</span>
          <button onClick={() => void doShare(Array.from(selected))}>
            Telegram руу
            <Send size={17} />
          </button>
        </div>
      )}
      <ManageSheet
        open={manageOpen}
        catalog={catalog}
        subscriptions={subscriptions}
        onClose={() => setManageOpen(false)}
        onChanged={afterSubscriptionsChanged}
        notify={notify}
        sourceLogos={branding.sourceLogos}
      />
      <FormulaManager
        open={formulaManagerOpen}
        formulas={formulas}
        catalog={catalog}
        onClose={() => setFormulaManagerOpen(false)}
        onChanged={afterFormulasChanged}
        notify={notify}
      />
      {toast && (
        <div className={`toast ${toast.error ? "error" : ""}`}>
          {toast.error ? <X size={17} /> : <Check size={17} />}
          {toast.text}
        </div>
      )}
    </div>
  );
}
