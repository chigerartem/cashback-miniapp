import type { ReactNode } from "react";

/**
 * Demo-only phone frame. The Mini App is built for a phone-width Telegram
 * viewport; on a desktop browser it would stretch full-screen, so the static
 * demo (VITE_DEMO=true) renders it inside a centered phone-sized device frame.
 *
 * Sizing uses viewport units (dvh) so the inner app's `h-full` resolves to a
 * definite height. The `transform` on the device makes it the containing block
 * for the app's `position: fixed` bottom nav, so the nav anchors to the phone
 * instead of the window. In real Telegram this wrapper is not used.
 */
export function DemoFrame({ children }: { children: ReactNode }) {
  return (
    <div className="fixed inset-0 flex flex-col items-center justify-center gap-3 overflow-hidden bg-[radial-gradient(130%_130%_at_50%_-10%,#102a22_0%,#060606_58%)] p-0 sm:p-6">
      <div
        className="relative w-full overflow-hidden bg-[#0a0a0a] shadow-2xl shadow-black/70 h-[100dvh] sm:h-[min(100dvh-5rem,880px)] sm:w-[400px] sm:rounded-[2.5rem] sm:border sm:border-white/10 sm:ring-1 sm:ring-black/40"
        style={{ transform: "translateZ(0)" }}
      >
        {children}
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
