# APEX 2.0 — F1 Strategy Intelligence

APEX is a **React + FastAPI** dashboard for Formula 1: live/historical weekend data, **Monte Carlo race & quali predictions**, **telemetry & tyre degradation views**, and a **tyre-strategy engine** (simulation, live scenarios, undercut analysis, AI strategy chat).

Data is loaded primarily from **[OpenF1](https://openf1.org/)**; when OpenF1 has no rows for a session, the API falls back to **[FastF1](https://github.com/theOehrly/FastF1)** so drivers, laps, stints, results, and telemetry can still load locally.

**Repository:** [github.com/Aakash-1707/APEX_2.0](https://github.com/Aakash-1707/APEX_2.0)

---

## Features

| Area | What it does |
|------|----------------|
| **Calendar & sessions** | Pick a meeting; session bar (FP, Quali, Sprint, Race). OpenF1 + year-filter + optional FastF1 schedule fallback. |
| **Telemetry** | Track map + speed/brake colouring; OpenF1 car/location merge, FastF1 fallback. |
| **Tyre degradation** | Stint compounds + lap-time chart; stint ordering normalisation; OpenF1 → FastF1. |
| **Predictions** | Quali / Race / Sprint quali / Sprint race — `POST /api/predict` with configurable data sources. |
| **Strategy** | Monte Carlo tyre strategy, historical stop-profile bias, live SC/VSC/RF scenario, undercut calculator, actual vs predicted. |
| **Strategy Chat** | Optional LLM narration (requires API keys / services configured in backend). |
| **RAG** | Optional Chroma-backed RAG for strategy docs (`strategy_data/`). |

---

## Project structure

```
APEX/
├── apex_backend/
│   ├── api.py              # FastAPI app, OpenF1 proxy, predict, strategy routes
│   ├── ff_bridge.py        # FastF1 fallback (sessions, drivers, laps, stints, telemetry)
│   ├── f1_loader.py        # FastF1 helpers for model / telemetry
│   ├── model_core.py       # Feature engineering + Monte Carlo predictions
│   ├── strategy_engine.py  # Tyre deg fit, strategy sim, undercut
│   ├── requirements.txt
│   └── ...
├── src/
│   ├── App.jsx
│   ├── TelemetryTab.jsx
│   ├── TyreDegTab.jsx
│   ├── StrategyTab.jsx
│   ├── StrategyChat.jsx
│   ├── PredictionTabs.jsx
│   └── theme.jsx
├── Dockerfile              # Backend-only image (API on :8000)
├── vite.config.js          # Dev proxy: /api → http://127.0.0.1:8000
├── package.json
└── README.md
```

---

## Prerequisites

- **Python 3.10+** (3.11 recommended; FastF1 wheels vary by platform)
- **Node.js 18+**

---

## Quick start (local dev)

### 1. Backend

```bash
cd apex_backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

- API: **http://127.0.0.1:8000**
- Swagger: **http://127.0.0.1:8000/docs**

**FastF1** (in `requirements.txt`) caches data under `apex_backend/f1_cache/` — first load for a session can be slow.

### 2. Frontend

```bash
cd ..   # project root
npm install
npm run dev
```

- App: **http://127.0.0.1:3000** (Vite proxies `/api` to port 8000)

Optional: set `VITE_API_URL` if the API is not on the default proxy target (see `src/theme.jsx`).

---

## Docker (API only)

```bash
docker build -t apex-api .
docker run -p 8000:8000 apex-api
```

The frontend is not in this image; serve `npm run build` output separately or use `npm run dev` against the containerized API (adjust `VITE_API_URL` / proxy).

---

## Environment / secrets (optional)

- **LLM / Anthropic** — if you use Strategy Chat or LLM features, configure keys as expected by `apex_backend/llm_service.py` (e.g. env vars; never commit secrets).
- **`.env`** — listed in `.gitignore`; copy from a template if you add one.

---

## Troubleshooting

| Symptom | Fix |
|--------|-----|
| Red **APEX BACKEND OFFLINE** | Start `uvicorn` on port **8000**. |
| **Rate limit** from OpenF1 | Backend caches responses; wait or reduce request frequency. |
| No drivers / sessions for a meeting | Backend retries year-scoped OpenF1 + FastF1 schedule; ensure **fastf1** is installed. |
| Strategy sim **404** drivers | OpenF1 must return sessions + at least one session with a driver list; pick a completed weekend or check meeting key. |
| CORS in browser | Use **http://127.0.0.1:3000** with default Vite proxy, or set CORS / `VITE_API_URL` appropriately. |

---

## License

See repository owner preferences; add a `LICENSE` file if you want explicit terms.

---

## Contributing

Issues and PRs welcome at [Aakash-1707/APEX_2.0](https://github.com/Aakash-1707/APEX_2.0).
