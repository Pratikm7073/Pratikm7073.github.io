# pratikm7073.github.io

Personal portfolio site — React + Vite, deployed on GitHub Pages.

## Projects in this repository

### [Retail Resource Planning & Forecast Engine](planning-engine/) · [live demo ↗](https://pratikm7073.github.io/planning-engine.html)

A multi-channel contact centre demand-forecasting and capacity-planning engine in Python:
forecasts contacts across 16 service lines, sizes every half hour with Erlang, models
advisor supply against attrition and the recruitment pipeline, prices the gap and raises a
mitigations register. 35.8% mean error reduction against a seasonal-naive baseline across
all 16 lines; 130 unit tests. All data is synthetic — see the
[project README](planning-engine/README.md).

## Site

```bash
cd app && npm install && npm run dev     # local dev server
npm run build                            # builds to ../dist
```

The built `index.html` and `assets/` are committed at the repository root, which is what
GitHub Pages serves.
