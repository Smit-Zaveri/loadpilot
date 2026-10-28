# LoadPilot UI direction

Chosen by the project owner: **instrument panel**.

- **Identity:** a lab instrument for measuring APIs. Numbers come first; decoration doesn't.
- **Theme:** dark by default (people watch it for long runs, often next to a terminal), with a working light toggle.
- **Palette:** calm neutral greys plus **one signal colour, amber**. Amber means "live" or "needs attention": the running state, the headline metric, warnings. Nothing else is amber.
- **Charts:** colour-blind-safe series colours (Okabe–Ito: sky blue, orange, vermillion). They encode data, so they don't count as brand colours.
- **Typography:** the system UI font, because a self-hosted tool should render instantly with no font download. All numbers use tabular figures so live values don't jitter as they change.
- **Density:** compact and aligned to a grid, with thin 1px borders and small radii (4–6px). No shadows: everything sits on one flat surface, like a panel.
- **Motion:** hover and focus states only. Live data is the only thing that moves.

Dial: ENERGY 1 / RHYTHM 2 / MOTION 1
