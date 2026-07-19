import { useSyncExternalStore } from "react";

/** Tiny cross-component store for the active collection scope. */

export interface ActiveCollection {
  id: string;
  name: string;
}

const KEY = "corpus.activeCollection";
let listeners: (() => void)[] = [];
let cached: ActiveCollection | null = readStorage();

function readStorage(): ActiveCollection | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as ActiveCollection) : null;
  } catch {
    return null;
  }
}

export function setActiveCollection(value: ActiveCollection | null): void {
  cached = value;
  if (value) localStorage.setItem(KEY, JSON.stringify(value));
  else localStorage.removeItem(KEY);
  listeners.forEach((fn) => fn());
}

export function useActiveCollection(): ActiveCollection | null {
  return useSyncExternalStore(
    (onChange) => {
      listeners.push(onChange);
      return () => {
        listeners = listeners.filter((fn) => fn !== onChange);
      };
    },
    () => cached,
  );
}
