import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, createMemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NewTestPage } from "./NewTestPage";

type Handler = (url: string, init?: RequestInit) => { status: number; body: unknown };

function mockFetch(handler: Handler) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const { status, body } = handler(String(input), init);
    return new Response(JSON.stringify(body), { status });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const defaults: Handler = (url) => {
  if (url === "/api/health") return { status: 200, body: { status: "ok", version: "x", demo: true } };
  if (url === "/api/runs") return { status: 200, body: [] };
  return { status: 404, body: null };
};

function renderPage() {
  const router = createMemoryRouter(
    [
      { path: "/", element: <NewTestPage /> },
      { path: "/runs/:id", element: <p>run page</p> },
    ],
    { initialEntries: ["/"] },
  );
  render(<RouterProvider router={router} />);
  return router;
}

describe("NewTestPage", () => {
  beforeEach(() => vi.useRealTimers());
  afterEach(() => vi.unstubAllGlobals());

  it("shows the empty state for runs", async () => {
    mockFetch(defaults);
    renderPage();
    expect(await screen.findByText(/No runs yet/)).toBeInTheDocument();
  });

  it("validates before sending anything", async () => {
    const fetchMock = mockFetch(defaults);
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Start test" }));
    expect(screen.getByText("Enter the URL to test.")).toBeInTheDocument();
    expect(screen.getByLabelText("URL")).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });

  it("fills the demo target and starts a run", async () => {
    let posted: unknown;
    mockFetch((url, init) => {
      if (url === "/api/runs" && init?.method === "POST") {
        posted = JSON.parse(String(init.body));
        return { status: 201, body: { id: "run123" } };
      }
      return defaults(url, init);
    });
    const router = renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /built-in demo target/ }));
    expect(screen.getByLabelText("URL")).toHaveValue(
      `${window.location.origin}/demo/random-latency?min_ms=20&max_ms=120`,
    );
    await userEvent.click(screen.getByRole("radio", { name: "Requests per second" }));
    await userEvent.clear(screen.getByLabelText("Target rate (req/s)"));
    await userEvent.type(screen.getByLabelText("Target rate (req/s)"), "25");
    await userEvent.click(screen.getByRole("button", { name: "Start test" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/runs/run123"));
    expect(posted).toMatchObject({
      name: "Demo: random latency",
      load: { mode: "rate", rate: 25, duration: 30 },
    });
  });

  it("links to the running test when another one is active", async () => {
    mockFetch((url, init) => {
      if (url === "/api/runs" && init?.method === "POST") {
        return { status: 409, body: { detail: { message: "another test is already running", run_id: "busy1" } } };
      }
      return defaults(url, init);
    });
    renderPage();
    await userEvent.type(screen.getByLabelText("URL"), "http://localhost:9000/");
    await userEvent.click(screen.getByRole("button", { name: "Start test" }));
    expect(await screen.findByText("another test is already running")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the running test" })).toHaveAttribute("href", "/runs/busy1");
  });
});
