import { useEffect, useState } from "react";
import {
  disconnectExchange,
  getExchanges,
  getGlobalStats,
  getRecentWithdrawals,
  type ExchangeBalance,
  type ExchangeInfo,
  type GlobalStats,
  type MeResponse,
  type RecentWithdrawal,
} from "../api";
import ConnectExchangeModal from "../components/ConnectExchangeModal";
import StatsModal from "../components/StatsModal";
import UserAvatar, { tgHandle } from "../components/UserAvatar";
import WithdrawModal from "../components/WithdrawModal";
import { fmtUsd, fmtUsdCompact, fmtInt } from "../format";

const TIER_LABELS: Record<string, string> = {
  bronze:   "Bronze",
  silver:   "Silver",
  gold:     "Gold",
  platinum: "Platinum",
  diamond:  "Diamond",
  vip:      "VIP",
};

// VIP-надбавка в % сверх базовой ставки биржи (база — в ExchangeInfo.user_base_rate_pct:
// bingx 30, binance 5). Итоговый % = база активной биржи + надбавка.
const TIER_BONUS: Record<string, number> = {
  bronze: 0, silver: 1, gold: 2, platinum: 3, diamond: 4, vip: 5,
};

// Кэш домашних данных: при переоткрытии секции «Биржи» / «Последние выплаты» /
// статы показываются мгновенно из прошлого снимка, потом обновляются фоном.
const CK_STATS = "cashback_stats_v1";
const CK_WD = "cashback_withdrawals_v1";
const CK_EXCH = "cashback_exchanges_v1";

function cacheGet<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}
function cacheSet<T>(key: string, val: T): void {
  try {
    localStorage.setItem(key, JSON.stringify(val));
  } catch {
    /* localStorage недоступен/полон — некритично */
  }
}

type Props = {
  me: MeResponse;
  onReload: () => void;
};

