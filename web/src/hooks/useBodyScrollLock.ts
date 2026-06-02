import { useEffect } from "react";

/** Блокирует прокрутку body и затемняет native-шапку Telegram, пока active === true. */
export function useBodyScrollLock(active: boolean) {
  useEffect(() => {
    if (!active) return;

    // Реальный скролл-контейнер приложения — <main>, НЕ body. Если лочить только
    // body, на iOS фон (main) продолжает прокручиваться под открытым модалом, а
    // overlay (position:fixed ВНУТРИ overflow-scroll контейнера) ещё и «уезжает»
    // вместе с фоном и не накрывает весь экран. Ставим main → overflow:hidden:
    // это и стопит скролл, и убирает scroll-container-контекст, из-за которого
    // iOS неправильно позиционировал fixed overlay (теперь снова от вьюпорта).
    const scroller = document.querySelector<HTMLElement>("main");
    const prevBodyOverflow = document.body.style.overflow;
    const prevBodyOverscroll = document.body.style.overscrollBehavior;
    const prevMainOverflow = scroller?.style.overflow ?? "";
    document.body.style.overflow = "hidden";
    document.body.style.overscrollBehavior = "none";
    if (scroller) scroller.style.overflow = "hidden";

    // iOS: при открытой клавиатуре свайп панит весь layout-viewport (фон + каретка
    // в инпуте уезжают), а overflow:hidden это НЕ блокирует. React-овский
    // onTouchMove — passive, preventDefault в нём игнорируется, поэтому вешаем СВОЙ
    // non-passive listener и режем touchmove, КРОМЕ скролла внутри реально
    // прокручиваемых областей модала (напр. список в StatsModal).
    const onTouchMove = (e: TouchEvent) => {
      let el = e.target as HTMLElement | null;
      while (el && el !== document.body) {
        const oy = getComputedStyle(el).overflowY;
        if ((oy === "auto" || oy === "scroll") && el.scrollHeight > el.clientHeight) {
          return; // внутри прокручиваемого элемента — разрешаем нативный скролл
        }
        el = el.parentElement;
      }
      e.preventDefault();
    };
    document.addEventListener("touchmove", onTouchMove, { passive: false });

    const tg = window.Telegram?.WebApp;
    const prevHeader = tg?.headerColor;
    try {
      tg?.setHeaderColor?.("#000000");
    } catch {
      // старые Telegram-клиенты не понимают hex — игнорируем
    }

    return () => {
      document.body.style.overflow = prevBodyOverflow;
      document.body.style.overscrollBehavior = prevBodyOverscroll;
      if (scroller) scroller.style.overflow = prevMainOverflow;
      document.removeEventListener("touchmove", onTouchMove);
      try {
        tg?.setHeaderColor?.(prevHeader || "bg_color");
      } catch {
        // ignore
      }
    };
  }, [active]);
}
