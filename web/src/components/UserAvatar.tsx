import { useEffect, useState } from "react";

type Props = {
  name: string;
  size?: number;
  className?: string;
};

export default function UserAvatar({ name, size = 40, className = "" }: Props) {
  const tgUser = window.Telegram?.WebApp?.initDataUnsafe?.user;
  const [photoErrored, setPhotoErrored] = useState(false);
  const photoUrl = tgUser?.photo_url;

  // Сбросить error-флаг, если URL изменился (смена сессии)
  useEffect(() => {
    setPhotoErrored(false);
  }, [photoUrl]);

  const initial = (name?.[0] || "U").toUpperCase();
  const base = "shrink-0 rounded-full bg-neutral-800 object-cover";
  const style = { width: size, height: size };

  if (photoUrl && !photoErrored) {
    return (
      <img
        src={photoUrl}
        alt={name}
        className={`${base} ${className}`}
        style={style}
        referrerPolicy="no-referrer"
        onError={() => setPhotoErrored(true)}
      />
    );
  }

  return (
    <div
      className={`${base} grid place-items-center font-semibold text-neutral-300 ${className}`}
      style={{ ...style, fontSize: Math.round(size * 0.42) }}
    >
      {initial}
    </div>
  );
}

export function tgHandle(me: {
  tg_username: string | null;
  tg_id: number;
}): string {
  return me.tg_username ? `@${me.tg_username}` : `#${me.tg_id}`;
}
