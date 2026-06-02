/** Парсит строку/число → выводит "$0.00" с разделителями. NaN/null/"" → "$0.00". */
export function fmtUsd(v: string | number | null | undefined): string {
  const n = typeof v === "number" ? v : Number(v ?? 0);
  if (!Number.isFinite(n)) return "$0.00";
  return "$" + n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** Компактный формат: $1.5K, $25M. Под цифры на статах. */
export function fmtUsdCompact(v: string | number | null | undefined): string {
  const n = typeof v === "number" ? v : Number(v ?? 0);
  if (!Number.isFinite(n)) return "$0";
  if (n >= 1_000_000) return "$" + (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 10_000) return "$" + Math.round(n / 1_000) + "K";
  if (n >= 1_000) return "$" + (n / 1_000).toFixed(1).replace(/\.0$/, "") + "K";
  return "$" + Math.round(n);
}

/** Целое число для счётчиков (трейдеров, рефералов). */
export function fmtInt(v: string | number | null | undefined): string {
  const n = typeof v === "number" ? v : Number(v ?? 0);
  if (!Number.isFinite(n)) return "0";
  return Math.round(n).toLocaleString("en-US");
}
