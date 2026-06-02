import type { ReactNode } from "react";
import mockup from "./assets/iphone-mockup.png";

/**
 * Demo-only device mockup + Telegram chrome. The Mini App targets a phone-width
 * Telegram viewport; on desktop the static demo (VITE_DEMO=true) renders it
 * inside an iPhone mockup with a faked iOS status bar and Telegram header so it
 * reads as a real Telegram Mini App, and so the app content starts below the
 * Dynamic Island (which occupies the top ~7.4% of the screen). The app sits
 * behind the mockup PNG and shows through its transparent screen hole; the bezel
 * + island are drawn on top. A `transform` on the screen layer contains the
 * app's `position: fixed` bottom nav. On mobile the chrome + mockup are hidden
 * and the app is full-bleed; in real Telegram this wrapper is unused.
 */
export function DemoFrame({ children }: { children: ReactNode }) {
  return (
    <div className="fixed inset-0 flex flex-col items-center justify-center gap-3 overflow-hidden bg-[#070707] p-0 sm:p-4">
      <div className="relative h-[100dvh] w-full sm:h-[min(100dvh-5rem,820px)] sm:w-[402px]">
        <div
          className="absolute inset-0 flex flex-col overflow-hidden bg-[#0a0a0a] sm:left-[5.1%] sm:right-[5.1%] sm:top-[2.27%] sm:bottom-[2.27%]"
          style={{ transform: "translateZ(0)" }}
        >
          <StatusBar />
          <TgHeader />
          <div className="relative min-h-0 flex-1">{children}</div>
        </div>
        <img
          src={mockup}
          alt=""
          aria-hidden="true"
          draggable={false}
          className="pointer-events-none absolute inset-0 hidden h-full w-full select-none sm:block"
        />
      </div>
      <div className="hidden shrink-0 text-center text-[11px] text-neutral-500 sm:block">
        Telegram Mini App · live demo on mock data ·{" "}
        <a
          href="https://github.com/chigerartem/cashback-miniapp"
          target="_blank"
          rel="noreferrer"
          className="text-neutral-400 underline-offset-2 transition-colors hover:text-emerald-300 hover:underline"
        >
          source ↗
        </a>
      </div>
    </div>
  );
}

/** Faked iOS status bar — sits in the Dynamic Island band (top ~7.4% of screen). */
function StatusBar() {
  return (
    <div
      className="hidden shrink-0 items-center justify-between px-[8%] text-white sm:flex"
      style={{ height: "7.4%" }}
    >
      <span className="text-[13px] font-semibold tracking-tight">9:41</span>
      <span className="flex items-center gap-[5px]">
        {/* cellular */}
        <svg width="17" height="11" viewBox="0 0 17 11" fill="currentColor" aria-hidden="true">
          <rect x="0" y="7.5" width="3" height="3.5" rx="0.8" />
          <rect x="4.7" y="5" width="3" height="6" rx="0.8" />
          <rect x="9.4" y="2.5" width="3" height="8.5" rx="0.8" />
          <rect x="14" y="0" width="3" height="11" rx="0.8" />
        </svg>
        {/* wifi */}
        <svg width="16" height="12" viewBox="0 0 16 12" fill="currentColor" aria-hidden="true">
          <path d="M8 2.7c2.5 0 4.8 1 6.5 2.6l-1.5 1.6A7 7 0 0 0 8 4.9 7 7 0 0 0 3 6.9L1.5 5.3A9.4 9.4 0 0 1 8 2.7Z" />
          <path d="M8 6.7c1.4 0 2.7.6 3.6 1.5l-1.5 1.6A3 3 0 0 0 8 8.9a3 3 0 0 0-2.1.9L4.4 8.2A5 5 0 0 1 8 6.7Z" />
          <path d="M8 10.1 9.5 8.6a2.1 2.1 0 0 0-3 0L8 10.1Z" />
        </svg>
        {/* battery */}
        <svg width="27" height="13" viewBox="0 0 27 13" fill="none" aria-hidden="true">
          <rect x="0.6" y="0.6" width="22.8" height="11.8" rx="3.4" stroke="currentColor" strokeOpacity="0.45" />
          <rect x="2.2" y="2.2" width="15" height="8.6" rx="1.8" fill="currentColor" />
          <path d="M25 4.4c1 .5 1 3.7 0 4.2V4.4Z" fill="currentColor" fillOpacity="0.45" />
        </svg>
      </span>
    </div>
  );
}

/** Faked Telegram Mini App header — Close · title · menu. */
function TgHeader() {
  return (
    <div
      className="relative hidden shrink-0 items-center px-4 sm:flex"
      style={{ height: "5.8%" }}
    >
      <span className="text-[15px] text-[#3a9bff]">Закрыть</span>
      <div className="pointer-events-none absolute inset-x-0 flex flex-col items-center leading-none">
        <span className="text-[15px] font-semibold text-white">Cashback</span>
        <span className="mt-[3px] text-[10px] text-neutral-400">мини-приложение</span>
      </div>
      <span className="ml-auto grid h-[26px] w-[26px] place-items-center rounded-full bg-white/10 text-white/80">
        <svg width="15" height="4" viewBox="0 0 15 4" fill="currentColor" aria-hidden="true">
          <circle cx="2" cy="2" r="1.6" />
          <circle cx="7.5" cy="2" r="1.6" />
          <circle cx="13" cy="2" r="1.6" />
        </svg>
      </span>
    </div>
  );
}
