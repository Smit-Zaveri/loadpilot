import { useCallback, useState } from "react";

export type Theme = "dark" | "light";
const KEY = "loadpilot-theme";

function initialTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function applyTheme(theme: Theme) {
  // Set before React re-renders: charts read colours from CSS variables when they rebuild,
  // and child effects run before a parent's, so an effect here would be too late.
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Storage can be unavailable (private mode); the theme still applies for this visit.
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next = current === "dark" ? "light" : "dark";
      applyTheme(next);
      return next;
    });
  }, []);

  return { theme, toggle };
}
