import { createContext } from "react";
import type { Theme } from "./useTheme";

export const ThemeContext = createContext<Theme>("dark");
