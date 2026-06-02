/**
 * Client-side demo data + a small mutable store.
 *
 * When the app is built with `VITE_DEMO=true`, `api.ts` serves everything from
 * here instead of calling a backend — so the Mini App runs as a fully static
 * site (e.g. GitHub Pages) and stays interactive: connecting an exchange,
 * disconnecting, and requesting a withdrawal all mutate this in-memory state.
 *
 * Nothing here is real: figures, names and UIDs are fabricated for the showcase.
 */
import type {
  BingxStatus,
  ConnectResult,
  CreateWithdrawalBody,
  CreateWithdrawalResult,
  ExchangeBalance,
  ExchangeInfo,
  GlobalStats,
  LeaderboardEntry,
  MeResponse,
  RecentWithdrawal,
  ReferralInfo,
  StatsResponse,
  Withdrawal,
  WithdrawalLimits,
} from "./api";

type Fees = ExchangeInfo["fees"];

type CatalogEntry = {
  slug: string;
  name: string;
  brand_color: string;
  domain: string;
  logo: string;
  fees: Fees;
  broker_rate_pct: number;
  user_base_rate_pct: number;
};

const CATALOG: CatalogEntry[] = [
  {
    slug: "bingx", name: "BingX", brand_color: "#1f6cf0", domain: "bingx.com",
    logo: "https://coin-images.coingecko.com/markets/images/812/large/YtFwQwJr_400x400.jpg",
    fees: { spot_taker_pct: 0.1, spot_maker_pct: 0.1, perp_taker_pct: 0.05, perp_maker_pct: 0.02 },
    broker_rate_pct: 55, user_base_rate_pct: 30,
  },
  {
    slug: "binance", name: "Binance", brand_color: "#F0B90B", domain: "binance.com",
    logo: "https://www.google.com/s2/favicons?domain=binance.com&sz=128",
    fees: { spot_taker_pct: 0.1, spot_maker_pct: 0.1, perp_taker_pct: 0.05, perp_maker_pct: 0.02 },
    broker_rate_pct: 40, user_base_rate_pct: 5,
  },
  {
    slug: "bitget", name: "Bitget", brand_color: "#00E5FF", domain: "bitget.com",
    logo: "https://www.google.com/s2/favicons?domain=bitget.com&sz=128",
    fees: { spot_taker_pct: 0.1, spot_maker_pct: 0.1, perp_taker_pct: 0.06, perp_maker_pct: 0.02 },
    broker_rate_pct: 0, user_base_rate_pct: 10,
  },
  {
    slug: "mexc", name: "MEXC", brand_color: "#0B61FF", domain: "mexc.com",
    logo: "https://www.google.com/s2/favicons?domain=mexc.com&sz=128",
    fees: { spot_taker_pct: 0.05, spot_maker_pct: 0.0, perp_taker_pct: 0.02, perp_maker_pct: 0.0 },
    broker_rate_pct: 50, user_base_rate_pct: 30,
  },
  {
    slug: "bydfi", name: "BYDFi", brand_color: "#F5C518", domain: "bydfi.com",
    logo: "https://www.google.com/s2/favicons?domain=bydfi.com&sz=128",
    fees: { spot_taker_pct: 0.1, spot_maker_pct: 0.1, perp_taker_pct: 0.06, perp_maker_pct: 0.02 },
    broker_rate_pct: 60, user_base_rate_pct: 35,
  },
];

const logoUrls = (c: CatalogEntry): string[] => [
  c.logo,
  `https://icons.duckduckgo.com/ip3/${c.domain}.ico`,
  `https://www.google.com/s2/favicons?domain=${c.domain}&sz=128`,
];

type Bal = { accrued: number; paid_out: number; reserved: number };

type Store = {
  accounts: Record<string, { uid: string; status: "active" | "pending" }>;
  balances: Record<string, Bal>;
  withdrawals: Withdrawal[];
};

function daysAgo(d: number): string {
  return new Date(Date.now() - d * 86_400_000).toISOString();
}
function hoursAgo(h: number): string {
  return new Date(Date.now() - h * 3_600_000).toISOString();
}
function s2(n: number): string {
  return n.toFixed(2);
}
function delay<T>(value: T): Promise<T> {
  // A touch of latency so loading states are visible in the demo.
  return new Promise((resolve) => setTimeout(() => resolve(value), 180));
}

const store: Store = {
  accounts: {
    bingx: { uid: "87654321", status: "active" },
    binance: { uid: "alex@demo.io", status: "active" },
  },
  balances: {
    bingx: { accrued: 142.5, paid_out: 40, reserved: 0 },
    binance: { accrued: 18.3, paid_out: 0, reserved: 0 },
  },
  withdrawals: [
    {
      id: "w-demo-1", amount_usd: "40.00",
      destination_type: "trc20", destination_masked: "TKx9***h7Qm",
      status: "done", tx_hash: "a1b2c3d4e5f6a7b8c9d0", failure_reason: null,
      created_at: daysAgo(14), completed_at: daysAgo(14),
    },
  ],
};