export default function Home({ me, onReload }: Props) {
  const [connectTarget, setConnectTarget] = useState<ExchangeInfo | null>(null);
  const [withdrawTarget, setWithdrawTarget] = useState<string | null>(null);
  const [statsTarget, setStatsTarget] = useState<string | null>(null);
  const [stats, setStats] = useState<GlobalStats | null>(() => cacheGet<GlobalStats>(CK_STATS));
  const [withdrawals, setWithdrawals] = useState<RecentWithdrawal[] | null>(() => cacheGet<RecentWithdrawal[]>(CK_WD));
  const [exchanges, setExchanges] = useState<ExchangeInfo[] | null>(() => cacheGet<ExchangeInfo[]>(CK_EXCH));
  const [activeBalanceSlug, setActiveBalanceSlug] = useState<string>("bingx");

  useEffect(() => {
    getGlobalStats().then((s) => { setStats(s); cacheSet(CK_STATS, s); }).catch(() => {});
    getRecentWithdrawals(4)
      .then((w) => { setWithdrawals(w); cacheSet(CK_WD, w); })
      .catch(() => setWithdrawals((p) => p ?? []));
    getExchanges()
      .then((e) => { setExchanges(e); cacheSet(CK_EXCH, e); })
      .catch(() => setExchanges((p) => p ?? []));
  }, []);

  // Балансы, которые показываем: только биржи с подключённым (active/pending) аккаунтом.
  const connectedSlugs = new Set(
    me.exchanges
      .filter((e) => e.status === "active" || e.status === "pending")
      .map((e) => e.exchange),
  );
  const visibleBalances = (me.balances || []).filter((b) => connectedSlugs.has(b.exchange));
  const activeBalance =
    visibleBalances.find((b) => b.exchange === activeBalanceSlug) || visibleBalances[0] || null;

  // Если activeBalanceSlug пропал из видимых — переключаемся на первую.
  useEffect(() => {
    if (visibleBalances.length === 0) return;
    if (!visibleBalances.find((b) => b.exchange === activeBalanceSlug)) {
      setActiveBalanceSlug(visibleBalances[0].exchange);
    }
  }, [visibleBalances, activeBalanceSlug]);

  const exchangeMeta = (slug: string): ExchangeInfo | null =>
    exchanges?.find((e) => e.slug === slug) || null;

  const reloadExchanges = () => {
    getExchanges().then((e) => { setExchanges(e); cacheSet(CK_EXCH, e); }).catch(() => {});
    onReload();
  };

  // Имя и @handle — из живого Telegram-профиля (initDataUnsafe обновляется при
  // каждом открытии Mini App), фолбэк на значения из БД. Иначе после смены
  // имени/юзернейма в Telegram в шапке остаётся старое.
  const tgU = window.Telegram?.WebApp?.initDataUnsafe?.user;
  const displayName = tgU?.first_name || tgU?.username || me.user.name;
  const userHandle = tgU?.username ? `@${tgU.username}` : tgHandle(me.user);

  return (
    <div className="space-y-5 px-4 pb-4 pt-6">
      <header className="flex items-center justify-between pb-1">
        <div className="flex items-center gap-3">
          <UserAvatar name={displayName} size={44} />
          <div>
            <div className="text-sm text-neutral-400">Здравствуйте,</div>
            <div className="text-lg font-semibold leading-tight">{displayName}</div>
          </div>
        </div>
        <div className="text-xs text-neutral-500">{userHandle}</div>
      </header>

      <div className="grid grid-cols-3 gap-2">
        <Stat label="Всего выплачено" value={fmtUsdCompact(stats?.total_paid_out_usd)} />
        <Stat label="Трейдеров" value={fmtInt(stats?.total_traders)} />
        <Stat label="Объём 30д" value={fmtUsdCompact(stats?.volume_30d_usd)} />
      </div>

      <BalanceCarousel
        balances={visibleBalances}
        exchangesCatalog={exchanges}
        activeSlug={activeBalanceSlug}
        onChangeSlug={setActiveBalanceSlug}
        active={activeBalance}
        vipTier={me.user.vip_tier}
        onWithdraw={(slug) => setWithdrawTarget(slug)}
        onStats={(slug) => setStatsTarget(slug)}
      />

      <section className="rounded-2xl bg-neutral-900 p-5">
        <h2 className="mb-3 text-base font-semibold">Биржи</h2>
        <ExchangesList
          exchanges={exchanges}
          onConnect={(ex) => setConnectTarget(ex)}
          onDisconnect={async (ex) => {
            const ok = window.confirm(
              `Отключить ${ex.name}? Кешбэк по ней останется в истории, но новые сделки учитываться не будут, пока биржа не будет подключена снова.`,
            );
            if (!ok) return;
            try {
              await disconnectExchange(ex.slug);
              reloadExchanges();
            } catch (e: unknown) {
              alert(e instanceof Error ? e.message : String(e));
            }
          }}
        />
      </section>

      <section className="rounded-2xl bg-neutral-900 p-5">
        <h2 className="mb-3 text-base font-semibold">Последние выплаты</h2>
        <WithdrawalsFeed items={withdrawals} />
      </section>

      <ConnectExchangeModal
        open={connectTarget !== null}
        exchange={connectTarget}
        onClose={() => setConnectTarget(null)}
        onSuccess={reloadExchanges}
      />
      <WithdrawModal
        open={withdrawTarget !== null}
        sourceExchange={withdrawTarget}
        sourceExchangeMeta={withdrawTarget ? exchangeMeta(withdrawTarget) : null}
        sourceBalance={
          withdrawTarget
            ? visibleBalances.find((b) => b.exchange === withdrawTarget) ?? null
            : null
        }
        onClose={() => setWithdrawTarget(null)}
        onSuccess={onReload}
        exchanges={me.exchanges ?? []}
        limits={me.withdrawal}
      />
      <StatsModal
        open={statsTarget !== null}
        exchange={statsTarget}
        exchangeMeta={statsTarget ? exchangeMeta(statsTarget) : null}
        onClose={() => setStatsTarget(null)}
      />
    </div>
  );
}

