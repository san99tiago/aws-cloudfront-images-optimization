import { useEffect, useState, useSyncExternalStore } from "react";

import { getVersion, subscribe } from "./deviceCache";

/** Re-render when any delivery or the device cache changes. */
export function useDeliveryVersion(): number {
  return useSyncExternalStore(subscribe, getVersion);
}

/** A clock that ticks every second (countdowns of the device cache TTL). */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

/** Element width (CSS px) that only changes when the element really resizes. */
export function useElementWidth<T extends HTMLElement>(ref: React.RefObject<T | null>): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const next = Math.round(entries[0]?.contentRect.width ?? 0);
      setWidth((current) => (Math.abs(current - next) >= 1 ? next : current));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

/** True once the element is close to the viewport (download only what the user will see). */
export function useNearViewport<T extends HTMLElement>(ref: React.RefObject<T | null>, rootMargin = "300px"): boolean {
  const [near, setNear] = useState(false);
  useEffect(() => {
    const element = ref.current;
    if (!element || near) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNear(true);
          observer.disconnect();
        }
      },
      { rootMargin },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, near, rootMargin]);
  return near;
}
