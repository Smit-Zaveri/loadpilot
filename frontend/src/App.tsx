import { Link, NavLink, Outlet, createBrowserRouter } from "react-router";
import { ThemeContext } from "./hooks/themeContext";
import { useTheme } from "./hooks/useTheme";
import { ComparePage } from "./pages/ComparePage";
import { HistoryPage } from "./pages/HistoryPage";
import { NewTestPage } from "./pages/NewTestPage";
import { RunPage } from "./pages/RunPage";
import { SettingsPage } from "./pages/SettingsPage";

function Layout() {
  const { theme, toggle } = useTheme();
  return (
    <ThemeContext.Provider value={theme}>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <header className="topbar">
        <Link to="/" className="wordmark">
          LoadPilot
        </Link>
        <nav aria-label="Main" className="nav">
          <NavLink to="/" end className="nav-link">
            New test
          </NavLink>
          <NavLink to="/history" className="nav-link">
            History
          </NavLink>
          <NavLink to="/settings" className="nav-link">
            Settings
          </NavLink>
        </nav>
        <button type="button" className="btn btn-quiet" onClick={toggle}>
          {theme === "dark" ? "Light theme" : "Dark theme"}
        </button>
      </header>
      <main id="main" className="main">
        <Outlet />
      </main>
    </ThemeContext.Provider>
  );
}

function NotFound() {
  return (
    <div className="page-state">
      <h1 className="page-title">Page not found</h1>
      <Link to="/" className="btn">
        Start a new test
      </Link>
    </div>
  );
}

export const routes = [
  {
    element: <Layout />,
    children: [
      { path: "/", element: <NewTestPage /> },
      { path: "/runs/:id", element: <RunPage /> },
      { path: "/history", element: <HistoryPage /> },
      { path: "/compare", element: <ComparePage /> },
      { path: "/settings", element: <SettingsPage /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
