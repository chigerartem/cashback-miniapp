import { useEffect, useState } from "react";
import {
  ApiError,
  connectBingx,
  getExchanges,
  type ExchangeInfo,
} from "../api";
import { createPortal } from "react-dom";
import { useBodyScrollLock } from "../hooks/useBodyScrollLock";

type Step = "intro" | "uid" | "done" | "error";

type Props = {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
};

export default function ConnectBingxModal({ open, onClose, onSuccess }: Props) {
  const [step, setStep] = useState<Step>("intro");
  const [info, setInfo] = useState<ExchangeInfo | null>(null);
  const [uid, setUid] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [keyboardOffset, setKeyboardOffset] = useState(0);

  useBodyScrollLock(open);

  useEffect(() => {
    if (!open) return;
    setStep("intro");
    setUid("");
    setError(null);
    window.Telegram?.WebApp?.expand?.();
    getExchanges()
      .then((list) => setInfo(list[0] ?? null))
      .catch((e) => {
        setError(humanError(e));
        setStep("error");
      });
  }, [open]);

  // Sheet поднимается вместе с клавиатурой через visualViewport API.
  // Подписку откладываем — иначе tg.expand() триггерит resize и sheet дёргается.
  useEffect(() => {
    if (!open) return;
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
  }, [open]);

  function openReferralLink() {
    if (!info?.referral_url) return;
    haptic("medium");
    const tg = window.Telegram?.WebApp;
    if (tg?.openLink) {
      tg.openLink(info.referral_url, { try_instant_view: false });
    } else {
      window.open(info.referral_url, "_blank", "noopener,noreferrer");
    }
  }

  async function submitUid() {
    if (!/^\d{3,32}$/.test(uid)) {
      setError("UID должен состоять только из цифр (3–32 символа)");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await connectBingx(uid);
      haptic("success");
      setStep("done");
      onSuccess();
    } catch (e) {
      haptic("error");
      setError(humanError(e));
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) return null;

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
          <div className="text-base font-semibold">Подключить BingX</div>
          <button
            onClick={onClose}
            className="text-xl text-neutral-500 hover:text-neutral-200"
            aria-label="Закрыть"
          >
            ×
          </button>
        </div>

        <Stepper step={step} />

        {step === "intro" && (
          <div className="space-y-4">
            <p className="text-sm text-neutral-300">
              Зарегистрируйтесь на BingX по нашей реферальной ссылке —
              это позволит возвращать вам часть комиссий с ваших сделок.
            </p>
            <button
              onClick={openReferralLink}
              disabled={!info?.referral_url}
              className="w-full rounded-xl bg-white py-3 font-medium text-black disabled:opacity-40"
            >
              Открыть BingX и зарегистрироваться
            </button>
            {info !== null && !info.referral_url && (
              <p className="text-xs text-amber-400">
                Реферальная ссылка пока не настроена. Свяжитесь с поддержкой.
              </p>
            )}
            <button
              onClick={() => setStep("uid")}
              className="w-full rounded-xl border border-neutral-700 py-3 text-sm text-neutral-200"
            >
              Уже есть аккаунт BingX →
            </button>
          </div>
        )}

        {step === "uid" && (
          <div className="space-y-4">
            <label className="block text-sm text-neutral-400">
              Укажите ваш UID на BingX
              <input
                value={uid}
                onChange={(e) => setUid(e.target.value.replace(/\D/g, ""))}
                inputMode="numeric"
                autoFocus
                placeholder="напр. 23845129"
                className="mt-2 w-full rounded-xl bg-neutral-800 px-4 py-3 text-base text-white outline-none ring-emerald-500 focus:ring-2"
              />
            </label>
            <p className="text-xs text-neutral-500">
              UID находится в профиле BingX в правом верхнем углу.
            </p>
            {error && <p className="text-sm text-red-400">{error}</p>}
            <button
              onClick={submitUid}
              disabled={submitting || !uid}
              className="w-full rounded-xl bg-white py-3 font-medium text-black disabled:opacity-40"
            >
              {submitting ? "Проверяем…" : "Подтвердить"}
            </button>
          </div>
        )}

        {step === "done" && (
          <div className="space-y-4 text-center">
            <div className="text-5xl">✅</div>
            <div className="text-base font-medium">BingX подключён</div>
            <p className="text-sm text-neutral-400">
              Кешбэк за сделки появляется на балансе на следующий день в 05:00 UTC.
            </p>
            <button
              onClick={onClose}
              className="w-full rounded-xl bg-white py-3 font-medium text-black"
            >
              Готово
            </button>
          </div>
        )}

        {step === "error" && (
          <div className="space-y-4">
            <p className="text-sm text-red-400">{error}</p>
            <button
              onClick={onClose}
              className="w-full rounded-xl border border-neutral-700 py-3"
            >
              Закрыть
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

function Stepper({ step }: { step: Step }) {
  const idx = step === "intro" ? 0 : step === "uid" ? 1 : 2;
  return (
    <div className="mb-4 grid grid-cols-3 gap-2">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className={
            "h-1 rounded-full " + (i <= idx ? "bg-emerald-500" : "bg-neutral-700")
          }
        />
      ))}
    </div>
  );
}

function haptic(kind: "success" | "warning" | "error" | "medium") {
  const tg = window.Telegram?.WebApp;
  if (!tg?.HapticFeedback) return;
  if (kind === "medium") tg.HapticFeedback.impactOccurred("medium");
  else tg.HapticFeedback.notificationOccurred(kind);
}

function humanError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 503) {
      return "BingX-интеграция временно недоступна. Попробуйте позже или напишите в поддержку.";
    }
    if (e.status === 409) {
      return e.message;
    }
    if (e.status === 422 || e.status === 502) {
      return e.message ||
        "BingX не подтвердил привязку. Убедитесь, что UID указан верно и регистрация прошла по нашей ссылке.";
    }
    return e.message || `Ошибка ${e.status}`;
  }
  return e instanceof Error ? e.message : String(e);
}
