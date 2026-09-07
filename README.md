# Market Observatory (internal)

Minato Wealth internal market-analysis dashboard. Public market data only.
Live page (noindex): https://claritus-wealth.github.io/market-observatory/
System record: Notion → Practice Library → "Market Observatory — System Record".

## How it is published
`.github/workflows/refresh.yml` runs each weekday at 05:30 UTC (and on demand from the
Actions tab). It runs `refresh.py`, which fetches FX, oil and metals from public mirrors,
validates them, injects the data into `dashboard_template.html`, and the workflow commits the
result as `index.html`. GitHub Pages redeploys from `main` on that commit.

If `refresh.py` fails a validation gate the workflow fails, nothing is committed, the previous
page stays live, and GitHub emails the repository owner.

## Files
- `refresh.py` — the build script (standard library only).
- `dashboard_template.html` — the dashboard template (v2, 18 Jul 2026); `/*__DATA__*/` is the injection marker.
- `index.html` — the published page. Generated; do not edit by hand.
- `.github/workflows/refresh.yml` — the schedule and publish steps.

This repository is the canonical home of the build files. Change them here, by commit.
