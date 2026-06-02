import * as demo from "./demo";

const API_BASE = import.meta.env.VITE_API_BASE || "";
// Static demo build (e.g. GitHub Pages): serve everything from ./demo, no server.
const DEMO = import.meta.env.VITE_DEMO === "true";

function authHeader(): HeadersInit {
  const initData = window.Telegram?.WebApp?.initData ?? "";
  return initData ? { Authorization: `tma ${initData}` } : {};
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.headers || {}),
      ...authHeader(),
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  if (!r.ok) {
    let detail = "";
    try {
      const data = await r.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      detail = await r.text();
    }
    throw new ApiError(r.status, detail || r.statusText);
  }
  return r.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

// ── /api/me ──────────────────────────────────────────────────────────────

export type ExchangeAccount = {
  exchange: string;
  uid: string;
  status: "pending" | "active" | "revoked";
};

export type ExchangeBalance = {
  exchange: string;
  accrued_usd: string;
  paid_out_usd: string;
  reserved_usd: string;
  available_usd: string;
};

export type MeResponse = {
  user: {
    id: string;
    tg_id: number;
    tg_username: string | null;
    name: string;
    ref_code: string;
    vip_tier: string;
    language: string;
  };
  /** Суммарный баланс юзера по всем биржам (для VIP-прогресса). */
  balance: {
    accrued_usd: string;
    paid_out_usd: string;
    reserved_usd: string;
    available_usd: string;
  };
  /** Балансы per-биржа — основной источник для UI. */
  balances: ExchangeBalance[];
  exchanges: ExchangeAccount[];
  withdrawal: {
    min_usd: number;
    daily_limit_usd: number;
    monthly_limit_usd: number;
    cooldown_minutes: number;
  };
};

export const getMe = () => (DEMO ? demo.getMe() : jsonFetch<MeResponse>("/api/me"));

export type StatsEntry = {
  id: string;
  exchange: string;
  kind: "self" | "referral" | "partner";
  amount_usd: string;
  rate_applied: string | null;
  vip_tier_at_time: string | null;
  source_date: string | null;
  created_at: string;
};

export type StatsResponse = {
  period_days: number;
  exchange: string | null;
  total_cashback_usd: string;
  by_kind: Partial<Record<"self" | "referral" | "partner", string>>;
  daily: { date: string | null; amount_usd: string }[];
  entries: StatsEntry[];
};

export const getMyStats = (exchange?: string, days = 30) => {
  if (DEMO) return demo.getMyStats(exchange, days);
  const params = new URLSearchParams();
  if (exchange) params.set("exchange", exchange);
  params.set("days", String(days));
  return jsonFetch<StatsResponse>(`/api/me/stats?${params.toString()}`);
};

// ── /api/exchanges ───────────────────────────────────────────────────────

export type ExchangeFees = {
  spot_taker_pct: number;
  spot_maker_pct: number;
  perp_taker_pct: number;
  perp_maker_pct: number;
};

export type ExchangeInfo = {
  slug: string;
  name: string;
  brand_color: string;
  domain: string;
  logo_urls: string[];
  available: boolean;
  referral_url: string | null;
  status: "not_connected" | "pending" | "active" | "coming_soon";
  uid: string | null;
  fees: ExchangeFees;
  broker_rate_pct: number;
  /** Базовый % юзеру от его fee без VIP-бонуса: bingx 30, binance 5. */
  user_base_rate_pct: number;
};

export const getExchanges = () =>
  DEMO ? demo.getExchanges() : jsonFetch<ExchangeInfo[]>("/api/exchanges");

export type ConnectResult = {
  status: "pending" | "active";
  uid: string;
  direct_invitation?: boolean;
};

export const connectExchange = (slug: string, uid: string) =>
  DEMO
    ? demo.connectExchange(slug, uid)
    : jsonFetch<ConnectResult>(`/api/exchanges/${slug}/connect`, {
        method: "POST",
        body: JSON.stringify({ uid }),
      });

/** @deprecated Use connectExchange("bingx", uid) instead. */
export const connectBingx = (uid: string) => connectExchange("bingx", uid);

export const disconnectExchange = (slug: string) =>
  DEMO
    ? demo.disconnectExchange(slug)
    : jsonFetch<{ deleted: true; slug: string }>(`/api/exchanges/${slug}`, {
        method: "DELETE",
      });

export type BingxStatus =
  | { status: "not_connected" }
  | { status: "pending" | "active"; uid: string };

export const getBingxStatus = () =>
  DEMO ? demo.getBingxStatus() : jsonFetch<BingxStatus>("/api/exchanges/bingx/status");

// ── /api/referral ────────────────────────────────────────────────────────

export type ReferralInfo = {
  ref_code: string;
  ref_url: string;
  invited_count: number;
  earned_usd: string;
  referral_rate_pct: number;
};

export const getReferral = () =>
  DEMO ? demo.getReferral() : jsonFetch<ReferralInfo>("/api/referral");

// ── /api/stats ───────────────────────────────────────────────────────────

export type GlobalStats = {
  total_paid_out_usd: string;
  total_traders: number;
  volume_30d_usd: string;
};

export const getGlobalStats = () =>
  DEMO ? demo.getGlobalStats() : jsonFetch<GlobalStats>("/api/stats/global");

export type RecentWithdrawal = {
  id: string;
  amount_usd: string;
  destination_type: "bingx_uid" | "trc20";
  destination_masked: string;
  completed_at: string | null;
};

export const getRecentWithdrawals = (limit = 20) =>
  DEMO
    ? demo.getRecentWithdrawals(limit)
    : jsonFetch<RecentWithdrawal[]>(`/api/stats/recent_withdrawals?limit=${limit}`);

export type LeaderboardEntry = {
  rank: number;
  name: string;
  vip_tier: string;
  earned_usd: string;
};

export const getLeaderboard = (period: "all" | "30d" = "all", limit = 50) =>
  DEMO
    ? demo.getLeaderboard(period, limit)
    : jsonFetch<LeaderboardEntry[]>(`/api/leaderboard?period=${period}&limit=${limit}`);

// ── /api/withdrawals ─────────────────────────────────────────────────────

export type WithdrawalLimits = {
  available_usd: string;
  min_usd: number;
  daily_limit_usd: number;
  monthly_limit_usd: number;
  cooldown_minutes: number;
};

export const getWithdrawalLimits = () =>
  DEMO ? demo.getWithdrawalLimits() : jsonFetch<WithdrawalLimits>("/api/withdrawals/limits");

export type Withdrawal = {
  id: string;
  amount_usd: string;
  destination_type: "bingx_uid" | "trc20";
  destination_masked: string;
  status: "pending" | "processing" | "done" | "failed";
  tx_hash: string | null;
  failure_reason: string | null;
  created_at: string;
  completed_at: string | null;
};

export const getWithdrawals = (limit = 50) =>
  DEMO ? demo.getWithdrawals(limit) : jsonFetch<Withdrawal[]>(`/api/withdrawals?limit=${limit}`);

export type CreateWithdrawalBody = {
  amount_usd: string;
  exchange: string;
  destination_type: "bingx_uid" | "trc20";
  destination_value: string;
};

export type CreateWithdrawalResult = {
  id: string;
  status: "pending";
  amount_usd: string;
  created_at: string;
};

export const createWithdrawal = (body: CreateWithdrawalBody) =>
  DEMO
    ? demo.createWithdrawal(body)
    : jsonFetch<CreateWithdrawalResult>("/api/withdrawals", {
        method: "POST",
        body: JSON.stringify(body),
      });
