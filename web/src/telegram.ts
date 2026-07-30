interface TelegramWebApp {
  initData: string;
  initDataUnsafe?: {
    start_param?: string;
    user?: { id: number };
  };
  colorScheme?: "light" | "dark";
  ready(): void;
  expand(): void;
  close(): void;
  shareMessage?: (
    messageId: string,
    callback?: (success: boolean) => void,
  ) => void;
  switchInlineQuery?: (query: string, chatTypes?: string[]) => void;
  HapticFeedback?: {
    impactOccurred(style: "light" | "medium" | "heavy"): void;
    notificationOccurred(type: "success" | "warning" | "error"): void;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

export function getTelegramWebApp(): TelegramWebApp | undefined {
  return window.Telegram?.WebApp;
}

function launchDataParameter(name: string): string {
  const fromQuery = new URLSearchParams(window.location.search).get(name);
  if (fromQuery) return fromQuery;

  // Telegram Desktop can pass Web App launch parameters in the URL fragment,
  // e.g. #tgWebAppData=…&tgWebAppVersion=…. URLSearchParams also decodes the
  // outer value, leaving the signed init-data query string intact for server
  // validation.
  const hash = window.location.hash.startsWith("#")
    ? window.location.hash.slice(1)
    : window.location.hash;
  return new URLSearchParams(hash).get(name) || "";
}

/** Return launch data from either Telegram's JS bridge or direct-link query. */
export function getTelegramInitData(): string {
  const bridgeData = window.Telegram?.WebApp?.initData?.trim();
  if (bridgeData) return bridgeData;
  return launchDataParameter("tgWebAppData");
}

export function isTelegramLaunch(): boolean {
  // telegram-web-app.js also creates window.Telegram.WebApp in an ordinary
  // browser, so the bridge object alone is not proof of a Telegram launch.
  return Boolean(
    getTelegramInitData() ||
      launchDataParameter("tgWebAppVersion") ||
      launchDataParameter("tgWebAppPlatform"),
  );
}

export function initializeTelegram(): void {
  const app = getTelegramWebApp();
  if (!app) return;
  app.ready();
  app.expand();
}

export function haptic(
  type: "success" | "warning" | "error" | "light" = "light",
): void {
  const app = getTelegramWebApp();
  if (!app?.HapticFeedback) return;
  if (type === "light") app.HapticFeedback.impactOccurred("light");
  else app.HapticFeedback.notificationOccurred(type);
}

export async function sharePreparedMessage(messageId: string): Promise<boolean> {
  const app = getTelegramWebApp();
  if (!app?.shareMessage) return false;
  return new Promise((resolve) => {
    app.shareMessage?.(messageId, (success) => resolve(success));
  });
}
