import type { ReactNode } from "react";
import mockup from "./assets/iphone-mockup.png";

/**
 * Demo-only device mockup. The Mini App targets a phone-width Telegram viewport;
 * on desktop the static demo (VITE_DEMO=true) renders it inside an iPhone mockup.
 * The app sits *behind* the mockup PNG and shows through its transparent screen
 * hole (inset ≈5.1% sides / 2.27% top-bottom); the bezel + Dynamic Island are on
 * top. The app overlay and the mockup are both sized in % of the device box, so
 * they stay aligned regardless of the exact box dimensions. A `transform` on the
 * app layer makes it the containing block for the app's `position: fixed` bottom
 * nav. On mobile the mockup is hidden and the app is full-bleed; in real Telegram
 * this wrapper is unused.
 */
export function DemoFrame({ children }: { children: ReactNode }) {
  return (
    <div className="fixed inset-0 flex flex-col items-center justify-center gap-3 overflow-hidden bg-[#070707] p-0 sm:p-4">
      <div className="relative h-[100dvh] w-full sm:h-[min(100dvh-5rem,820px)] sm:w-[402px]">
        <div
          className="absolute inset-0 overflow-hidden bg-[#0a0a0a] sm:left-[5.1%] sm:right-[5.1%] sm:top-[2.27%] sm:bottom-[2.27%]"
          style={{ transform: "translateZ(0)" }}
        >
          {children}
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
