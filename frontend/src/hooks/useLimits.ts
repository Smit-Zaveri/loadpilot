import { useEffect, useState } from "react";
import { api, type Limits } from "../api";

/** Server safety limits; null until loaded (or if they can't be loaded). */
export function useLimits(): Limits | null {
  const [limits, setLimits] = useState<Limits | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .getSettings()
      .then((s) => !cancelled && setLimits(s.limits))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  return limits;
}
