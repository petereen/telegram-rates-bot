import {
  ChevronRight,
  Clock3,
  Ellipsis,
  Plus,
  Search,
  Send,
  Trash2,
  WalletCards,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type {
  BrandingSettings,
  CalculationResult,
  CalculationTapeShare,
  RateSnapshot,
} from "./types";

type TapeOperator = "+" | "-" | "*" | "/";

interface TapeEntry {
  id: string;
  operator: TapeOperator;
  value: string;
  percentage?: boolean;
  label?: string;
}

interface TapeDocument {
  version: 1;
  id: string;
  title: string;
  entries: TapeEntry[];
  createdAt: string;
  updatedAt: string;
}

interface TapeCalculatorProps {
  availableRates: RateSnapshot[];
  sourceLogos: BrandingSettings["sourceLogos"];
  notify(message: string, error?: boolean): void;
  onShare(tape: CalculationTapeShare): void;
}

const ACTIVE_TAPE_KEY = "oyuns-rates-active-tape-v1";
const TAPE_HISTORY_KEY = "oyuns-rates-tape-history-v1";
const MAX_HISTORY = 10;

const newId = () =>
  globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;

function blankTape(): TapeDocument {
  const now = new Date().toISOString();
  return {
    version: 1,
    id: newId(),
    title: "Тооцоолол",
    entries: [{ id: newId(), operator: "+", value: "" }],
    createdAt: now,
    updatedAt: now,
  };
}

function readStoredTape(): TapeDocument {
  try {
    const parsed = JSON.parse(localStorage.getItem(ACTIVE_TAPE_KEY) || "null") as TapeDocument | null;
    if (parsed?.version === 1 && Array.isArray(parsed.entries) && parsed.entries.length) return parsed;
  } catch {
    // A malformed or unavailable store should never block the calculator.
  }
  return blankTape();
}

function readHistory(): TapeDocument[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(TAPE_HISTORY_KEY) || "[]") as TapeDocument[];
    return Array.isArray(parsed)
      ? parsed.filter((item) => item?.version === 1 && Array.isArray(item.entries)).slice(0, MAX_HISTORY)
      : [];
  } catch {
    return [];
  }
}

function hasContent(tape: TapeDocument): boolean {
  return tape.entries.some((entry) => entry.value.trim());
}

function formatAmount(value: string): string {
  const percentage = value.includes("%");
  const normalized = value.replaceAll(",", "").replace("%", "").trim();
  const match = normalized.match(/^(-?)(\d*)(?:\.(\d*))?$/);
  if (!match || (!match[2] && !match[3])) return value || "0";
  const [, sign, rawInteger, rawFraction = ""] = match;
  const integer = (rawInteger || "0").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const decimal = normalized.includes(".") ? `.${rawFraction}` : "";
  return `${sign}${integer}${decimal}${percentage ? "%" : ""}`;
}

function sanitizeTapeValue(value: string): string {
  const normalized = value.replaceAll(",", "").replace(/[^\d.-]/g, "");
  const sign = normalized.startsWith("-") ? "-" : "";
  const unsigned = normalized.replace(/-/g, "");
  const [integer = "", ...fractionParts] = unsigned.split(".");
  const fraction = fractionParts.join("");
  if (!integer && !fraction && !normalized.includes(".")) return sign;
  return `${sign}${integer || "0"}${normalized.includes(".") ? `.${fraction}` : ""}`;
}

function tokensFor(entries: TapeEntry[]): string[] {
  const complete = entries.filter((entry) => entry.value.trim());
  if (!complete.length || complete[0].percentage) return [];
  const tokens = [complete[0].value.replaceAll(",", "")];
  complete.slice(1).forEach((entry) => {
    if (entry.percentage) {
      tokens.push(`${entry.operator === "-" ? "-" : "+"}${entry.value.replaceAll(",", "").replace(/^[-+]/, "")}`);
    } else {
      tokens.push(entry.operator, entry.value.replaceAll(",", ""));
    }
  });
  return tokens;
}

function rateLabel(label: string): string {
  return { buy: "Авах", sell: "Зарах", value: "Ханш" }[label] || label;
}