function balOf(slug: string): Bal {
  return store.balances[slug] ?? { accrued: 0, paid_out: 0, reserved: 0 };
}
function available(b: Bal): number {
  return Math.max(0, b.accrued - b.paid_out - b.reserved);
}

function exchangeBalances(): ExchangeBalance[] {
  return Object.keys(store.accounts).map((slug) => {
    const b = balOf(slug);
    return {
      exchange: slug,
      accrued_usd: s2(b.accrued),
      paid_out_usd: s2(b.paid_out),
      reserved_usd: s2(b.reserved),
      available_usd: s2(available(b)),
    };
  });
}

export function getMe(): Promise<MeResponse> {
  const totals = Object.keys(store.accounts).reduce(
    (acc, slug) => {
      const b = balOf(slug);
      acc.accrued += b.accrued;
      acc.paid_out += b.paid_out;
      acc.reserved += b.reserved;
      return acc;
    },
    { accrued: 0, paid_out: 0, reserved: 0 },
  );
  return delay<MeResponse>({
    user: {
      id: "demo-user",
      tg_id: 100200300,
      tg_username: "alex_demo",
      name: "Алекс",
      ref_code: "DEMO1234",
      vip_tier: "gold",
      language: "ru",
    },
    balance: {
      accrued_usd: s2(totals.accrued),
      paid_out_usd: s2(totals.paid_out),
      reserved_usd: s2(totals.reserved),
      available_usd: s2(totals.accrued - totals.paid_out - totals.reserved),
    },
    balances: exchangeBalances(),
    exchanges: Object.entries(store.accounts).map(([slug, a]) => ({
      exchange: slug,
      uid: a.uid,
      status: a.status,
    })),
    withdrawal: { min_usd: 1, daily_limit_usd: 5000, monthly_limit_usd: 20000, cooldown_minutes: 30 },
  });
}

export function getExchanges(): Promise<ExchangeInfo[]> {
  const list: ExchangeInfo[] = CATALOG.map((c) => ({
    slug: c.slug,
    name: c.name,
    brand_color: c.brand_color,
    domain: c.domain,
    logo_urls: logoUrls(c),
    available: true,
    referral_url: null,
    status: (store.accounts[c.slug]?.status ?? "not_connected") as ExchangeInfo["status"],
    uid: store.accounts[c.slug]?.uid ?? null,
    fees: c.fees,
    broker_rate_pct: c.broker_rate_pct,
    user_base_rate_pct: c.user_base_rate_pct,
  }));
  list.sort(
    (a, b) => Number(b.available) - Number(a.available) || b.user_base_rate_pct - a.user_base_rate_pct,
  );
  return delay<ExchangeInfo[]>(list);
}

export function getMyStats(exchange?: string, days = 30): Promise<StatsResponse> {
  const daily = Array.from({ length: 7 }, (_, i) => ({
    date: new Date(Date.now() - (6 - i) * 86_400_000).toISOString().slice(0, 10),
    amount_usd: s2(3 + (i % 3) * 2.4 + (i === 6 ? 5 : 0)),
  }));
  return delay<StatsResponse>({
    period_days: days,
    exchange: exchange ?? null,
    total_cashback_usd: "142.50",
    by_kind: { self: "128.20", referral: "14.30" },
    daily,
    entries: [
      { id: "e1", exchange: "bingx", kind: "self", amount_usd: "8.40", rate_applied: "0.32", vip_tier_at_time: "gold", source_date: daysAgo(1).slice(0, 10), created_at: daysAgo(1) },
      { id: "e2", exchange: "bingx", kind: "referral", amount_usd: "1.26", rate_applied: "0.15", vip_tier_at_time: "gold", source_date: daysAgo(1).slice(0, 10), created_at: daysAgo(1) },
      { id: "e3", exchange: "binance", kind: "self", amount_usd: "2.10", rate_applied: "0.07", vip_tier_at_time: "gold", source_date: daysAgo(2).slice(0, 10), created_at: daysAgo(2) },
    ],
  });
}

export function connectExchange(slug: string, uid: string): Promise<ConnectResult> {
  store.accounts[slug] = { uid, status: "active" };
  if (!store.balances[slug]) store.balances[slug] = { accrued: 0, paid_out: 0, reserved: 0 };
  return delay<ConnectResult>({ status: "active", uid, direct_invitation: true });
}

export function disconnectExchange(slug: string): Promise<{ deleted: true; slug: string }> {
  delete store.accounts[slug];
  delete store.balances[slug];
  return delay<{ deleted: true; slug: string }>({ deleted: true, slug });
}

