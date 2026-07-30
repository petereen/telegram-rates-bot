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

export const telegram = window.Telegram?.WebApp;
export const isTelegram = Boolean(telegram?.initData);

export function initializeTelegram(): void {
  if (!telegram) return;
  telegram.ready();
  telegram.expand();
}

export function haptic(
  type: "success" | "warning" | "error" | "light" = "light",
): void {
  if (!telegram?.HapticFeedback) return;
  if (type === "light") telegram.HapticFeedback.impactOccurred("light");
  else telegram.HapticFeedback.notificationOccurred(type);
}

export async function sharePreparedMessage(messageId: string): Promise<boolean> {
  if (!telegram?.shareMessage) return false;
  return new Promise((resolve) => {
    telegram.shareMessage?.(messageId, (success) => resolve(success));
  });
}