export function TapeCalculatorPage({
  availableRates,
  sourceLogos,
  notify,
  onShare,
}: TapeCalculatorProps) {
  const [tape, setTape] = useState<TapeDocument>(readStoredTape);
  const [history, setHistory] = useState<TapeDocument[]>(readHistory);
  const [activeIndex, setActiveIndex] = useState<number>(tape.entries.length - 1);
  const [result, setResult] = useState<CalculationResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [picker, setPicker] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<RateSnapshot[] | null>(null);
  const tapeEndRef = useRef<HTMLDivElement>(null);

  const updateEntries = useCallback((change: (entries: TapeEntry[]) => TapeEntry[]) => {
    setTape((current) => ({
      ...current,
      entries: change(current.entries),
      updatedAt: new Date().toISOString(),
    }));
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(ACTIVE_TAPE_KEY, JSON.stringify(tape));
    } catch {
      // Continue with in-memory state when storage is restricted.
    }
  }, [tape]);

  useEffect(() => {
    try {
      localStorage.setItem(TAPE_HISTORY_KEY, JSON.stringify(history.slice(0, MAX_HISTORY)));
    } catch {
      // Continue with in-memory state when storage is restricted.
    }
  }, [history]);

  const calculate = useCallback(async () => {
    const tokens = tokensFor(tape.entries);
    if (!tokens.length) return;
    setBusy(true);
    try {
      setResult(await api.calculateTape(tokens));
      setActiveIndex(-1);
      tapeEndRef.current?.scrollIntoView?.({ block: "nearest" });
    } catch (error) {
      notify(error instanceof Error ? error.message : "Тооцоолох боломжгүй", true);
    } finally {
      setBusy(false);
    }
  }, [notify, tape.entries]);

  useEffect(() => {
    const query = searchQuery.trim();
    if (!picker || !query) {
      setSearchResults(null);
      return;
    }
    const timer = window.setTimeout(() => {
      void api.searchRates(query).then((data) => setSearchResults(data.rates)).catch(() => setSearchResults([]));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [picker, searchQuery]);

  const pickerRates = searchQuery.trim() ? searchResults || [] : availableRates;

  const appendDigit = useCallback((digit: string) => {
    setResult(null);
    const index = activeIndex >= 0 ? activeIndex : tape.entries.length - 1;
    setActiveIndex(index);
    updateEntries((entries) => entries.map((entry, itemIndex) => {
      if (itemIndex !== index || entry.percentage) return entry;
      if (digit === "." && entry.value.includes(".")) return entry;
      const base = entry.value === "0" && digit !== "." ? "" : entry.value;
      return { ...entry, value: `${base}${digit === "." && !base ? "0." : digit}` };
    }));
  }, [activeIndex, tape.entries.length, updateEntries]);

  const appendOperator = useCallback((operator: TapeOperator) => {
    setResult(null);
    const last = tape.entries.at(-1);
    if (!last?.value.trim()) {
      updateEntries((entries) => entries.map((entry, index) =>
        index === entries.length - 1 ? { ...entry, operator } : entry));
      setActiveIndex(tape.entries.length - 1);
      return;
    }
    const next = { id: newId(), operator, value: "" };
    updateEntries((entries) => [...entries, next]);
    setActiveIndex(tape.entries.length);
    window.setTimeout(() => tapeEndRef.current?.scrollIntoView?.({ block: "nearest" }), 0);
  }, [tape.entries, updateEntries]);

  const clearEntry = useCallback(() => {
    setResult(null);
    const index = activeIndex >= 0 ? activeIndex : tape.entries.length - 1;
    if (tape.entries.length > 1 && !tape.entries[index]?.value) {
      updateEntries((entries) => entries.filter((_, itemIndex) => itemIndex !== index));
      setActiveIndex(Math.max(0, index - 1));
    } else {
      updateEntries((entries) => entries.map((entry, itemIndex) =>
        itemIndex === index ? { ...entry, value: "", percentage: false, label: undefined } : entry));
      setActiveIndex(index);
    }
  }, [activeIndex, tape.entries, updateEntries]);

  const backspace = useCallback(() => {
    const index = activeIndex >= 0 ? activeIndex : tape.entries.length - 1;
    setResult(null);
    updateEntries((entries) => entries.map((entry, itemIndex) =>
      itemIndex === index && !entry.percentage
        ? { ...entry, value: entry.value.slice(0, -1), label: undefined }
        : entry));
    setActiveIndex(index);
  }, [activeIndex, tape.entries.length, updateEntries]);

  const archive = useCallback((document: TapeDocument) => {
    if (!hasContent(document)) return;
    setHistory((current) => [
      { ...document, updatedAt: new Date().toISOString() },
      ...current.filter((item) => item.id !== document.id),
    ].slice(0, MAX_HISTORY));
  }, []);

  const startNewTape = useCallback(() => {
    archive(tape);
    const next = blankTape();
    setTape(next);
    setResult(null);
    setActiveIndex(0);
  }, [archive, tape]);

  const reopenTape = (selected: TapeDocument) => {
    archive(tape);
    setTape({ ...selected, updatedAt: new Date().toISOString() });
    setHistory((current) => current.filter((item) => item.id !== selected.id));
    setResult(null);
    setActiveIndex(selected.entries.length - 1);
    setHistoryOpen(false);
  };

  const chooseRate = (rate: RateSnapshot, value: RateSnapshot["values"][number]) => {
    const label = `${rate.source} · ${rate.pair} · ${rateLabel(value.label)}`;
    const current = tape.entries[activeIndex];
    if (current && !current.value) {
      updateEntries((entries) => entries.map((entry, index) =>
        index === activeIndex ? { ...entry, value: value.amount, label } : entry));
    } else {
      updateEntries((entries) => [...entries, { id: newId(), operator: "+", value: value.amount, label }]);
      setActiveIndex(tape.entries.length);
    }
    setResult(null);
    setPicker(false);
    setSearchQuery("");
  };

  const addPercentage = (value: string) => {
    if (!tape.entries.some((entry) => entry.value)) return;
    updateEntries((entries) => [...entries, {
      id: newId(),
      operator: value.startsWith("-") ? "-" : "+",
      value: value.replace(/^[-+]/, ""),
      percentage: true,
    }]);
    setActiveIndex(-1);
    setResult(null);
    setMoreOpen(false);
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) {
        if (["+", "-", "*", "/"].includes(event.key)) {
          event.preventDefault();
          appendOperator(event.key as TapeOperator);
        } else if (event.key === "Enter" || event.key === "=") {
          event.preventDefault();
          void calculate();
        } else if (event.key === "Escape") {
          event.target.blur();
        }
        return;
      }
      if (/^\d$/.test(event.key) || event.key === ".") appendDigit(event.key);
      else if (["+", "-", "*", "/"].includes(event.key)) appendOperator(event.key as TapeOperator);
      else if (event.key === "Enter" || event.key === "=") void calculate();
      else if (event.key === "Backspace") backspace();
      else if (event.key === "Escape") {
        setPicker(false);
        setMoreOpen(false);
        setHistoryOpen(false);
      } else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
        event.preventDefault();
        setActiveIndex((current) => Math.max(0, Math.min(tape.entries.length - 1, current + (event.key === "ArrowUp" ? -1 : 1))));
      } else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [appendDigit, appendOperator, backspace, calculate, tape.entries.length]);

  const shareTape = () => onShare({
    title: tape.title,
    entries: tape.entries.filter((entry) => entry.value).map(({ operator, value, percentage, label }) => ({
      operator,
      value,
      percentage,
      label,
    })),
  });

  return (
    <div className="page calculator-page tape-calculator-page">
      <h1 className="sr-only">Тооны машин</h1>

      <section className="tape-workspace">
        <div className="tape-paper" aria-label="Тооцооллын тууз">
          {tape.entries.map((entry, index) => {
            const step = result?.steps[index];
            const active = activeIndex === index;
            return (
              <div className={`tape-entry ${active ? "active" : ""}`} key={entry.id}>
                <div className="tape-entry-line">
                  <select
                    aria-label={`${index + 1}-р мөрийн оператор`}
                    value={index === 0 ? "+" : entry.operator}
                    disabled={index === 0 || entry.percentage}
                    onChange={(event) => {
                      const operator = event.target.value as TapeOperator;
                      setResult(null);
                      updateEntries((entries) => entries.map((item, itemIndex) => itemIndex === index ? { ...item, operator } : item));
                      setActiveIndex(index);
                    }}
                  >
                    <option value="+">+</option><option value="-">−</option>
                    <option value="*">×</option><option value="/">÷</option>
                  </select>
                  {active && !entry.percentage ? (
                    <div className="tape-input-display">
                      <input
                        readOnly
                        inputMode="none"
                        aria-label={`${index + 1}-р мөрийн дүн`}
                        value={entry.value}
                        onPointerDown={(event) => event.preventDefault()}
                        onChange={(event) => {
                          const value = sanitizeTapeValue(event.target.value);
                          setResult(null);
                          updateEntries((entries) => entries.map((item, itemIndex) => itemIndex === index ? { ...item, value, label: undefined } : item));
                        }}
                      />
                      <span className="tape-caret" aria-hidden="true" />
                    </div>
                  ) : (
                    <button className="tape-value" onClick={() => setActiveIndex(index)}>
                      {formatAmount(entry.value)}
                    </button>
                  )}
                </div>
                {entry.label && <small className="tape-rate-label">{entry.label}</small>}
                {index > 0 && step && (
                  <div className="tape-subtotal">
                    <span />
                    <strong>+ {formatAmount(step.subtotal)}</strong>
                  </div>
                )}
              </div>
            );
          })}
          {!result && <p className="tape-pending">= дарж дэд нийлбэрүүдийг харуулна</p>}
          <div ref={tapeEndRef} />
        </div>

        <div className="tape-controls">
          <div className="tape-tools">
            <button onClick={() => setPicker(true)}><WalletCards size={17} /> Ханш</button>
            <button onClick={() => setMoreOpen(true)}><Ellipsis size={18} /> Бусад</button>
            <button onClick={() => setHistoryOpen(true)} aria-label="Туузны түүх"><Clock3 size={17} /></button>
            <button onClick={clearEntry}>CE</button>
            <button onClick={backspace} aria-label="Сүүлийн тэмдэгт устгах">⌫</button>
          </div>
          <div className="keypad tape-keypad">
            {["7", "8", "9", "/", "4", "5", "6", "*", "1", "2", "3", "-", "0", ".", "=", "+"].map((key) => (
              <button
                key={key}
                className={key === "=" ? "equals-key" : ["/", "*", "-", "+"].includes(key) ? "operator" : ""}
                disabled={busy && key === "="}
                onClick={() => key === "=" ? void calculate() : ["/", "*", "-", "+"].includes(key) ? appendOperator(key as TapeOperator) : appendDigit(key)}
              >
                {key === "*" ? "×" : key === "/" ? "÷" : key}
              </button>
            ))}
          </div>
          <div className="tape-bottom-actions">
            <button className="secondary-button" onClick={startNewTape}><Plus size={17} /> Шинэ тууз</button>
            <button className="primary-button" disabled={!result} onClick={shareTape}><Send size={17} /> Тууз хуваалцах</button>
          </div>
          <span className="sr-only" role="status" aria-live="polite">
            {result ? `Нийт ${formatAmount(result.result)}` : ""}
          </span>
        </div>
      </section>

      {picker && (
        <div className="sheet-backdrop" onMouseDown={() => setPicker(false)}>
          <section className="sheet rate-picker-sheet" onMouseDown={(event) => event.stopPropagation()}>
            <div className="sheet-handle" />
            <header className="sheet-header"><div><span className="eyebrow">ОРЛУУЛАХ УТГА</span><h2>Ханш сонгох</h2></div><button className="icon-button" onClick={() => setPicker(false)} aria-label="Хаах"><X size={20} /></button></header>
            <div className="picker-search"><Search size={17} /><input autoFocus value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Бүх эх сурвалжаас хайх" aria-label="Ханш хайх" /></div>
            <p className="picker-caption">{searchQuery.trim() ? "Бүх эх сурвалж" : "Миний хадгалсан ханш"}</p>
            <div className="picker-list">
              {pickerRates.filter((rate) => rate.values.length).map((rate) => (
                <div className="picker-row" key={rate.key}>
                  <span><strong>{rate.pair}</strong><small>{sourceLogos[rate.source]?.url && <img className="picker-source-logo" src={sourceLogos[rate.source].url || ""} alt="" />}{rate.source}</small></span>
                  <div>{rate.values.map((value) => <button key={value.label} onClick={() => chooseRate(rate, value)}><small>{rateLabel(value.label)}</small>{value.amount}</button>)}</div>
                </div>
              ))}
              {!pickerRates.some((rate) => rate.values.length) && <p className="picker-empty">Тохирох ханш олдсонгүй</p>}
            </div>
          </section>
        </div>
      )}

      {moreOpen && (
        <div className="sheet-backdrop" onMouseDown={() => setMoreOpen(false)}>
          <section className="sheet compact-sheet" onMouseDown={(event) => event.stopPropagation()}>
            <div className="sheet-handle" /><header className="sheet-header"><h2>Хувийн үйлдэл</h2><button className="icon-button" onClick={() => setMoreOpen(false)} aria-label="Хаах"><X size={20} /></button></header>
            <div className="percent-strip">{["+0.5%", "+1%", "-1%"].map((value) => <button key={value} onClick={() => addPercentage(value)}>{value}</button>)}</div>
          </section>
        </div>
      )}

      {historyOpen && (
        <div className="sheet-backdrop" onMouseDown={() => setHistoryOpen(false)}>
          <section className="sheet tape-history-sheet" onMouseDown={(event) => event.stopPropagation()}>
            <div className="sheet-handle" /><header className="sheet-header"><div><span className="eyebrow">СҮҮЛИЙН {MAX_HISTORY}</span><h2>Туузны түүх</h2></div><button className="icon-button" onClick={() => setHistoryOpen(false)} aria-label="Хаах"><X size={20} /></button></header>
            <div className="tape-history-list">
              {history.map((item) => (
                <div className="tape-history-row" key={item.id}>
                  <input aria-label="Туузны нэр өөрчлөх" value={item.title} onChange={(event) => setHistory((current) => current.map((entry) => entry.id === item.id ? { ...entry, title: event.target.value } : entry))} />
                  <small>{new Date(item.updatedAt).toLocaleString("mn-MN")}</small>
                  <button onClick={() => reopenTape(item)}>Нээх <ChevronRight size={16} /></button>
                  <button className="danger-icon" aria-label={`${item.title} устгах`} onClick={() => setHistory((current) => current.filter((entry) => entry.id !== item.id))}><Trash2 size={16} /></button>
                </div>
              ))}
              {!history.length && <p className="picker-empty">Хадгалсан тууз алга</p>}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
