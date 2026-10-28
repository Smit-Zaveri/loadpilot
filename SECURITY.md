# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue. Use GitHub's private vulnerability reporting
("Security" tab → "Report a vulnerability") on this repository. We aim to reply within 7 days.

## Scope

LoadPilot is designed to run on your own machine. By default it binds to `127.0.0.1`.
If you expose it on a network, put it behind authentication. Anyone who can reach it
can make it send traffic.
