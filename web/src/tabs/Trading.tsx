import { useEffect, useMemo, useRef, useState } from "react";
import type { ExchangeInfo, MeResponse } from "../api";
import { getExchanges } from "../api";
import { fmtUsd } from "../format";
import { makeSelectionTicker } from "../haptics";

const VOL_MIN = 5;
const VOL_MAX = 100_000;
const VOL_SLIDER_STEPS = 1000;

function sliderToVolume(s: number): number {
  const ratio = Math.max(0, Math.min(1, s / VOL_SLIDER_STEPS));
  const raw = VOL_MIN * Math.pow(VOL_MAX / VOL_MIN, ratio);
  return snapVolume(raw);
}

function volumeToSlider(v: number): number {
  const r = Math.log(v / VOL_MIN) / Math.log(VOL_MAX / VOL_MIN);
  return Math.round(VOL_SLIDER_STEPS * Math.max(0, Math.min(1, r)));
}

function snapVolume(v: number): number {
  if (v < 20) return Math.max(VOL_MIN, Math.round(v));
  if (v < 50) return Math.round(v / 5) * 5;
  if (v < 200) return Math.round(v / 10) * 10;
  if (v < 500) return Math.round(v / 25) * 25;
  if (v < 1000) return Math.round(v / 50) * 50;
  if (v < 5000) return Math.round(v / 100) * 100;
  if (v < 10_000) return Math.round(v / 250) * 250;
  if (v < 50_000) return Math.round(v / 500) * 500;
  return Math.round(v / 1000) * 1000;
}

// Сделок в день — логарифмическая шкала: 1-10 занимает первую половину ползунка
// (при ratio 0.5 → 10 сделок), 10-100 — вторую. Большинство юзеров делают 1-10
// сделок, поэтому им нужна точность на малых числах, а не равномерная шкала 1-100.
const TRADES_MIN = 1;
const TRADES_MAX = 100;
const TRADES_SLIDER_STEPS = 1000;

function sliderToTrades(s: number): number {
  const ratio = Math.max(0, Math.min(1, s / TRADES_SLIDER_STEPS));
  const raw = TRADES_MIN * Math.pow(TRADES_MAX / TRADES_MIN, ratio);
  return snapTrades(raw);
}

function tradesToSlider(v: number): number {
  const r = Math.log(v / TRADES_MIN) / Math.log(TRADES_MAX / TRADES_MIN);
  return Math.round(TRADES_SLIDER_STEPS * Math.max(0, Math.min(1, r)));
}

function snapTrades(v: number): number {
  if (v <= 10) return Math.max(TRADES_MIN, Math.round(v)); // 1..10 по одному
  if (v < 20) return Math.round(v / 2) * 2;                // 12,14,16,18
  if (v < 50) return Math.round(v / 5) * 5;                // 20,25,...,45
  return Math.round(v / 10) * 10;                          // 50,60,...,100
}

// bonus — VIP-надбавка в % сверх базовой ставки биржи. Итоговый % = база биржи
// (user_base_rate_pct: bingx 30, binance 5) + bonus. Базу берём из выбранной биржи.
const TIERS = [
  { key: "bronze",   label: "Bronze",   bonus: 0, threshold: 0     },
  { key: "silver",   label: "Silver",   bonus: 1, threshold: 50    },
  { key: "gold",     label: "Gold",     bonus: 2, threshold: 250   },
  { key: "platinum", label: "Platinum", bonus: 3, threshold: 1000  },
  { key: "diamond",  label: "Diamond",  bonus: 4, threshold: 5000  },
  { key: "vip",      label: "VIP",      bonus: 5, threshold: 20000 },
];

const LEVERAGES = [1, 5, 10, 25, 50, 100];

type Mode = "spot" | "perp_maker" | "perp_taker";

const MODES: { key: Mode; label: string; short: string; usesLeverage: boolean }[] = [
  { key: "perp_taker", label: "Фьючерсы (taker)", short: "Фьюч. taker", usesLeverage: true  },
  { key: "perp_maker", label: "Фьючерсы (maker)", short: "Фьюч. maker", usesLeverage: true  },
  { key: "spot",       label: "Спот",             short: "Спот",        usesLeverage: false },
];

