# Development roadmap

The roadmap is a deterministic snapshot of the implementation tickets under GitHub spec #7.
It is not part of the deployed Tariff Copilot application and makes no browser-time GitHub API
requests.

Regenerate it from the repository root after issue status, assignments, metadata, or native
blocking edges change:

```sh
python -m planning.roadmap.roadmap
```

The exporter validates required execution metadata, text/native dependency agreement,
contiguous sequence numbers, supported lanes/models, timezone-aware target windows, and an
acyclic dependency graph before updating `roadmap.json` and `index.html`.

Preview locally:

```sh
python -m http.server 4173 -d planning/roadmap
```

Then open <http://localhost:4173/>.
