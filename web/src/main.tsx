import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { installTapHaptics } from "./haptics";
import "./index.css";

if (window.Telegram?.WebApp) {
  const tg = window.Telegram.WebApp;
  tg.ready();
  tg.expand();

  // Сливаем шапку, фон Telegram и нижний бар с цветом темы TG.
  // Используем именованное значение 'bg_color' — оно гарантированно работает
  // на всех версиях TG, в отличие от hex (требует Bot API 6.9+).
  // Наш CSS body/html/main тоже использует var(--tg-theme-bg-color), который
  // TG задаёт автоматически. В итоге шапка, область за контентом и сам контент
  // имеют ровно один цвет — без разрыва на границе.
  try { tg.setHeaderColor?.("bg_color"); } catch { /* noop */ }
  try { tg.setBackgroundColor?.("bg_color"); } catch { /* noop */ }
  try { tg.setBottomBarColor?.("bg_color"); } catch { /* noop */ }

  // Подстраховка: вручную пробрасываем themeParams.bg_color в CSS-переменную.
  // Большинство версий TG это делают автоматически, но на старых WebView
  // переменная может оказаться не задана — тогда body/html/main свалятся
  // на fallback #0a0a0a, который отличается от цвета шапки TG.
  const syncThemeBg = () => {
    const bg = tg.themeParams?.bg_color;
    if (bg) {
      document.documentElement.style.setProperty("--tg-theme-bg-color", bg);
    }
  };
  syncThemeBg();
  tg.onEvent?.("themeChanged", syncThemeBg);

  // Жёстко фиксируем высоту приложения по Telegram-viewport, иначе на iOS
  // `100vh`/`100dvh` пересчитывается при инерции прокрутки и верх контента
  // уезжает за пределы видимой области без возможности доскроллить обратно.
  // Берём МАКСИМУМ из увиденного и НЕ подписываемся на viewportChanged: на iOS
  // Telegram при скролле сворачивает свою шапку и шлёт viewportChanged с меньшей
  // высотой — если переписать --app-h мид-скролл, контейнер сжимается и скролл
  // подвисает/обрезается (Профиль с лидербордом «не листался, пока не подёргаешь»).
  // Сразу после ready может прийти «compact» высота, через ~300ms — полная.
  let appliedHeight = 0;
  const applyHeight = () => {
    const h = tg.viewportStableHeight ?? tg.viewportHeight ?? window.innerHeight;
    if (h && Number.isFinite(h) && h > appliedHeight) {
      appliedHeight = h;
      document.documentElement.style.setProperty("--app-h", `${Math.round(h)}px`);
    }
  };
  applyHeight();
  setTimeout(applyHeight, 0);
  setTimeout(applyHeight, 300);
} else {
  // В обычном браузере фолбэк на 100dvh через CSS
}

// Блокируем pinch-to-zoom: Safari игнорирует viewport user-scalable=no
const blockGesture = (e: Event) => e.preventDefault();
document.addEventListener("gesturestart", blockGesture);
document.addEventListener("gesturechange", blockGesture);
document.addEventListener("gestureend", blockGesture);
document.addEventListener(
  "touchmove",
  (e) => {
    if ((e as TouchEvent).touches.length > 1) e.preventDefault();
  },
  { passive: false },
);
// Double-tap zoom — игнор повторного тапа в пределах 350ms
let lastTouchEnd = 0;
document.addEventListener(
  "touchend",
  (e) => {
    const now = Date.now();
    if (now - lastTouchEnd <= 350) e.preventDefault();
    lastTouchEnd = now;
  },
  { passive: false },
);

// Глобальная тактильная отдача на нажатие любой кнопки/ссылки.
installTapHaptics();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
