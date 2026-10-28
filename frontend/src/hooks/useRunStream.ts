import { useEffect, useRef, useState } from "react";
import { ApiError, api, isDone, runStreamUrl, type RunDetail, type StreamMessage } from "../api";
import { applyMessage } from "../lib/runState";

export type StreamState = "loading" | "live" | "reconnecting" | "closed" | "error";

/** Loads a run over REST, then follows it live over a WebSocket until it ends. */
export function useRunStream(runId: string) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [state, setState] = useState<StreamState>("loading");
  const [error, setError] = useState<ApiError | null>(null);
  const runRef = useRef<RunDetail | null>(null);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let retries = 0;
    let cancelled = false;

    const update = (next: RunDetail | null) => {
      runRef.current = next;
      setRun(next);
    };

    const connect = () => {
      if (cancelled) return;
      socket = new WebSocket(runStreamUrl(runId));
      socket.onopen = () => {
        retries = 0;
        setState("live");
      };
      socket.onmessage = (event) => {
        const msg = JSON.parse(event.data as string) as StreamMessage;
        update(applyMessage(runRef.current, msg));
      };
      socket.onclose = () => {
        if (cancelled) return;
        const current = runRef.current;
        if (current && isDone(current.status)) {
          setState("closed");
          return;
        }
        setState("reconnecting");
        retries += 1;
        retryTimer = setTimeout(connect, Math.min(1000 * retries, 5000));
      };
    };

    setState("loading");
    setError(null);
    update(null);
    api
      .getRun(runId)
      .then((initial) => {
        if (cancelled) return;
        update(initial);
        if (isDone(initial.status)) setState("closed");
        else connect();
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof ApiError ? e : new ApiError(String(e), 0));
        setState("error");
      });

    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
      socket?.close();
    };
  }, [runId]);

  return { run, state, error, setRun: (r: RunDetail) => { runRef.current = r; setRun(r); } };
}
