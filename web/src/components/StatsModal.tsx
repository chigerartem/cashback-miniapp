import { useEffect, useState } from "react";
import { getMyStats, type ExchangeInfo, type StatsResponse } from "../api";
import { createPortal } from "react-dom";
import { useBodyScrollLock } from "../hooks/useBodyScrollLock";
import { fmtUsd } from "../format";

type Props = {
  open: boolean;
  exchange: string | null;
  exchangeMeta: ExchangeInfo | null;
  onClose: () => void;
};

const KIND_LABELS: Record<string, string> = {
  self: "Свой кешбэк",
  referral: "От реферала",
  partner: "Партнёрская доля",
};

const KIND_COLORS: Record<string, string> = {
  self: "bg-emerald-500/15 text-emerald-300",
  referral: "bg-sky-500/15 text-sky-300",
  partner: "bg-amber-500/15 text-amber-300",
};

export default function StatsModal({ open, exchange, exchangeMeta, onClose }: Props) {
  const [data, setData] = useState<StatsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(30);

  useBodyScrollLock(open);

  useEffect(() => {
    if (!open || !exchange) return;
    setLoading(true);
    setError(null);
    getMyStats(exchange, days)
      .then(setData)
      .catch((e) => setError(String(e?.message || e)))
      .finally(() => setLoading(false));
  }, [open, exchange, days]);

  if (!open || !exchange) return null;

  const exchangeName = exchangeMeta?.name || exchange.toUpperCase();
  const maxDaily = Math.max(
    1,
    ...(data?.daily.map((d) => Number(d.amount_usd) || 0) || [1]),
  );

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-end justify-center overscroll-contain bg-black/85 backdrop-blur-md"
      onTouchMove={(e) => {
        if (e.target === e.currentTarget) e.preventDefault();
      }}
    >
      <div className="flex h-[88vh] w-full max-w-md flex-col rounded-t-3xl bg-neutral-900 sm:h-auto sm:max-h-[80vh] sm:rounded-3xl sm:mb-4">
        <div className="flex shrink-0 items-center justify-between border-b border-neutral-800 p-5">
          <div>
            <div className="text-base font-semibold">Статистика</div>
            <div className="text-xs text-neutral-500">{exchangeName}</div>
          </div>
          <button
            onClick={onClose}
            className="text-xl text-neutral-500 hover:text-neutral-200"
            aria-label="Закрыть"
          >
            ×
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {/* Period switcher */}
          <div className="mb-4 flex gap-1.5 rounded-xl bg-neutral-800 p-1">
            {[7, 30, 90].map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={
                  "flex-1 rounded-lg py-1.5 text-xs " +
                  (days === d ? "bg-neutral-700 text-white font-medium" : "text-neutral-400")
                }
              >
                {d} дней
              </button>
            ))}
          </div>

          {loading && !data && (
            <div className="py-10 text-center text-sm text-neutral-500">Загрузка…</div>
          )}
          {error && (
            <div className="rounded-xl bg-red-900/30 p-3 text-sm text-red-300">{error}</div>
          )}

          {data && !loading && (
            <>
              {/* Total */}
              <div className="mb-4 rounded-2xl bg-neutral-800 p-5">
                <div className="text-[11px] uppercase tracking-wider text-neutral-500">
                  Кешбэк за {data.period_days} дней
                </div>
                <div className="mt-1 text-3xl font-bold">
                  {fmtUsd(data.total_cashback_usd)}
                </div>
                {(data.by_kind.self || data.by_kind.referral) && (
                  <div className="mt-3 flex flex-wrap gap-3 text-xs text-neutral-400">
                    {data.by_kind.self && (
                      <span>
                        Свой:{" "}
                        <span className="text-emerald-300">{fmtUsd(data.by_kind.self)}</span>
                      </span>
                    )}
                    {data.by_kind.referral && (
                      <span>
                        Рефералы:{" "}
                        <span className="text-sky-300">{fmtUsd(data.by_kind.referral)}</span>
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Daily bars */}
              {data.daily.length > 0 && (
                <div className="mb-4 rounded-2xl bg-neutral-800 p-4">
                  <div className="mb-3 text-xs uppercase tracking-wider text-neutral-500">
                    По дням
                  </div>
                  <div className="flex h-24 items-end gap-0.5">
                    {data.daily.map((d, i) => {
                      const v = Number(d.amount_usd) || 0;
                      const h = Math.max(2, (v / maxDaily) * 100);
                      return (
                        <div
                          key={d.date || i}
                          className="flex-1 rounded-t bg-emerald-500/70"
                          style={{ height: `${h}%` }}
                          title={`${d.date}: ${fmtUsd(d.amount_usd)}`}
                        />
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Entries list */}
              <div className="rounded-2xl bg-neutral-800">
                <div className="border-b border-neutral-700/50 p-4 text-xs uppercase tracking-wider text-neutral-500">
                  История начислений
                </div>
                {data.entries.length === 0 ? (
                  <div className="p-6 text-center text-sm text-neutral-500">
                    Пока пусто — начислений за выбранный период не было.
                  </div>
                ) : (
                  <ul className="divide-y divide-neutral-700/50">
                    {data.entries.map((e) => (
                      <li key={e.id} className="flex items-center justify-between gap-3 p-4">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span
                              className={
                                "rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider " +
                                (KIND_COLORS[e.kind] || "bg-neutral-700 text-neutral-300")
                              }
                            >
                              {KIND_LABELS[e.kind] || e.kind}
                            </span>
                            {e.vip_tier_at_time && (
                              <span className="text-[11px] text-neutral-500">
                                {e.vip_tier_at_time}
                              </span>
                            )}
                          </div>
                          <div className="mt-1 text-xs text-neutral-500">{e.source_date}</div>
                        </div>
                        <div className="shrink-0 text-base font-semibold">
                          {fmtUsd(e.amount_usd)}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
