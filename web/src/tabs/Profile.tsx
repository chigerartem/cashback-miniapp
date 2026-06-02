import { useEffect, useState } from "react";
import {
  getLeaderboard,
  getWithdrawals,
  type LeaderboardEntry,
  type MeResponse,
  type Withdrawal,
} from "../api";
import UserAvatar, { tgHandle } from "../components/UserAvatar";
import { fmtUsd } from "../format";

const TIER_LABEL: Record<string, string> = {
  bronze: "Bronze",
  silver: "Silver",
  gold: "Gold",
  platinum: "Platinum",
  diamond: "Diamond",
  vip: "VIP",
};

export default function Profile({ me }: { me: MeResponse }) {
  const [leaders, setLeaders] = useState<LeaderboardEntry[] | null>(null);
  const [period, setPeriod] = useState<"all" | "30d">("all");
  const [history, setHistory] = useState<Withdrawal[] | null>(null);

  useEffect(() => {
    // Не сбрасываем leaders в null между переключениями period — иначе
    // список схлопывается в одну строку «Загрузка…», высота страницы
    // меняется, и скролл прыгает в начало. Старые строки остаются на
    // месте до прихода новых, потом тихо заменяются.
    getLeaderboard(period, 50).then(setLeaders).catch(() => setLeaders([]));
  }, [period]);

  useEffect(() => {
    getWithdrawals(20).then(setHistory).catch(() => setHistory([]));
  }, []);

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-col items-center gap-2 py-4">
        <UserAvatar name={me.user.name} size={88} />
        <div className="mt-2 text-lg font-semibold">{me.user.name}</div>
        <div className="text-xs text-neutral-500">{tgHandle(me.user)}</div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <Stat label="Общая экономия" value={fmtUsd(me.balance.accrued_usd)} />
        <Stat label="Реф. доход" value={fmtUsd(0)} />
        <Stat label="Выведено" value={fmtUsd(me.balance.paid_out_usd)} />
      </div>

      <section className="rounded-2xl bg-neutral-900 p-5">
        <h2 className="mb-3 text-base font-semibold">Мои выплаты</h2>
        <WithdrawalsHistory items={history} />
      </section>

      <section className="rounded-2xl bg-neutral-900 p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold">Лидерборд</h2>
          <div className="flex gap-1 rounded-lg bg-neutral-800 p-1 text-xs">
            <PeriodBtn label="30 дней" active={period === "30d"} onClick={() => setPeriod("30d")} />
            <PeriodBtn label="Всё время" active={period === "all"} onClick={() => setPeriod("all")} />
          </div>
        </div>
        <Leaderboard items={leaders} />
      </section>
    </div>
  );
}

function PeriodBtn({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={
        "rounded-md px-2.5 py-1 transition " +
        (active ? "bg-neutral-700 text-white" : "text-neutral-400")
      }
    >
      {label}
    </button>
  );
}

function Leaderboard({ items }: { items: LeaderboardEntry[] | null }) {
  if (items === null) {
    return <div className="text-sm text-neutral-500">Загрузка…</div>;
  }
  if (items.length === 0) {
    return (
      <div className="text-sm text-neutral-500">
        Рейтинг участников появится после первых сделок.
      </div>
    );
  }
  return (
    <ul className="divide-y divide-neutral-800">
      {items.map((e) => (
        <li key={e.rank} className="flex items-center justify-between py-2.5">
          <div className="flex items-center gap-3">
            <span
              className={
                "grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-semibold " +
                rankColor(e.rank)
              }
            >
              {e.rank}
            </span>
            <div>
              <div className="text-sm text-neutral-200">{e.name}</div>
              <div className="text-[11px] uppercase tracking-wider text-neutral-500">
                {TIER_LABEL[e.vip_tier] ?? e.vip_tier}
              </div>
            </div>
          </div>
          <div className="text-sm font-semibold">{fmtUsd(e.earned_usd)}</div>
        </li>
      ))}
    </ul>
  );
}

function rankColor(rank: number): string {
  if (rank === 1) return "bg-amber-500/20 text-amber-300";
  if (rank === 2) return "bg-neutral-400/20 text-neutral-200";
  if (rank === 3) return "bg-orange-600/20 text-orange-300";
  return "bg-neutral-800 text-neutral-400";
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

const STATUS_LABEL: Record<Withdrawal["status"], string> = {
  pending: "В очереди",
  processing: "В обработке",
  done: "Выплачено",
  failed: "Отклонено",
};

const STATUS_STYLE: Record<Withdrawal["status"], string> = {
  pending: "bg-neutral-800 text-neutral-300",
  processing: "bg-amber-500/15 text-amber-300",
  done: "bg-emerald-500/15 text-emerald-300",
  failed: "bg-red-500/15 text-red-300",
};

function WithdrawalsHistory({ items }: { items: Withdrawal[] | null }) {
  if (items === null) {
    return <div className="text-sm text-neutral-500">Загрузка…</div>;
  }
  if (items.length === 0) {
    return (
      <div className="text-sm text-neutral-500">
        Здесь будет история ваших выплат.
      </div>
    );
  }
  return (
    <ul className="divide-y divide-neutral-800">
      {items.map((w) => (
        <li key={w.id} className="flex items-center justify-between py-3 text-sm">
          <div>
            <div className="font-medium text-neutral-200">{fmtUsd(w.amount_usd)}</div>
            <div className="mt-0.5 text-[11px] text-neutral-500">
              {w.destination_type === "trc20" ? "TRC-20" : "BingX UID"} ·{" "}
              {w.destination_masked} · {formatDate(w.created_at)}
            </div>
            {w.status === "failed" && w.failure_reason && (
              <div className="mt-1 text-[11px] text-red-400">{w.failure_reason}</div>
            )}
          </div>
          <span
            className={
              "shrink-0 rounded-full px-2.5 py-1 text-[11px] " + STATUS_STYLE[w.status]
            }
          >
            {STATUS_LABEL[w.status]}
          </span>
        </li>
      ))}
    </ul>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
}
