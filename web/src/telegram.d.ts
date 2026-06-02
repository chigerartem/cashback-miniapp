/// <reference types="vite/client" />

declare global {
  interface TelegramWebApp {
    initData: string;
    initDataUnsafe: {
      user?: {
        id: number;
        first_name?: string;
        last_name?: string;
        username?: string;
        language_code?: string;
        photo_url?: string;
      };
      start_param?: string;
    };
    ready: () => void;
    expand: () => void;
    colorScheme: "light" | "dark";
    openLink: (url: string, options?: { try_instant_view?: boolean }) => void;
    openTelegramLink?: (url: string) => void;
    disableVerticalSwipes?: () => void;
    enableVerticalSwipes?: () => void;
    isClosingConfirmationEnabled?: boolean;
    enableClosingConfirmation?: () => void;
    headerColor?: string;
    backgroundColor?: string;
    setHeaderColor?: (color: string) => void;
    setBackgroundColor?: (color: string) => void;
    setBottomBarColor?: (color: string) => void;
    themeParams?: {
      bg_color?: string;
      text_color?: string;
      hint_color?: string;
      link_color?: string;
      button_color?: string;
      button_text_color?: string;
      secondary_bg_color?: string;
      header_bg_color?: string;
      bottom_bar_bg_color?: string;
      accent_text_color?: string;
      section_bg_color?: string;
      section_header_text_color?: string;
      subtitle_text_color?: string;
      destructive_text_color?: string;
    };
    HapticFeedback?: {
      notificationOccurred: (type: "success" | "warning" | "error") => void;
      impactOccurred: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
      selectionChanged?: () => void;
    };
    isFullscreen?: boolean;
    requestFullscreen?: () => void;
    exitFullscreen?: () => void;
    viewportHeight?: number;
    viewportStableHeight?: number;
    safeAreaInset?: { top: number; bottom: number; left: number; right: number };
    contentSafeAreaInset?: { top: number; bottom: number; left: number; right: number };
    onEvent?: (event: string, handler: (...args: unknown[]) => void) => void;
    offEvent?: (event: string, handler: (...args: unknown[]) => void) => void;
  }
  interface Window {
    Telegram?: { WebApp: TelegramWebApp };
  }
}
export {};
