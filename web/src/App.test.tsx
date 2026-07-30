import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { api } from "./api";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    api: {
      me: vi.fn(),
      miniAppLogin: vi.fn(),
      rates: vi.fn(),
      calculated: vi.fn(),
      catalog: vi.fn(),
      subscriptions: vi.fn(),
      refresh: vi.fn(),
      logout: vi.fn(),
    },
  };
});

describe("App shell", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(api.me).mockResolvedValue({
      user: { telegramId: 1, username: "tester", firstName: "Тест" },
    });
    vi.mocked(api.rates).mockResolvedValue({ rates: [] });
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
  });
});
