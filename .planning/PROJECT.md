# Climate Pulse

## What This Is

Climate Pulse è una pipeline open-source che aggrega dati meteorologici da fonti pubbliche europee (stazioni ARPA regionali italiane, ECMWF Open Data, METAR/TAF NOAA, Copernicus C3S) in un unico time-series store interrogabile via public API REST/WebSocket e visualizzato attraverso una dashboard Angular con mappa interattiva. È pensata per ricercatori, giornalisti dati, comunità open-data e PMI (agricoltura, energie rinnovabili) che vogliono accesso strutturato a serie storiche meteo senza pagare API commerciali.

## Core Value

**End-to-end multi-source meteo pipeline**: aggregare in modo affidabile dati pubblici da fonti EU eterogenee (ARPA, ECMWF, NOAA, Copernicus) e renderli queryabili attraverso una public API documentata + dashboard utilizzabile. Se l'intera catena ingestion → storage → query → visualizzazione non funziona, il progetto non ha valore.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

(None yet — ship to validate)

### Active

<!-- Current scope. Building toward these. -->

- [ ] Aggregation multi-source con adapter pluggable (ARPA regionali IT, ECMWF Open Data, METAR/TAF NOAA, Copernicus C3S)
- [ ] TimescaleDB time-series storage (hypertable per location + variable + timestamp, compression chunk-based, retention configurabile per fonte)
- [ ] Public API FastAPI con OpenAPI 3.1 (REST + WebSocket, rate limiting Redis-based, export CSV/JSON/Parquet)
- [ ] Dashboard Angular 21 SSR (mappa Leaflet con marker stazioni, grafici Plotly time-series, comparazione multi-station)
- [ ] Variabili WMO normalizzate (temperatura, umidità, pressione, vento, precipitazioni, irraggiamento, copertura nuvole) in unità SI con quality flag per fonte
- [ ] Celery worker ingestion cron-style (ARPA 15min, ECMWF 4 cycle/day, METAR 1h) con retry strategy + Dead Letter Queue
- [ ] Scraping rispettoso (User-Agent identificato, rate limit conservative, cache HTTP, fallback snapshot statici, compliance robots.txt)
- [ ] Alert configurabili (webhook + email) per soglie variabili (temperatura, vento, precipitazioni) per location
- [ ] Documentazione MkDocs + community setup guide
- [ ] **GitHub Pages documentation** pubblicata fin dalla v0.1 (MkDocs Material → gh-pages, GitHub Action di build/deploy automatico)
- [ ] **Footer dashboard + footer docs** con attribuzione `federicocalo.dev` (link cliccabile) presente su ogni pagina del progetto
- [ ] Deploy self-hosted via Docker Compose (timescale + redis + api + worker + dashboard)

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- API commerciale a pagamento — filosofia open-data, license MIT
- OAuth/SSO autenticazione utenti finali — API pubblica, eventuale API key opzionale in v1.0
- Dataset extra-europei oltre METAR globali — focus EU/Italia
- Forecasting proprietario / modelli ML interni — Climate Pulse aggrega, non genera previsioni
- Mobile app native — dashboard web SSR sufficiente per v1.0
- Real-time streaming via Kafka — Celery cron-style è sufficiente per le frequenze richieste
- Deploy Kubernetes / Helm chart — solo Docker Compose self-hosted in v1.0
- Multi-tenancy / billing — single-instance open-data, non SaaS

## Context

- **Filosofia open data infrastructure**: i dati sono pubblici, la pipeline che li unifica dovrebbe esserlo anche. License MIT per massima riusabilità.
- **Target users diversi**: ricercatori universitari (climatologia, agricoltura), giornalisti dati ambientali (ondate calore, siccità, alluvioni), comunità open-data, PMI agricoltura precision farming / energie rinnovabili (solare, eolico).
- **Fonti pubbliche eterogenee**: ogni fonte ARPA regionale ha endpoint, formato e cadenza differenti — servono adapter dedicati e gestione quality flag per fonte.
- **Compliance scraping**: gli endpoint ARPA sono pubblici ma vanno trattati con rispetto (User-Agent, rate limit, robots.txt, fallback snapshot).
- **Stack moderno**: FastAPI 0.115+, Python 3.12, TimescaleDB, Angular 21 SSR, Leaflet, Plotly, Celery, Redis — scelte coerenti con ecosistema 2026.
- **Rilascio target**: Q3 2026, work-in-progress.

## Constraints

- **Tech stack**: FastAPI 0.115+, Python 3.12, TimescaleDB, Angular 21 SSR, Leaflet, Plotly, Celery, Redis — già deciso, no negoziazione
- **License**: MIT — massima riusabilità community
- **Team**: sviluppatore singolo — scope ridotti per phase, no parallelism umano (parallelism solo dei plan all'interno della phase)
- **Budget**: zero cloud budget — tutto deve girare su risorse locali (Docker Compose) o tier gratuito
- **Compliance**: GDPR-aware anche se dati meteo pubblici — attenzione a log delle query API, no PII tracking, robots.txt compliance scraping
- **Deploy**: self-hosted Docker Compose only in v1.0 — niente K8s, niente cloud-native
- **Timeline**: rilascio v1.0.0 previsto Q3 2026
- **Politeness scraping**: rate limit conservative, snapshot fallback, identificazione User-Agent obbligatori per fonti ARPA
- **Attribuzione obbligatoria**: footer `federicocalo.dev` su dashboard Angular e documentazione GitHub Pages — presente in ogni release a partire dalla v0.1
- **Docs pubbliche da subito**: documentazione MkDocs Material pubblicata su GitHub Pages fin dalla v0.1 (no "docs in fase successiva")

## Key Decisions

<!-- Decisions that constrain future work. Add throughout project lifecycle. -->

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| TimescaleDB invece di InfluxDB/ClickHouse | Postgres-compatible, hypertable native, compression chunk-based, ecosistema FastAPI/Python maturo | — Pending |
| Celery + Redis vs APScheduler/Prefect | Celery è battle-tested per worker periodici, Redis comunque presente per cache/rate-limit | — Pending |
| Angular 21 SSR vs Next.js/Svelte | Stack dichiarato dal proprietario progetto, SSR per SEO open-data | — Pending |
| Adapter pluggable per fonti | Ogni fonte ha format diversi, serve astrazione per aggiungere nuove fonti senza toccare core | — Pending |
| Variabili WMO normalizzate (unità SI) | Standard internazionale, abilita confronti cross-source | — Pending |
| License MIT | Filosofia open-data, massima riusabilità community | ✓ Good |
| Self-hosted Docker Compose only (v1.0) | Zero cloud budget, deploy comunità open-data, single-node sufficient | — Pending |
| Public API senza autenticazione (rate-limit IP-based) | Filosofia open-data, API key opzionale solo in v1.0 | — Pending |
| Docs su GitHub Pages fin dalla v0.1 (MkDocs Material + GH Action) | Progetto open-source vive anche di docs scoperte da Google — niente "docs dopo", parte subito | ✓ Good |
| Footer `federicocalo.dev` su dashboard + docs | Attribuzione autore richiesta in ogni release; deve essere in ogni pagina (dashboard Angular layout + MkDocs theme footer) | ✓ Good |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-23 after initialization*
