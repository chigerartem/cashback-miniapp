import { useEffect, useState } from "react";
import { getReferral, type MeResponse, type ReferralInfo } from "../api";
import { fmtInt, fmtUsd } from "../format";

const BOT_USERNAME = import.meta.env.VITE_BOT_USERNAME || "your_cashback_bot";

export default function Community({ me }: { me: MeResponse }) {
  const [info, setInfo] = useState<ReferralInfo | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    getReferral().then(setInfo).catch(() => setInfo(null));
  }, []);

  // Fallback: на старте можно показать ref_url, собранный из me, пока запрос летит
  const refUrl = info?.ref_url ?? `https://t.me/${BOT_USERNAME}?start=ref_${me.user.ref_code}`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(refUrl);
      setCopied(true);
      window.Telegram?.WebApp?.HapticFeedback?.notificationOccurred("success");
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // ignore — clipboard not available
    }
  }

  function shareToTelegram() {
    const tg = window.Telegram?.WebApp;
    const text = "Получаю кешбэк за торговлю на криптобиржах. Подключайся.";
    const url = `https://t.me/share/url?url=${encodeURIComponent(refUrl)}&text=${encodeURIComponent(text)}`;
    tg?.HapticFeedback?.impactOccurred?.("medium");
    if (tg?.openTelegramLink) {
      tg.openTelegramLink(url);
    } else {
      window.open(url, "_blank", "noopener,noreferrer");
    }
  }

  return (
    <div className="space-y-4 p-4">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Комьюнити</h1>
        <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-300">
          {info?.referral_rate_pct ?? 15}% реф
        </span>
      </header>

      <div className="grid grid-cols-2 gap-2">
        <Stat label="Приглашено" value={fmtInt(info?.invited_count)} />
        <Stat label="Заработано" value={fmtUsd(info?.earned_usd)} />
      </div>

      <p className="rounded-2xl bg-neutral-900 p-4 text-sm leading-relaxed text-neutral-300">
        Вы получаете <b>15%</b> от кешбэка каждого приглашённого — пожизненно.
        Для приглашённого с VIP-статусом и ставкой 35% это{" "}
        <span className="text-emerald-300">~5%</span> от его комиссии.
      </p>

      <section className="rounded-2xl bg-neutral-900 p-5">
        <div className="mb-2 text-[10px] uppercase tracking-wider text-neutral-500">
          Ваша реферальная ссылка
        </div>
        <div className="break-all rounded-lg bg-neutral-800 px-3 py-2.5 text-sm text-neutral-200">
          {refUrl}
        </div>
        <div className="mt-3 flex gap-2">
          <button
            onClick={copy}
            className={
              "flex-1 rounded-xl border py-2.5 text-sm font-medium transition " +
              (copied
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                : "border-neutral-700 text-neutral-200")
            }
          >
            {copied ? "✓ Скопировано" : "Скопировать"}
          </button>
          <button
            onClick={shareToTelegram}
            className="flex-1 rounded-xl bg-white py-2.5 text-sm font-medium text-black"
          >
            Share в Telegram
          </button>
        </div>
      </section>

      <section className="rounded-2xl bg-neutral-900 p-5">
        <h2 className="mb-3 text-base font-semibold">Как это работает</h2>
        <ol className="space-y-2.5 text-sm text-neutral-300">
          <Step n={1} text="Отправляете ссылку другу или подписчикам" />
          <Step n={2} text="Они регистрируются по ней и подключают BingX" />
          <Step n={3} text="С каждой их сделки вам автоматически начисляется 15% от их кешбэка" />
        </ol>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-neutral-900 p-4 text-center">
      <div className="text-2xl font-bold">{value}</div>
      <div className="mt-1 text-[10px] uppercase tracking-wider text-neutral-500">
        {label}
      </div>
    </div>
  );
}

function Step({ n, text }: { n: number; text: string }) {
  return (
    <li className="flex items-start gap-3">
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-emerald-500/15 text-xs font-semibold text-emerald-300">
        {n}
      </span>
      <span>{text}</span>
    </li>
  );
}