function feeRateFor(ex: ExchangeInfo, mode: Mode): number {
  switch (mode) {
    case "spot": return ex.fees.spot_taker_pct / 100;
    case "perp_maker": return ex.fees.perp_maker_pct / 100;
    case "perp_taker": return ex.fees.perp_taker_pct / 100;
  }
}

export default function Trading({ me }: { me: MeResponse }) {
  const [leverage, setLeverage] = useState(10);
  const [volume, setVolume] = useState(500);
  const [tradesPerDay, setTradesPerDay] = useState(5);
  const [mode, setMode] = useState<Mode>("perp_taker");
  const [exchanges, setExchanges] = useState<ExchangeInfo[]>([]);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);

  useEffect(() => {
    getExchanges().then((list) => {
      setExchanges(list);
      // Prefer the user's connected exchange; otherwise first available.
      const connected = list.find((e) => e.status === "active" || e.status === "pending");
      setSelectedSlug(connected?.slug || list.find((e) => e.available)?.slug || list[0]?.slug || null);
    }).catch(() => {});
  }, []);

  const selected = useMemo(
    () => exchanges.find((e) => e.slug === selectedSlug) ?? null,
    [exchanges, selectedSlug],
  );

  const modeObj = MODES.find((m) => m.key === mode)!;
  const currentTier = TIERS.find((t) => t.key === me.user.vip_tier) ?? TIERS[0];
  const currentIdx = TIERS.indexOf(currentTier);
  const nextTier = TIERS[currentIdx + 1] ?? null;

  // База кешбэка зависит от выбранной биржи (bingx 30%, binance 5%); VIP добавляет сверху.
  const baseRate = (selected?.user_base_rate_pct ?? 30) / 100;
  const curRate = baseRate + currentTier.bonus / 100;
  const nextRate = nextTier ? baseRate + nextTier.bonus / 100 : 0;

  const paidOut = Number(me.balance.paid_out_usd) || 0;
  const progress = nextTier
    ? Math.min(100, Math.max(0,
        ((paidOut - currentTier.threshold) / (nextTier.threshold - currentTier.threshold)) * 100))
    : 100;
  const toNext = nextTier ? Math.max(0, nextTier.threshold - paidOut) : 0;

  const effectiveLeverage = modeObj.usesLeverage ? leverage : 1;
  const feeRate = selected ? feeRateFor(selected, mode) : 0;

  const calc = useMemo(() => {
    const position = volume * effectiveLeverage;
    const feePerTrade = position * feeRate;
    const userCbPerTrade = feePerTrade * curRate;
    const daily = userCbPerTrade * tradesPerDay;
    const monthly = daily * 30;
    return { position, feePerTrade, userCbPerTrade, daily, monthly };
  }, [volume, effectiveLeverage, tradesPerDay, curRate, feeRate]);

  return (
    <div className="space-y-4 p-4">
      {/* ── VIP ───────────────────────────────────────────── */}
      <section className="rounded-2xl bg-neutral-900 p-5">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm text-neutral-400">Текущий уровень</div>
            <div className="mt-1 flex items-center gap-2">
              <div className="text-xl font-semibold">{currentTier.label}</div>
              <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-300">
                +{currentTier.bonus}%
              </span>
              <span className="text-xs text-neutral-500">
                итого {(curRate * 100).toFixed(0)}%
              </span>
            </div>
          </div>
          <div className="text-right text-xs text-neutral-500">
            <div>Выведено</div>
            <div className="text-sm text-neutral-200">{fmtUsd(paidOut)}</div>
          </div>
        </div>

        <div className="mt-4 h-2 overflow-hidden rounded-full bg-neutral-800">
          <div
            className="h-full rounded-full bg-emerald-500 transition-all"
            style={{
              width: progress > 0 && progress < 4 ? "4%" : `${progress}%`,
              minWidth: progress > 0 ? 6 : 0,
            }}
          />
        </div>
        <div className="mt-1 flex justify-between text-[10px] text-neutral-500">
          <span>${currentTier.threshold}</span>
          {nextTier && (
            <span>
              <span className="text-emerald-400">{progress.toFixed(0)}%</span>
              <span className="mx-1">·</span>${nextTier.threshold}
            </span>
          )}
        </div>

        {nextTier ? (
          <div className="mt-3 text-sm text-neutral-400">
            До <b className="text-neutral-200">{nextTier.label}</b> (
            {(nextRate * 100).toFixed(0)}%) — ещё{" "}
            <b className="text-neutral-200">{fmtUsd(toNext)}</b>
          </div>
        ) : (
          <div className="mt-3 text-sm text-emerald-300">Максимальный тир достигнут</div>
        )}
      </section>

      {/* ── Calculator ────────────────────────────────────── */}
      <section className="rounded-2xl bg-neutral-900 p-5">
        <h2 className="text-base font-semibold">Калькулятор экономии</h2>
        <p className="mt-1 text-xs text-neutral-500">
          Каждая биржа берёт свою комиссию — посчитайте, сколько вернётся именно у вас.
        </p>

        {/* Exchange selector */}
        <div className="mt-4">
          <div className="text-xs uppercase tracking-wider text-neutral-500">Биржа</div>
          <div
            className="mt-2 grid gap-1.5"
            style={{
              gridTemplateColumns: `repeat(${Math.min(Math.max(exchanges.length, 1), 5)}, minmax(0, 1fr))`,
            }}
          >
            {exchanges.map((ex) => {
              const active = selectedSlug === ex.slug;
              return (
                <button
                  key={ex.slug}
                  onClick={() => setSelectedSlug(ex.slug)}
                  className={
                    "relative flex flex-col items-center gap-1 rounded-lg px-2 py-2 text-[10px] transition " +
                    (active
                      ? "bg-white text-black font-medium"
                      : "bg-neutral-800 text-neutral-300")
                  }
                >
                  <ExchangeLogo ex={ex} active={active} />
                  <span className="leading-tight">{ex.name}</span>
                  {!ex.available && (
                    <span className="absolute -top-1 -right-1 rounded-full bg-amber-500 px-1 text-[8px] font-bold uppercase leading-tight text-black">
                      soon
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Mode selector */}
        <div className="mt-4">
          <div className="text-xs uppercase tracking-wider text-neutral-500">Тип сделки</div>
          <div className="mt-2 grid grid-cols-3 gap-1.5">
            {MODES.map((m) => (
              <button
                key={m.key}
                onClick={() => setMode(m.key)}
                className={
                  "rounded-lg py-2 text-xs transition " +
                  (mode === m.key
                    ? "bg-white text-black font-medium"
                    : "bg-neutral-800 text-neutral-300")
                }
              >
                {m.short}
              </button>
            ))}
          </div>
        </div>

        {modeObj.usesLeverage && (
          <div className="mt-4">
            <div className="text-xs uppercase tracking-wider text-neutral-500">Плечо</div>
            <div className="mt-2 grid grid-cols-6 gap-1.5">
              {LEVERAGES.map((l) => (
                <button
                  key={l}
                  onClick={() => setLeverage(l)}
                  className={
                    "rounded-lg py-2 text-sm transition " +
                    (leverage === l
                      ? "bg-white text-black font-medium"
                      : "bg-neutral-800 text-neutral-300")
                  }
                >
                  {l}x
                </button>
              ))}
            </div>
          </div>
        )}

        <LogSlider
          label={modeObj.usesLeverage ? "Маржа одной сделки" : "Объём одной сделки"}
          value={volume}
          onChange={setVolume}
          toSlider={volumeToSlider}
          toValue={sliderToVolume}
          steps={VOL_SLIDER_STEPS}
          ticks={[fmtMoney(VOL_MIN), "$100", "$1K", "$10K", fmtMoney(VOL_MAX)]}
          fmt={fmtMoney}
        />

        <LogSlider
          label="Сделок в день"
          value={tradesPerDay}
          onChange={setTradesPerDay}
          toSlider={tradesToSlider}
          toValue={sliderToTrades}
          steps={TRADES_SLIDER_STEPS}
          ticks={["1", "5", "10", "30", "100"]}
          fmt={(v) => String(v)}
        />
      </section>

      <section className="rounded-2xl bg-gradient-to-br from-emerald-900/50 to-neutral-900 p-5">
        <div className="flex items-baseline justify-between">
          <div className="text-xs uppercase tracking-wider text-emerald-300">Ваша экономия</div>
          {selected && (
            <div className="text-[10px] text-neutral-500">
              {selected.name} · {modeObj.short}
            </div>
          )}
        </div>

        {selected && !selected.available && (
          <div className="mt-3 rounded-lg bg-amber-500/10 px-3 py-2 text-[11px] text-amber-300">
            {selected.name} подключим в ближайшее время — это превью того, что
            вы получите.
          </div>
        )}

        <div className="mt-3 grid grid-cols-2 gap-3">
          <div>
            <div className="text-2xl font-bold">{fmtMoney(calc.daily)}</div>
            <div className="text-[11px] uppercase text-neutral-500">в день</div>
          </div>
          <div>
            <div className="text-2xl font-bold">{fmtMoney(calc.monthly)}</div>
            <div className="text-[11px] uppercase text-neutral-500">в месяц</div>
          </div>
        </div>

        {selected && (
          <div className="mt-4 border-t border-emerald-900/60 pt-3 text-[11px] text-neutral-500">
            Позиция {fmtMoney(calc.position)} × {(feeRate * 100).toFixed(3)}% комиссии{" "}
            {selected.name} = {fmtMoney(calc.feePerTrade)} за сделку.
            Возврат {(curRate * 100).toFixed(0)}% — <b className="text-emerald-300">{fmtMoney(calc.userCbPerTrade)}</b> вам.
          </div>
        )}
      </section>
    </div>
  );
}

function ExchangeLogo({ ex, active }: { ex: ExchangeInfo; active: boolean }) {
  const [idx, setIdx] = useState(0);
  const url = ex.logo_urls[idx];
  if (!url) {
    return (
      <div
        className="flex h-7 w-7 items-center justify-center rounded-full text-[10px] font-bold"
        style={{ background: ex.brand_color, color: "white" }}
      >
        {ex.name[0]}
      </div>
    );
  }
  return (
    <img
      src={url}
      alt={ex.name}
      onError={() => setIdx((i) => i + 1)}
      className={
        "h-7 w-7 rounded-full object-cover " +
        (!ex.available && !active ? "opacity-50" : "")
      }
    />
  );
}

function LogSlider({
  label,
  value,
  onChange,
  toSlider,
  toValue,
  steps,
  ticks,
  fmt,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  toSlider: (v: number) => number;
  toValue: (s: number) => number;
  steps: number;
  ticks: string[];
  fmt: (v: number) => string;
}) {
  const tick = useRef(makeSelectionTicker()).current;
  return (
    <div className="mt-5">
      <div className="flex items-baseline justify-between">
        <div className="text-xs uppercase tracking-wider text-neutral-500">{label}</div>
        <div className="text-sm text-neutral-200">{fmt(value)}</div>
      </div>
      <input
        type="range"
        min={0}
        max={steps}
        step={1}
        value={toSlider(value)}
        onChange={(e) => {
          const v = toValue(Number(e.target.value));
          onChange(v);
          tick(v);
        }}
        className="range mt-2"
      />
      <div className="mt-1 flex justify-between text-[10px] text-neutral-500">
        {ticks.map((t, i) => (
          <span key={i}>{t}</span>
        ))}
      </div>
    </div>
  );
}

function fmtMoney(v: number): string {
  if (v >= 1000) {
    return "$" + Math.round(v).toLocaleString("en-US");
  }
  if (v >= 10) return "$" + v.toFixed(0);
  if (v >= 1) return "$" + v.toFixed(2);
  return "$" + v.toFixed(3);
}