export function getBingxStatus(): Promise<BingxStatus> {
  const acc = store.accounts.bingx;
  return delay<BingxStatus>(acc ? { status: acc.status, uid: acc.uid } : { status: "not_connected" });
}

export function getReferral(): Promise<ReferralInfo> {
  return delay<ReferralInfo>({
    ref_code: "DEMO1234",
    ref_url: `https://t.me/${import.meta.env.VITE_BOT_USERNAME || "your_cashback_bot"}?start=ref_DEMO1234`,
    invited_count: 7,
    earned_usd: "14.30",
    referral_rate_pct: 15,
  });
}

export function getGlobalStats(): Promise<GlobalStats> {
  return delay<GlobalStats>({ total_paid_out_usd: "184213.50", total_traders: 2417, volume_30d_usd: "5120000" });
}

export function getRecentWithdrawals(limit = 20): Promise<RecentWithdrawal[]> {
  const rows: RecentWithdrawal[] = [
    { id: "r1", amount_usd: "312.40", destination_type: "trc20", destination_masked: "TQp7***x2Lk", completed_at: hoursAgo(2) },
    { id: "r2", amount_usd: "58.10", destination_type: "trc20", destination_masked: "TYa3***m9Rd", completed_at: hoursAgo(6) },
    { id: "r3", amount_usd: "146.00", destination_type: "bingx_uid", destination_masked: "44***81", completed_at: hoursAgo(11) },
    { id: "r4", amount_usd: "27.85", destination_type: "trc20", destination_masked: "TBn2***q4Vw", completed_at: hoursAgo(20) },
    { id: "r5", amount_usd: "203.50", destination_type: "trc20", destination_masked: "TLz8***c1Hg", completed_at: daysAgo(2) },
  ];
  return delay<RecentWithdrawal[]>(rows.slice(0, limit));
}

const LB_NAMES: [string, string][] = [
  ["Дмитрий К.", "vip"], ["@cryptopro", "vip"], ["Анна М.", "vip"], ["Sergei L.", "diamond"],
  ["@moon_trader", "diamond"], ["Виктор", "diamond"], ["Aleksandr P.", "platinum"], ["Мария", "platinum"],
  ["@whale_88", "platinum"], ["Игорь Т.", "gold"], ["Алексей", "gold"], ["@hodl_master", "gold"],
  ["Екатерина", "gold"], ["Roman S.", "silver"], ["@day_trade", "silver"], ["Павел", "silver"],
  ["Наталья В.", "bronze"], ["@scalp_king", "bronze"], ["Олег", "bronze"], ["Аноним", "bronze"],
];

export function getLeaderboard(period: "all" | "30d" = "all", limit = 50): Promise<LeaderboardEntry[]> {
  const factor = period === "30d" ? 0.28 : 1;
  const rows: LeaderboardEntry[] = LB_NAMES.slice(0, limit).map(([name, vip], i) => ({
    rank: i + 1,
    name,
    vip_tier: vip,
    earned_usd: s2(Math.max(8, 12400 * Math.pow(0.86, i) * factor)),
  }));
  return delay<LeaderboardEntry[]>(rows);
}

export function getWithdrawalLimits(): Promise<WithdrawalLimits> {
  const totalAvail = Object.keys(store.accounts).reduce((sum, slug) => sum + available(balOf(slug)), 0);
  return delay<WithdrawalLimits>({
    available_usd: s2(totalAvail),
    min_usd: 1,
    daily_limit_usd: 5000,
    monthly_limit_usd: 20000,
    cooldown_minutes: 30,
  });
}

export function getWithdrawals(limit = 50): Promise<Withdrawal[]> {
  return delay<Withdrawal[]>(store.withdrawals.slice(0, limit));
}

export function createWithdrawal(body: CreateWithdrawalBody): Promise<CreateWithdrawalResult> {
  const amount = Number(body.amount_usd) || 0;
  const b = balOf(body.exchange);
  b.reserved += amount;
  store.balances[body.exchange] = b;
  const w: Withdrawal = {
    id: `w-demo-${store.withdrawals.length + 1}`,
    amount_usd: s2(amount),
    destination_type: body.destination_type,
    destination_masked: maskDemo(body.destination_value),
    status: "pending",
    tx_hash: null,
    failure_reason: null,
    created_at: new Date().toISOString(),
    completed_at: null,
  };
  store.withdrawals = [w, ...store.withdrawals];
  return delay<CreateWithdrawalResult>({ id: w.id, status: "pending", amount_usd: w.amount_usd, created_at: w.created_at });
}

function maskDemo(value: string): string {
  if (!value) return "***";
  if (value.length <= 6) return "***" + value.slice(-2);
  return value.slice(0, 4) + "***" + value.slice(-4);
}
