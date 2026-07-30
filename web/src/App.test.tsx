import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { api } from "./api";
import { getTelegramInitData } from "./telegram";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    api: {
      me: vi.fn(),
      miniAppLogin: vi.fn(),
      rates: vi.fn(),
      searchRates: vi.fn(),
      calculated: vi.fn(),
      formulas: vi.fn(),
      branding: vi.fn(),
      catalog: vi.fn(),
      subscriptions: vi.fn(),
      refresh: vi.fn(),
      logout: vi.fn(),
      calculate: vi.fn(),
      share: vi.fn(),
      createFormula: vi.fn(),
      updateFormula: vi.fn(),
      deleteFormula: vi.fn(),
      orderFormulas: vi.fn(),
    },
  };
});

describe("App shell", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    localStorage.clear();
    vi.mocked(api.me).mockResolvedValue({
      user: { telegramId: 1, username: "tester", firstName: "Тест" },
    });
    vi.mocked(api.rates).mockResolvedValue({ rates: [] });
    vi.mocked(api.searchRates).mockResolvedValue({ rates: [] });
    vi.mocked(api.calculated).mockResolvedValue({
      rates: [
        {
          key: "formula:delcrado",
          kind: "calculated",
          source: "Тооцоолсон",
          pair: "ДЕЛЬКРАДО",
          values: [{ label: "value", amount: "50.25" }],
          details: [],
          fetchedAt: "2026-07-30T08:00:00Z",
          status: "fresh",
          formula: "MongolBank RUB/MNT × 1.005",
        },
      ],
    });
    vi.mocked(api.catalog).mockResolvedValue({ providers: [] });
    vi.mocked(api.subscriptions).mockResolvedValue({ subscriptions: [] });
    vi.mocked(api.formulas).mockResolvedValue({ formulas: [] });
    vi.mocked(api.branding).mockResolvedValue({
      appLogoUrl: null,
      sourceLogos: {},
    });
    vi.mocked(api.calculate).mockResolvedValue({
      expression: "1 ÷ 3",
      result: "0.3333333333333333333333333333",
    });
    vi.mocked(api.share).mockResolvedValue({
      preparedMessageId: "prepared",
      inlineQuery: "_b:test",
      handoffUrl: null,
      inlineFallback: null,
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("shows all four primary destinations after login", async () => {
    render(<App />);
    await waitFor(() => expect(api.me).toHaveBeenCalled());
    expect(
      await screen.findByRole("heading", { name: "Ханш" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Тооцоолсон").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Тооны машин").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Тохиргоо").length).toBeGreaterThan(0);
    expect(api.calculated).not.toHaveBeenCalled();
  });

  it("reads signed Mini App launch data from Telegram Desktop's URL fragment", () => {
    window.history.replaceState(
      {},
      "",
      "/#tgWebAppData=user%3D%257B%2522id%2522%253A1%257D%26hash%3Dsigned",
    );

    expect(getTelegramInitData()).toBe("user=%7B%22id%22%3A1%7D&hash=signed");
  });

  it("enters multi-select and selects a held rate row", async () => {
    vi.mocked(api.rates).mockResolvedValue({
      rates: [
        {
          key: "rate:CBR:USD/RUB",
          kind: "subscription",
          source: "CBR",
          pair: "USD/RUB",
          values: [{ label: "value", amount: "80.25" }],
          details: [],
          fetchedAt: "2026-07-30T08:00:00Z",
          status: "fresh",
        },
      ],
    });
    render(<App />);
    const pair = await screen.findByText("USD/RUB");
    vi.useFakeTimers();
    fireEvent.pointerDown(pair.closest("article")!, { clientX: 10, clientY: 10 });
    act(() => vi.advanceTimersByTime(500));
    expect(screen.getByText("1 сонгосон")).toBeInTheDocument();
  });

  it("offers full and hundredths calculator shares", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Ханш" });
    fireEvent.click(screen.getAllByRole("button", { name: "Тооны машин" }).at(-1)!);
    fireEvent.click(screen.getByRole("button", { name: "1" }));
    fireEvent.click(screen.getByRole("button", { name: "÷" }));
    fireEvent.click(screen.getByRole("button", { name: "3" }));
    fireEvent.click(screen.getByRole("button", { name: "=" }));
    expect(
      await screen.findByText("0.3333333333333333333333333333"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /2 орны дүн/ }));
    await waitFor(() =>
      expect(api.share).toHaveBeenCalledWith(
        [],
        ["1", "/", "3"],
        "hundredths",
      ),
    );
  });

  it("shows watchlist rates first and searches all sources on demand", async () => {
    vi.mocked(api.rates).mockResolvedValue({
      rates: [
        {
          key: "rate:CBR:USD/RUB",
          kind: "subscription",
          source: "CBR",
          pair: "USD/RUB",
          values: [{ label: "value", amount: "80.25" }],
          details: [],
          fetchedAt: "2026-07-30T08:00:00Z",
          status: "fresh",
        },
      ],
    });
    vi.mocked(api.calculated).mockResolvedValue({
      rates: [
        {
          key: "formula:delcrado",
          kind: "calculated",
          source: "Тооцоолсон",
          pair: "ДЕЛЬКРАДО",
          values: [{ label: "value", amount: "50.25" }],
          details: [],
          fetchedAt: "2026-07-30T08:00:00Z",
          status: "fresh",
        },
      ],
    });
    vi.mocked(api.searchRates).mockResolvedValue({
      rates: [
        {
          key: "rate:TDBM:USD/MNT",
          kind: "subscription",
          source: "TDBM",
          pair: "USD/MNT",
          values: [{ label: "sell", amount: "3560" }],
          details: [],
          fetchedAt: "2026-07-30T08:00:00Z",
          status: "fresh",
        },
      ],
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Ханш" });
    fireEvent.click(screen.getAllByRole("button", { name: "Тооны машин" }).at(-1)!);
    fireEvent.click(screen.getByRole("button", { name: /Ханш сонгож оруулах/ }));

    expect(screen.getByText("Миний хадгалсан ханш")).toBeInTheDocument();
    expect(screen.getByText("USD/RUB")).toBeInTheDocument();
    expect(await screen.findByText("ДЕЛЬКРАДО")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "Ханш хайх" }), {
      target: { value: "usd/mnt" },
    });
    await waitFor(() => expect(api.searchRates).toHaveBeenCalledWith("usd/mnt"));
    expect(await screen.findByText("USD/MNT")).toBeInTheDocument();
    expect(screen.getByText("Бүх эх сурвалж")).toBeInTheDocument();
  });

  it("shows and updates the current formula draft above the editor", async () => {
    vi.mocked(api.catalog).mockResolvedValue({
      providers: [
        {
          name: "MongolBank",
          label: "Монголбанк",
          pairs: [
            {
              symbol: "RUB/MNT",
              label: "Оросын рубль",
              subscribed: false,
              formulaFields: [{ key: "rate", label: "ханш" }],
            },
          ],
        },
      ],
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Ханш" });
    fireEvent.click(screen.getAllByRole("button", { name: "Тооцоолсон" }).at(-1)!);
    fireEvent.click(screen.getByRole("button", { name: "Томьёо тохируулах" }));
    fireEvent.click(screen.getByRole("button", { name: "Шинэ томьёо" }));

    const preview = screen.getByText("Одоогийн томьёо").nextElementSibling;
    expect(preview).toHaveTextContent("Монголбанк · RUB/MNT · ханш × 1");

    fireEvent.change(screen.getByRole("textbox", { name: "Тогтмол утга" }), {
      target: { value: "1.005" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Нэмэлт хувь, %" }), {
      target: { value: "0.5" },
    });

    expect(preview).toHaveTextContent(
      "Монголбанк · RUB/MNT · ханш × 1.005 +0.5%",
    );
  });
});