function BalanceCarousel({
  balances,
  exchangesCatalog,
  activeSlug,
  onChangeSlug,
  active,
  vipTier,
  onWithdraw,
  onStats,
}: {
  balances: ExchangeBalance[];
  exchangesCatalog: ExchangeInfo[] | null;
  activeSlug: string;
  onChangeSlug: (slug: string) => void;
  active: ExchangeBalance | null;
  vipTier: string;
  onWithdraw: (slug: string) => void;
  onStats: (slug: string) => void;
}) {
  if (balances.length === 0) {
    return (
      <section className="rounded-2xl bg-neutral-900 p-5">
        <div className="text-sm text-neutral-400">Ваш баланс</div>
        <div className="mt-1 text-3xl font-bold text-neutral-500">$0.00</div>
        <div className="mt-1 text-xs text-neutral-500">
          Подключите биржу ниже, чтобы начать получать кешбэк.
        </div>
      </section>
    );
  }

  const meta = exchangesCatalog?.find((e) => e.slug === activeSlug);

  return (
    <section className="rounded-2xl bg-neutral-900 p-5">
      {/* Pills */}
      {balances.length > 1 && (
        <div
          className="mb-3 grid gap-1.5 rounded-xl bg-neutral-800 p-1"
          style={{ gridTemplateColumns: `repeat(${balances.length}, minmax(0, 1fr))` }}
        >
          {balances.map((b) => {
            const m = exchangesCatalog?.find((e) => e.slug === b.exchange);
            const isActive = b.exchange === activeSlug;
            return (
              <button
                key={b.exchange}
                onClick={() => onChangeSlug(b.exchange)}
                className={
                  "flex items-center justify-center gap-2 truncate rounded-lg px-2 py-1.5 text-xs transition " +
                  (isActive
                    ? "bg-neutral-700 text-white font-medium"
                    : "text-neutral-400")
                }
              >
                <BalancePillLogo ex={m} fallbackName={b.exchange} />
                <span className="truncate">{m?.name || b.exchange.toUpperCase()}</span>
              </button>
            );
          })}
        </div>
      )}

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-neutral-400">
          {meta && <BalancePillLogo ex={meta} fallbackName={meta.slug} />}
          <span>{meta?.name || activeSlug.toUpperCase()}</span>
        </div>
        <div className="rounded-full bg-emerald-500/15 px-2 py-1 text-xs text-emerald-400">
          {TIER_LABELS[vipTier] ?? vipTier} ·{" "}
          {(meta?.user_base_rate_pct ?? 30) + (TIER_BONUS[vipTier] ?? 0)}%
        </div>
      </div>

      <div className="mt-2 text-3xl font-bold">
        {fmtUsd(active?.available_usd ?? "0")}
      </div>
      <div className="mt-1 text-xs text-neutral-500">
        Начислено {fmtUsd(active?.accrued_usd ?? "0")} · Выведено{" "}
        {fmtUsd(active?.paid_out_usd ?? "0")}
      </div>

      <div className="mt-4 flex gap-2">
        <button
          onClick={() => active && onWithdraw(active.exchange)}
          disabled={!active || Number(active.available_usd) <= 0}
          className="flex-1 rounded-xl bg-white py-2 font-medium text-black disabled:opacity-30"
        >
          Вывести →
        </button>
        <button
          onClick={() => active && onStats(active.exchange)}
          disabled={!active}
          className="rounded-xl border border-neutral-700 px-4 py-2 text-sm disabled:opacity-30"
        >
          Статистика
        </button>
      </div>
    </section>
  );
}

function BalancePillLogo({
  ex,
  fallbackName,
}: {
  ex: ExchangeInfo | null | undefined;
  fallbackName: string;
}) {
  const [idx, setIdx] = useState(0);
  const url = ex?.logo_urls?.[idx];
  if (!url) {
    return (
      <span
        className="grid h-4 w-4 shrink-0 place-items-center rounded-full text-[8px] font-bold text-white"
        style={{ background: ex?.brand_color || "#404040" }}
      >
        {(ex?.name || fallbackName)[0]?.toUpperCase()}
      </span>
    );
  }
  return (
    <img
      src={url}
      alt=""
      onError={() => setIdx((i) => i + 1)}
      className="h-4 w-4 shrink-0 rounded-full object-cover"
    />
  );
}

