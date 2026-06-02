import { useCallback, useEffect, useState, type SVGProps } from "react";
import { getMe, type MeResponse } from "./api";
import Home from "./tabs/Home";
import Trading from "./tabs/Trading";
import Community from "./tabs/Community";
import Profile from "./tabs/Profile";

type Tab = "home" | "trading" | "community" | "profile";
type IconFC = (p: SVGProps<SVGSVGElement>) => JSX.Element;

const IconStroke = (props: SVGProps<SVGSVGElement>) => (
  <svg
    fill="none"
    stroke="currentColor"
    strokeWidth={1.75}
    strokeLinecap="round"
    strokeLinejoin="round"
    viewBox="0 0 24 24"
    {...props}
  />
);

const HomeIcon: IconFC = (p) => (
  <IconStroke {...p}>
    <path d="M3 11.5 12 4l9 7.5" />
    <path d="M5 10v9a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1v-9" />
  </IconStroke>
);
const TradingIcon: IconFC = (p) => (
  <IconStroke {...p}>
    <path d="M3 17l6-6 4 4 8-9" />
    <path d="M14 6h7v7" />
  </IconStroke>
);
const CommunityIcon: IconFC = (p) => (
  <IconStroke {...p}>
    <circle cx="9" cy="8" r="3.2" />
    <path d="M2.5 19c0-3.5 3-5.5 6.5-5.5s6.5 2 6.5 5.5" />
    <circle cx="17" cy="8.5" r="2.5" />
    <path d="M17 13.5c2.6 0 4.5 1.5 4.5 4" />
  </IconStroke>
);
const ProfileIcon: IconFC = (p) => (
  <IconStroke {...p}>
    <circle cx="12" cy="8" r="3.6" />
    <path d="M4.5 20c0-3.6 3.4-6.2 7.5-6.2s7.5 2.6 7.5 6.2" />
  </IconStroke>
);

const TABS: { id: Tab; label: string; Icon: IconFC }[] = [
  { id: "home",      label: "Главная",   Icon: HomeIcon },
  { id: "trading",   label: "Калькулятор", Icon: TradingIcon },
  { id: "community", label: "Комьюнити", Icon: CommunityIcon },
  { id: "profile",   label: "Профиль",   Icon: ProfileIcon },
];

const ME_CACHE_KEY = "cashback_me_v1";

// Каркас на самый первый запуск (нет кэша и getMe ещё не вернулся) — чтобы
// показать главный экран сразу, без блокирующей «Загрузки…». Реальные данные
// подменят его, как только придёт ответ. Home устойчив к пустым balances/
// exchanges (рисует состояния «нет данных»), имя берётся из Telegram initData.
const PLACEHOLDER_ME: MeResponse = {
  user: { id: "", tg_id: 0, tg_username: null, name: "", ref_code: "", vip_tier: "bronze", language: "ru" },
  balance: { accrued_usd: "0", paid_out_usd: "0", reserved_usd: "0", available_usd: "0" },
  balances: [],
  exchanges: [],
  withdrawal: { min_usd: 1, daily_limit_usd: 5000, monthly_limit_usd: 20000, cooldown_minutes: 30 },
};

function loadCachedMe(): MeResponse | null {
  try {
    const raw = localStorage.getItem(ME_CACHE_KEY);
    return raw ? (JSON.parse(raw) as MeResponse) : null;
  } catch {
    return null;
  }
}

export default function App() {
  const [tab, setTab] = useState<Tab>("home");
  // Инициализируемся из кэша: при переоткрытии показываем прошлые данные сразу.
  const [me, setMe] = useState<MeResponse | null>(() => loadCachedMe());
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    getMe()
      .then((m) => {
        setMe(m);
        setError(null);
        try {
          localStorage.setItem(ME_CACHE_KEY, JSON.stringify(m));
        } catch {
          /* localStorage недоступен/переполнен — некритично */
        }
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    const tg = window.Telegram?.WebApp;
    tg?.ready?.();
    tg?.expand?.();
    tg?.disableVerticalSwipes?.();
    reload();
  }, [reload]);

  return (
    <div className="flex h-full flex-col">
      <main className="flex-1 overflow-y-scroll overscroll-contain bg-[var(--tg-theme-bg-color,#0a0a0a)] pb-24">
        {/* min-h calc(100%+1px) держит iOS scroll-context ПОСТОЯННО активным.
            Иначе при переключении с короткого таба на длинный (Профиль с
            лидербордом) momentum-скролл не включается, пока экран не «подёргать»
            — контент обрезается и не листается. Лишний 1px не виден. */}
        <div className="min-h-[calc(100%+1px)]">
          {/* Ошибку показываем, только если данных нет вообще (ни кэша, ни
              свежих) — это случай «открыли вне Telegram» / отказ авторизации.
              Если кэш есть, фоновый сбой обновления молча игнорируем. */}
          {error && !me && (
            <div className="m-4 rounded-lg bg-red-900/40 p-4 text-sm text-red-200">
              Ошибка загрузки: {error}. Откройте приложение из бота — без авторизации Telegram запрос не пройдёт.
            </div>
          )}
          {!(error && !me) && (
            <>
              <div hidden={tab !== "home"}><Home me={me ?? PLACEHOLDER_ME} onReload={reload} /></div>
              <div hidden={tab !== "trading"}><Trading me={me ?? PLACEHOLDER_ME} /></div>
              <div hidden={tab !== "community"}><Community me={me ?? PLACEHOLDER_ME} /></div>
              <div hidden={tab !== "profile"}><Profile me={me ?? PLACEHOLDER_ME} /></div>
            </>
          )}
        </div>
      </main>

      <nav
        className="fixed inset-x-0 bottom-0 z-40 border-t border-white/5 bg-neutral-950/85 backdrop-blur-xl"
        style={{ paddingBottom: "env(safe-area-inset-bottom, 0)" }}
      >
        <div className="mx-auto grid max-w-md grid-cols-4">
          {TABS.map((t) => {
            const active = tab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className="group relative flex flex-col items-center gap-1 py-2.5"
              >
                <span
                  className={
                    "absolute top-0 h-[2px] w-8 rounded-full bg-emerald-400 transition-opacity " +
                    (active ? "opacity-100" : "opacity-0")
                  }
                />
                <span
                  className={
                    "flex h-9 w-9 items-center justify-center rounded-xl transition " +
                    (active
                      ? "bg-emerald-500/10 text-emerald-300"
                      : "text-neutral-500 group-active:text-neutral-300")
                  }
                >
                  <t.Icon className="h-5 w-5" />
                </span>
                <span
                  className={
                    "text-[10.5px] font-medium tracking-wide transition " +
                    (active ? "text-emerald-300" : "text-neutral-500")
                  }
                >
                  {t.label}
                </span>
              </button>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
