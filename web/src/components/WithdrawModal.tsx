import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  createWithdrawal,
  type ExchangeAccount,
  type ExchangeBalance,
  type ExchangeInfo,
  type MeResponse,
} from "../api";
import { fmtUsd } from "../format";
import { createPortal } from "react-dom";
import { useBodyScrollLock } from "../hooks/useBodyScrollLock";

type DestType = "bingx_uid" | "trc20";
type Step = "form" | "done" | "error";

type Props = {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  /** Слаг биржи, с которой выводим. Null → модалка закрыта. */
  sourceExchange: string | null;
  sourceExchangeMeta: ExchangeInfo | null;
  sourceBalance: ExchangeBalance | null;
  exchanges: ExchangeAccount[];
  limits: MeResponse["withdrawal"];
};

export default function WithdrawModal({
  open,
  onClose,
  onSuccess,
  sourceExchange,
  sourceExchangeMeta,
  sourceBalance,
  exchanges,
  limits,
}: Props) {
  const [step, setStep] = useState<Step>("form");
  const [amount, setAmount] = useState("");
  const [destType, setDestType] = useState<DestType>("trc20");
  const [trc20, setTrc20] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [keyboardOffset, setKeyboardOffset] = useState(0);
  const firstInputRef = useRef<HTMLInputElement | null>(null);

  useBodyScrollLock(open);

  const sourceAccount = exchanges.find(
    (e) => e.exchange === sourceExchange && e.status === "active",
  );
  // Возврат на сам аккаунт биржи разрешён только для BingX (пока что — у других
  // нет broker-API, на их UID мы не можем гарантировать доставку через broker payout).
  const supportsExchangeUid = sourceExchange === "bingx" && Boolean(sourceAccount);

  useEffect(() => {
    if (!open) return;
    setStep("form");
    setAmount("");
    setTrc20("");
    setError(null);
    setKeyboardOffset(0);
    setDestType(supportsExchangeUid ? "bingx_uid" : "trc20");
    window.Telegram?.WebApp?.expand?.();
  }, [open, supportsExchangeUid]);

  // Sheet поднимается вместе с клавиатурой через visualViewport API.
  // Во время submitting tracking отключён: keyboardOffset принудительно 0.
  useEffect(() => {
    if (!open || submitting) {
      if (submitting) setKeyboardOffset(0);
      return;
    }
    const vv = window.visualViewport;
    if (!vv) return;
    let active = false;
    const update = () => {
      if (!active) return;
      const diff = window.innerHeight - vv.height - vv.offsetTop;
      setKeyboardOffset(diff > 100 ? diff : 0);
    };
    const t = window.setTimeout(() => {
      active = true;
      vv.addEventListener("resize", update);
      vv.addEventListener("scroll", update);
    }, 350);
    return () => {
      window.clearTimeout(t);
      vv.removeEventListener("resize", update);
      vv.removeEventListener("scroll", update);
      setKeyboardOffset(0);
    };
  }, [open, submitting]);

  if (!open || !sourceExchange || !sourceBalance) return null;

  const exchangeName = sourceExchangeMeta?.name || sourceExchange.toUpperCase();
  const available = Number(sourceBalance.available_usd ?? 0);
  const minUsd = limits.min_usd;
  const amountNum = Number(amount);
  const amountValid = Number.isFinite(amountNum) && amountNum >= minUsd && amountNum <= available;

  const destinationValue =
    destType === "bingx_uid" ? sourceAccount?.uid ?? "" : trc20.trim();
  const destValid =
    destType === "bingx_uid"
      ? Boolean(destinationValue)
      : /^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(destinationValue);

  async function submit() {
    if (!amountValid || !destValid) return;
    // Снимаем фокус с активного input до запроса — иначе после смены step
    // sheet прыгает между closing-keyboard анимацией и новой высотой контента.
    (document.activeElement as HTMLElement | null)?.blur?.();
    setSubmitting(true);
    setError(null);
    try {
      // Даём клавиатуре и sheet доехать вниз ОДНИМ движением до смены контента —
      // иначе анимация закрытия клавиатуры и смена шага накладываются (дёрганье).
      const settle = new Promise((r) => setTimeout(r, 280));
      await createWithdrawal({
        amount_usd: amount,
        exchange: sourceExchange!,
        destination_type: destType,
        destination_value: destinationValue,
      });
      await settle;
      window.Telegram?.WebApp?.HapticFeedback?.notificationOccurred("success");
      setStep("done");
      onSuccess();
    } catch (e) {
      window.Telegram?.WebApp?.HapticFeedback?.notificationOccurred("error");
      setError(humanError(e));
    } finally {
      setSubmitting(false);
    }
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-end justify-center overscroll-contain bg-black/85 backdrop-blur-md"
      onTouchMove={(e) => {
        if (e.target === e.currentTarget) e.preventDefault();
      }}
    >
      <div
        className="w-full max-w-md rounded-t-3xl bg-neutral-900 p-5 pb-8 transition-[margin] duration-150 sm:rounded-3xl sm:mb-4"
        style={{ marginBottom: keyboardOffset }}
      >
        <div className="mb-4 flex items-center justify-between">
          <div>
            <div className="text-base font-semibold">Вывод средств</div>
            <div className="text-xs text-neutral-500">С биржи {exchangeName}</div>
          </div>
          <button
            onClick={onClose}
            className="text-xl text-neutral-500"
            aria-label="Закрыть"
          >
            ×
          </button>
        </div>

        {step === "form" && (
          <div className="space-y-4">
            <div className="rounded-xl bg-neutral-800 px-4 py-3">
              <div className="text-[10px] uppercase tracking-wider text-neutral-500">
                Доступно к выводу с {exchangeName}
              </div>
              <div className="mt-1 text-2xl font-bold">{fmtUsd(available)}</div>
            </div>

            <label className="block text-sm text-neutral-400">
              Сумма (от {fmtUsd(minUsd)})
              <div className="relative mt-2">
                <input
                  ref={firstInputRef}
                  value={amount}
                  onChange={(e) =>
                    setAmount(e.target.value.replace(/[^0-9.]/g, "").replace(/(\..*)\./g, "$1"))
                  }
                  inputMode="decimal"
                  placeholder="0.00"
                  className="w-full rounded-xl bg-neutral-800 px-4 py-3 pr-16 text-base text-white outline-none ring-emerald-500 focus:ring-2"
                />
                <button
                  onClick={() => setAmount(String(available))}
                  disabled={available <= 0}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg bg-neutral-700 px-2.5 py-1 text-xs disabled:opacity-30"
                >
                  Макс
                </button>
              </div>
            </label>

            <div>
              <div className="mb-2 text-xs uppercase tracking-wider text-neutral-500">
                Куда вывести
              </div>
              <div className="grid grid-cols-2 gap-2">
                <DestBtn
                  active={destType === "bingx_uid"}
                  disabled={!supportsExchangeUid}
                  onClick={() => setDestType("bingx_uid")}
                  title={`${exchangeName} UID`}
                  subtitle={
                    supportsExchangeUid
                      ? `UID ${sourceAccount?.uid}`
                      : sourceExchange === "bingx"
                        ? "не подключён"
                        : "пока недоступно"
                  }
                />
                <DestBtn
                  active={destType === "trc20"}
                  onClick={() => setDestType("trc20")}
                  title="TRC-20"
                  subtitle="USDT-кошелёк"
                />
              </div>
            </div>

            {destType === "trc20" && (
              <label className="block text-sm text-neutral-400">
                Адрес TRC-20
                <input
                  value={trc20}
                  onChange={(e) => setTrc20(e.target.value.trim())}
                  placeholder="T..."
                  className="mt-2 w-full rounded-xl bg-neutral-800 px-4 py-3 font-mono text-sm text-white outline-none ring-emerald-500 focus:ring-2"
                />
                {trc20 && !destValid && (
                  <p className="mt-1.5 text-xs text-amber-400">
                    Адрес должен начинаться с T и содержать 34 символа
                  </p>
                )}
              </label>
            )}

            {destType === "trc20" && (
              <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-200">
                Комиссия сети TRC-20 (~$1 USDT) удерживается из суммы выплаты —
                её оплачивает получатель.
              </div>
            )}

            {error && <p className="text-sm text-red-400">{error}</p>}

            <p className="text-xs text-neutral-500">
              Выплата обрабатывается оператором вручную — обычно до 24 часов.
              Уведомление придёт в боте.
            </p>

            <button
              onClick={submit}
              disabled={submitting || !amountValid || !destValid}
              className="w-full rounded-xl bg-white py-3 font-medium text-black disabled:opacity-40"
            >
              {submitting ? "Отправляем…" : "Запросить вывод"}
            </button>
          </div>
        )}

        {step === "done" && (
          <div className="space-y-4 text-center">
            <div className="text-5xl">✓</div>
            <div className="text-base font-medium">Заявка принята</div>
            <p className="text-sm text-neutral-400">
              Выплата появится в истории. Уведомление придёт в боте, когда оператор
              завершит перевод.
            </p>
            <button
              onClick={onClose}
              className="w-full rounded-xl bg-white py-3 font-medium text-black"
            >
              Готово
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

function DestBtn({
  active,
  disabled,
  onClick,
  title,
  subtitle,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  title: string;
  subtitle: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={
        "rounded-xl border px-3 py-2.5 text-left transition disabled:opacity-30 " +
        (active
          ? "border-emerald-500/60 bg-emerald-500/10"
          : "border-neutral-700 bg-neutral-800")
      }
    >
      <div className="text-sm font-medium">{title}</div>
      <div className="mt-0.5 text-[11px] text-neutral-400">{subtitle}</div>
    </button>
  );
}

function humanError(e: unknown): string {
  if (e instanceof ApiError) {
    return e.message || `Ошибка ${e.status}`;
  }
  return e instanceof Error ? e.message : String(e);
}