function ExchangesList({
  exchanges,
  onConnect,
  onDisconnect,
}: {
  exchanges: ExchangeInfo[] | null;
  onConnect: (ex: ExchangeInfo) => void;
  onDisconnect: (ex: ExchangeInfo) => void;
}) {
  const [open, setOpen] = useState(false);

  if (exchanges === null) {
    return <div className="text-sm text-neutral-500">Загрузка…</div>;
  }

  const connected = exchanges.filter(
    (e) => e.status === "active" || e.status === "pending",
  );
  const others = exchanges.filter(
    (e) => e.status !== "active" && e.status !== "pending",
  );
  const hasConnected = connected.length > 0;
  const toggleLabel = hasConnected ? "Подключить ещё" : "Выбрать биржу";

  return (
    <>
      {hasConnected && (
        <ul className="space-y-2">
          {connected.map((ex) => (
            <li key={ex.slug}>
              <ExchangeRow ex={ex} onConnect={onConnect} onDisconnect={onDisconnect} />
            </li>
          ))}
        </ul>
      )}

      {others.length > 0 && (
        <>
          <button
            onClick={() => setOpen((v) => !v)}
            className={
              "flex w-full items-center justify-between rounded-xl bg-neutral-800 px-4 py-3 text-sm " +
              (hasConnected ? "mt-2" : "")
            }
          >
            <span className="text-neutral-200">{toggleLabel}</span>
            <span
              className={
                "text-neutral-500 transition-transform " + (open ? "rotate-90" : "")
              }
            >
              ›
            </span>
          </button>

          <div
            className="grid transition-[grid-template-rows] duration-300 ease-out"
            style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
          >
            <div className="overflow-hidden">
              <ul className="mt-2 space-y-2">
                {others.map((ex) => (
                  <li key={ex.slug}>
                    <ExchangeRow ex={ex} onConnect={onConnect} onDisconnect={onDisconnect} />
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </>
      )}
    </>
  );
}

function ExchangeRow({
  ex,
  onConnect,
  onDisconnect,
}: {
  ex: ExchangeInfo;
  onConnect: (ex: ExchangeInfo) => void;
  onDisconnect: (ex: ExchangeInfo) => void;
}) {
  const status = ex.status;
  const isActive = status === "active";
  const isPending = status === "pending";
  const isComingSoon = status === "coming_soon";
  const isConnectable = status === "not_connected" && ex.available;
  const isConnected = isActive || isPending;

  return (
    <div className="flex items-center gap-3 rounded-xl bg-neutral-800/70 px-3 py-2.5">
      <ExchangeLogo ex={ex} />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">{ex.name}</div>
        <div className="truncate text-[11px] text-neutral-500">
          {isActive && ex.uid &&
            (ex.slug === "binance" ? maskEmail(ex.uid) : `UID ${maskUid(ex.uid)}`)}
          {isPending && "Ожидается подтверждение"}
          {isConnectable &&
            `${ex.user_base_rate_pct}–${ex.user_base_rate_pct + 5}% кэшбэк`}
          {isComingSoon && "Интеграция в разработке"}
        </div>
      </div>
      {isActive && (
        <span className="rounded-full bg-emerald-500/15 px-2.5 py-1 text-[11px] text-emerald-300">
          активна
        </span>
      )}
      {isPending && (
        <span className="rounded-full bg-amber-500/15 px-2.5 py-1 text-[11px] text-amber-300">
          pending
        </span>
      )}
      {isConnected && (
        <button
          onClick={() => onDisconnect(ex)}
          aria-label={`Отключить ${ex.name}`}
          title="Отключить"
          className="grid h-8 w-8 place-items-center rounded-lg border border-neutral-700 text-neutral-400 hover:border-red-500/40 hover:text-red-300"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
          </svg>
        </button>
      )}
      {isConnectable && (
        <button
          onClick={() => onConnect(ex)}
          className="rounded-lg bg-white px-3 py-1.5 text-xs font-medium text-black"
        >
          Подключить
        </button>
      )}
      {isComingSoon && (
        <span className="rounded-full bg-neutral-700 px-2.5 py-1 text-[11px] text-neutral-400">
          скоро
        </span>
      )}
    </div>
  );
}

function ExchangeLogo({ ex }: { ex: ExchangeInfo }) {
  const [idx, setIdx] = useState(0);
  const url = ex.logo_urls?.[idx];
  if (!url) {
    return (
      <span
        className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-sm font-bold text-white"
        style={{ background: ex.brand_color }}
      >
        {ex.name[0]}
      </span>
    );
  }
  return (
    <span className="block h-9 w-9 shrink-0 overflow-hidden rounded-lg">
      <img
        src={url}
        alt={ex.name}
        className="h-full w-full object-cover"
        referrerPolicy="no-referrer"
        onError={() => setIdx((i) => i + 1)}
      />
    </span>
  );
}

function maskUid(uid: string): string {
  if (uid.length <= 4) return uid;
  return uid.slice(0, 2) + "•••" + uid.slice(-3);
}

function maskEmail(email: string): string {
  const at = email.indexOf("@");
  if (at < 0) return maskUid(email);
  const name = email.slice(0, at);
  const domain = email.slice(at + 1);
  const head = name.length <= 2 ? name.slice(0, 1) : name.slice(0, 2);
  return `${head}•••@${domain}`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-neutral-900 p-3 text-center">
      <div className="text-lg font-bold">{value}</div>
      <div className="mt-1 text-[10px] uppercase tracking-wider text-neutral-500">
        {label}
      </div>
    </div>
  );
}

function WithdrawalsFeed({ items }: { items: RecentWithdrawal[] | null }) {
  if (items === null) {
    return <div className="text-sm text-neutral-500">Загрузка…</div>;
  }
  if (items.length === 0) {
    return (
      <div className="text-sm text-neutral-500">
        История выплат появится после первых сделок.
      </div>
    );
  }
  return (
    <ul className="divide-y divide-neutral-800">
      {items.map((w) => (
        <li key={w.id} className="flex items-center justify-between py-2.5 text-sm">
          <div>
            <div className="text-neutral-200">{fmtUsd(w.amount_usd)}</div>
            <div className="text-[11px] text-neutral-500">
              {w.destination_type === "trc20" ? "TRC-20" : "BingX"} ·{" "}
              {w.destination_masked}
            </div>
          </div>
          <div className="text-[11px] text-neutral-500">
            {w.completed_at ? formatDate(w.completed_at) : ""}
          </div>
        </li>
      ))}
    </ul>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
}
