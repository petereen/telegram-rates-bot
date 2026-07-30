import {
  Calculator,
  Check,
  ChevronRight,
  CircleHelp,
  Moon,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings,
  Share2,
  SlidersHorizontal,
  Sun,
  Trash2,
  WalletCards,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "./api";
import { haptic, isTelegram, sharePreparedMessage, telegram } from "./telegram";
import type {
  CatalogProvider,
  RateSnapshot,
  Subscription,
  TabId,
  ThemeChoice,
  User,
} from "./types";

const AUTO_REFRESH_MS = 5 * 60 * 1000;

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

interface RateRowsProps {
  rates: RateSnapshot[];
  sharing: boolean;
  selected: Set<string>;
  refreshing: Set<string>;
  onToggle(key: string): void;
  onRefresh(key: string): void;
  onShare(keys: string[]): void;
}

function RateRows({
  rates,
  sharing,
  selected,
  refreshing,
  onToggle,
  onRefresh,
  onShare,
}: RateRowsProps) {
  const groups = useMemo(() => {
    const result = new Map<string, RateSnapshot[]>();
    rates.forEach((rate) => {
      const group = rate.kind === "calculated" ? "Тооцоолсон ханш" : rate.source;
      result.set(group, [...(result.get(group) || []), rate]);
    });
    return Array.from(result.entries());
  }, [rates]);

  return (
    <div className="rate-groups">
      {groups.map(([source, items]) => (
        <section className="ledger-group" key={source}>
          <div className="group-heading">
            <span>{source}</span>
            <span>{items.length.toString().padStart(2, "0")}</span>
          </div>
          {items.map((rate) => (
            <article
              className={`rate-row ${selected.has(rate.key) ? "is-selected" : ""}`}
              key={rate.key}
              onClick={() => sharing && onToggle(rate.key)}
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
}

function ManageSheet({
  open,
  catalog,
  subscriptions,
  onClose,
  onChanged,
  notify,
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
            `${provider.name} ${pair.symbol} ${pair.label}`
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
        aria-label="Ханш удирдах"
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
          {["Бүгд", ...catalog.map((item) => item.name)].map((name) => (
            <button
              key={name}
              className={providerFilter === name ? "active" : ""}
              onClick={() => setProviderFilter(name)}
            >
              {name}
            </button>
          ))}
        </div>
        <div className="catalog-list">
          {filtered.map((provider) => (
            <section key={provider.name}>
              <div className="catalog-provider">{provider.name}</div>
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
  onShare(tokens: Array<string | number>): void;
  notify(message: string, error?: boolean): void;
}

function CalculatorPage({
  availableRates,
  onShare,
  notify,
}: CalculatorPageProps) {
  const [tokens, setTokens] = useState<Array<string | number>>([]);
  const [picker, setPicker] = useState(false);
  const [result, setResult] = useState<{
    expression: string;
    result: string;
  } | null>(null);
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

  const chooseRate = (amount: string) => {
    setTokens((current) => [...current, amount]);
    setResult(null);
    setPicker(false);
    haptic();
  };

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
          <button className="primary-button full" onClick={() => onShare(tokens)}>
            <Send size={17} />
            Хариуг хуваалцах
          </button>
        )}
      </section>
      {picker && (
        <div className="sheet-backdrop" onMouseDown={() => setPicker(false)}>
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
              <button className="icon-button" onClick={() => setPicker(false)}>
                <X size={20} />
              </button>
            </header>
            <div className="picker-list">
              {availableRates
                .filter((rate) => rate.values.length)
                .map((rate) => (
                  <div className="picker-row" key={rate.key}>
                    <span>
                      <strong>{rate.pair}</strong>
                      <small>{rate.source}</small>
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
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

interface SettingsPageProps {
  user: User;
  theme: ThemeChoice;
  subscriptionCount: number;
  onTheme(theme: ThemeChoice): void;
  onManage(): void;
  onLogout(): void;
}

function SettingsPage({
  user,
  theme,
  subscriptionCount,
  onTheme,
  onManage,
  onLogout,
}: SettingsPageProps) {
  const [helpOpen, setHelpOpen] = useState(false);
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
          <span className="access-badge">WHITELIST</span>
        </div>
      </section>
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
      {!isTelegram && (
        <button className="secondary-button logout-button" onClick={onLogout}>
          Гарах
        </button>
      )}
      <p className="version-note">OYUNS RATES · 1.0.0</p>
    </div>
  );
}

export default function App() {
  const [authState, setAuthState] = useState<"loading" | "ready" | "login" | "denied">("loading");
  const [user, setUser] = useState<User | null>(null);
  const [tab, setTab] = useState<TabId>("rates");
  const [rates, setRates] = useState<RateSnapshot[]>([]);
  const [calculated, setCalculated] = useState<RateSnapshot[]>([]);
  const [catalog, setCatalog] = useState<CatalogProvider[]>([]);
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [manageOpen, setManageOpen] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [refreshing, setRefreshing] = useState<Set<string>>(new Set());
  const [loadingData, setLoadingData] = useState(true);
  const [toast, setToast] = useState<{ text: string; error: boolean } | null>(null);
  const [theme, setTheme] = useState<ThemeChoice>(
    () => (localStorage.getItem("rates-theme") as ThemeChoice) || "system",
  );

  const notify = useCallback((text: string, error = false) => {
    setToast({ text, error });
    window.setTimeout(() => setToast(null), 3200);
  }, []);

  const loadReferenceData = useCallback(async () => {
    const [catalogData, subscriptionData] = await Promise.all([
      api.catalog(),
      api.subscriptions(),
    ]);
    setCatalog(catalogData.providers);
    setSubscriptions(subscriptionData.subscriptions);
  }, []);

  const loadRates = useCallback(async () => {
    setLoadingData(true);
    try {
      const [rateData, formulaData] = await Promise.all([
        api.rates(),
        api.calculated(),
      ]);
      setRates(rateData.rates);
      setCalculated(formulaData.rates);
    } finally {
      setLoadingData(false);
    }
  }, []);

  const bootstrap = useCallback(async () => {
    try {
      if (isTelegram && telegram?.initData) {
        const session = await api.miniAppLogin(telegram.initData);
        setUser(session.user);
      } else {
        const session = await api.me();
        setUser(session.user);
      }
      setAuthState("ready");
      await Promise.all([loadReferenceData(), loadRates()]);
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) setAuthState("denied");
      else setAuthState("login");
    }
  }, [loadRates, loadReferenceData]);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

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
    if (authState !== "ready" || !isTelegram) return;
    const start = telegram?.initDataUnsafe?.start_param;
    if (!start?.startsWith("share_")) return;
    const token = start.slice(6);
    void api
      .prepareBundle(token)
      .then(async ({ preparedMessageId }) => {
        const successful = await sharePreparedMessage(preparedMessageId);
        if (!successful) {
          telegram?.switchInlineQuery?.(`_b:${token}`, [
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

  const doShare = async (
    rateKeys: string[],
    calculationTokens?: Array<string | number>,
  ) => {
    try {
      const share = await api.share(rateKeys, calculationTokens);
      if (isTelegram) {
        const successful = await sharePreparedMessage(share.preparedMessageId);
        if (!successful && telegram?.switchInlineQuery) {
          telegram.switchInlineQuery(share.inlineQuery, [
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

  if (authState === "loading") {
    return (
      <main className="center-state">
        <div className="brand-mark">Ө</div>
        <span>Ханш бэлдэж байна…</span>
      </main>
    );
  }

  if (authState === "login") {
    return (
      <main className="login-page">
        <div className="login-rule" />
        <span className="eyebrow">OYUNS · EXCHANGE LEDGER</span>
        <h1>Ханш нэг дор.<br />Илүү ойлгомжтой.</h1>
        <p>Хадгалсан болон тооцоолсон ханшаа харах, тооцоолох, Telegram чат руу цэгцтэй хуваалцах.</p>
        <a className="telegram-login" href="/api/auth/telegram/start">
          <Send size={19} />
          Telegram-аар нэвтрэх
        </a>
        <small>Зөвхөн whitelist-д бүртгэлтэй хэрэглэгч нэвтэрнэ.</small>
      </main>
    );
  }

  if (authState === "denied") {
    return (
      <main className="center-state denied">
        <div className="brand-mark">!</div>
        <h1>Хандах эрхгүй</h1>
        <p>Таны Telegram бүртгэл whitelist-д байхгүй байна.</p>
      </main>
    );
  }

  const activeRates = tab === "calculated" ? calculated : rates;
  const allAvailable = [...rates, ...calculated];

  return (
    <div className="app-shell">
      <aside className="desktop-rail">
        <div className="rail-brand">Ө</div>
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
                  {tab === "rates" ? "МИНИЙ ЖАГСААЛТ" : "ТОГТМОЛ ГУРВАН ХАНШ"}
                </span>
                <h1>{tab === "rates" ? "Ханш" : "Тооцоолсон"}</h1>
              </div>
              <div className="header-actions">
                {tab === "rates" && (
                  <button className="icon-button bordered" onClick={() => setManageOpen(true)}>
                    <Plus size={19} />
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
                onRefresh={(key) => refresh([key])}
                onShare={(keys) => void doShare(keys)}
              />
            ) : (
              <section className="empty-ledger">
                <span>00</span>
                <h2>Хадгалсан ханш алга</h2>
                <p>Өдөр бүр хардаг эх сурвалж, валютын хослолоо нэмнэ үү.</p>
                <button className="primary-button" onClick={() => setManageOpen(true)}>
                  <Plus size={17} />
                  Ханш нэмэх
                </button>
              </section>
            )}
          </div>
        )}
        {tab === "calculator" && (
          <CalculatorPage
            availableRates={allAvailable}
            onShare={(tokens) => void doShare([], tokens)}
            notify={notify}
          />
        )}
        {tab === "settings" && user && (
          <SettingsPage
            user={user}
            theme={theme}
            subscriptionCount={subscriptions.length}
            onTheme={setTheme}
            onManage={() => setManageOpen(true)}
            onLogout={() => {
              void api.logout().then(() => {
                setUser(null);
                setAuthState("login");
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
