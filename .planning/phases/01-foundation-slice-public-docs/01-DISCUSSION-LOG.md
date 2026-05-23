# Phase 1: Foundation Slice + Public Docs - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-23
**Phase:** 01-foundation-slice-public-docs
**Areas discussed:** Repo + Docs URL, Footer style, Phase 1 acceptance demo, Snapshot fallback storage, ARPA Emilia-Romagna endpoint, ECMWF GRIB parsing, Testing strategy + coverage gate

---

## Repo + Docs URL

### Q1: Dove vivrà il repo GitHub di Climate Pulse?

| Option | Description | Selected |
|--------|-------------|----------|
| github.com/federicocalo/climate-pulse | Account personale (URL pulito, semplice da gestire) | ✓ |
| github.com/<org>/climate-pulse | Organizzazione dedicata (per multi-maintainer) | |
| Decido più tardi | Phase 1 funziona anche in locale | |

### Q2: URL della documentazione pubblica MkDocs?

| Option | Description | Selected |
|--------|-------------|----------|
| climatepulse.federicocalo.dev (custom domain) | Sottodominio personale via CNAME, branded | |
| docs.climate-pulse.dev (dominio dedicato) | Dominio progetto separato, da acquistare | |
| federicocalo.github.io/climate-pulse (default) | URL gratis di default GitHub Pages, zero DNS | ✓ |

### Q3: Strategia di deploy GitHub Pages?

| Option | Description | Selected |
|--------|-------------|----------|
| GitHub-native Pages Action | actions/deploy-pages, env protection nativa | ✓ |
| peaceiris/actions-gh-pages | Legacy, deploy su branch gh-pages | |
| mike (versioned docs) | Versioned docs tool — overkill per Phase 1 | |

**Notes:** Custom domain `climatepulse.federicocalo.dev` rimandato a post-v1.0 (DNS config = costo che non vale per v0.1); `mike` rimandato a Phase 5 quando si tagga v1.0.0 (DOC-08).

---

## Footer Style (MkDocs)

### Q1: Contenuto del footer federicocalo.dev su MkDocs?

| Option | Description | Selected |
|--------|-------------|----------|
| Made with care by federicocalo.dev | Frase calda, attribuzione autore | |
| Climate Pulse · © 2026 · federicocalo.dev | Copyright classico con anno | |
| Solo 'federicocalo.dev' link | Minimal, una sola parola link | |
| Climate Pulse · MIT License · federicocalo.dev | License accanto all'attribuzione | ✓ |

### Q2: Stile visivo del footer su MkDocs Material?

| Option | Description | Selected |
|--------|-------------|----------|
| Override copyright nativo Material | Setto `copyright` in mkdocs.yml — minimal config | ✓ |
| Custom partial (overrides/partials/footer.html) | Pieno controllo — più lavoro | |
| Copyright + icona social federicocalo.dev | extra.social[] con icona world | |

### Q3: Link a federicocalo.dev nella navbar/header?

| Option | Description | Selected |
|--------|-------------|----------|
| No, solo footer | Minimal, attribuzione discreta | ✓ |
| Sì, link 'Author' in navbar | Più visibile | |
| Sì, icona social in topbar | Pulsante globe con tooltip | |

**Notes:** Footer text VERBATIM (stesso separatore `·`, stesse maiuscole) sarà riusato nella dashboard Angular in Phase 3 per consistenza visiva.

---

## Phase 1 Acceptance Demo

### Q1: Cosa vuoi vedere FUNZIONANTE alla fine di Phase 1?

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal: psql + docs live | Solo query SQL diretta + docs su GH Pages | |
| Mid: CLI tool 'climatepulse' + docs | Anche CLI thin che parla con TimescaleDB | |
| Full: anche /healthz HTTP endpoint | Aggiungi FastAPI minimo con /healthz + /readyz | ✓ |

### Q2: Quante stazioni Arpae per dichiarare 'done'?

| Option | Description | Selected |
|--------|-------------|----------|
| 1 stazione, 5+ variabili, 7+ giorni | Minimo significativo per schema | |
| Tutte le stazioni Arpae, 7+ giorni | Stress test scraping | |
| 5-10 stazioni, 30 giorni | Mid: valida compression (post-7d) + retention | ✓ |

### Q3: ECMWF Open Data scope Phase 1?

| Option | Description | Selected |
|--------|-------------|----------|
| Subset IT-only, 1 ciclo, 2-3 variabili | Minimo, MB invece di GB | |
| Subset EU, 4 cicli/day, 5+ variabili | Realistico, più pesante | ✓ |
| Solo IFS lo-res globale, 1 ciclo | Minimo assoluto | |

### Q4: Quickstart docs (DOC-05) cosa deve fare il visitatore in 5 min?

| Option | Description | Selected |
|--------|-------------|----------|
| Clone + docker compose up + psql query | Standard | |
| Anche backfill CLI di 1 stazione + verifica | `climatepulse backfill` come step | ✓ |
| Anche link a docs API future (Phase 2) | Promo roadmap | |

**Notes:** **SCOPE ADJUSTMENT registrato in D-14**: API-10 (`/healthz` + `/readyz`) e un minimal FastAPI skeleton vengono anticipati da Phase 2 a Phase 1. Il planner deve aggiornare REQUIREMENTS.md Traceability spostando API-10 da Phase 2 a Phase 1.

---

## Snapshot Fallback Storage

### Q1: Dove salvare snapshot quando ARPA è down?

| Option | Description | Selected |
|--------|-------------|----------|
| Docker volume locale `snapshots/` | Zero costo, zero deps esterne | ✓ |
| Filesystem path configurabile env | Più flessibile dev/prod | |
| S3-compatible (MinIO opzionale) | Self-hosted MinIO in Compose profile | |

### Q2: Formato snapshot?

| Option | Description | Selected |
|--------|-------------|----------|
| Raw payload + metadata.json | Debugging-friendly, no lock-in formato | |
| Parquet normalizzato | Storage efficiente ma perde raw fidelity | |
| JSON-LD canonical | Strutturato, interoperabile, parsing prima del salvataggio | ✓ |

### Q3: Retention snapshot?

| Option | Description | Selected |
|--------|-------------|----------|
| Rotazione ultimi N (es. 7 snapshot per source) | Cap su spazio | |
| 30 giorni rolling | Più contesto storico | ✓ |
| Append-only, manuale | Rischia esaurire disco | |

**Notes:** Volume Docker scelto come default, ma `SNAPSHOT_DIR` env var lo rende configurabile per produzione (best of both); JSON-LD canonical scelto nonostante richieda parsing pre-save (interoperabilità prevale su raw fidelity).

---

## ARPA Emilia-Romagna Endpoint

### Q1: Quale endpoint Arpae usare?

| Option | Description | Selected |
|--------|-------------|----------|
| dati.arpae.it REST/JSON | Portal open-data ufficiale, robots.txt, documentato | ✓ |
| Web service SMR via simc.arpae.it | TSI/RMQS, più grezzi ma meno docs | |
| Decidi tu (researcher investiga) | Lascio al gsd-phase-researcher | |

### Q2: Cadenza ingestion?

| Option | Description | Selected |
|--------|-------------|----------|
| 15 minuti (target produzione) | Coerente con PROJECT.md, stress politeness | ✓ |
| 1 ora | Più conservative inizialmente | |
| Configurabile via env (default 15min) | Massima flessibilità | |

### Q3: Cosa fare se Arpae cambia schema (silent break)?

| Option | Description | Selected |
|--------|-------------|----------|
| Quality flag 'schema_violation' + DLQ + alert | Marca riga, DLQ, canary unhealthy | ✓ |
| Fail-loud: stop adapter | Rompe altri sources | |
| Snapshot fallback + skip silenzioso | Dati silently obsoleti | |

**Notes:** L'opzione scelta è coerente con PITFALLS #20 (silent adapter break) e ING-14 (canary metric).

---

## ECMWF GRIB Parsing

### Q1: cfgrib + libeccodes0 (~300MB) accettato?

| Option | Description | Selected |
|--------|-------------|----------|
| Sì, cfgrib + libeccodes0 standard | One-time cost nel worker container | ✓ |
| Separare worker GRIB in container dedicato | `ecmwf-worker` Compose service | |
| Tentare NetCDF se disponibile | Più leggero ma ECMWF è GRIB primario | |

### Q2: Conferma ECMWF subset 'EU + 4 cicli + 5+ variabili'?

| Option | Description | Selected |
|--------|-------------|----------|
| Confermo: EU + 4 cicli + 5+ var | Conferma decisione | ✓ |
| Riduco: EU + 2 cicli/day | Meno banda | |
| Riduco: solo IT bbox + 4 cicli | Coerente focus Italia | |

### Q3: Storage 'virtual station' per grid-based?

| Option | Description | Selected |
|--------|-------------|----------|
| 1 virtual station per grid node + flag | Schema unificato con ARPA | |
| Tabella dedicata `gridded_observations` | Separazione netta — rompe principio "una hypertable" della research | ✓ |
| Interpolazione runtime su query | Defer post-v1.0 | |

### Q4 (follow-up): Confermo separazione `gridded_observations`?

| Option | Description | Selected |
|--------|-------------|----------|
| Confermo tabella dedicata | Accetto raddoppio ops complexity | ✓ |
| Rivedo: single hypertable con virtual station | Seguo research | |
| Compromesso: VIEW logica su `observations` | Una tabella fisica + vista | |

**Notes:** **DEVIAZIONE CONSAPEVOLE dalla research** — segnalata al user (PITFALLS raccomanda una sola hypertable); utente ha confermato dopo che è stato spiegato il trade-off (doubled CAGGs/policies/read paths). Planner deve progettare due hypertable + due CAGG `obs_hourly` + `gridded_hourly` + due retention/compression policy + resolution resolver in API (Phase 2) che route in base a tipo query.

---

## Testing Strategy + Coverage Gate

### Q1: Threshold coverage CI gate Phase 1?

| Option | Description | Selected |
|--------|-------------|----------|
| 80% globale, 70% adapters | Bilanciato, ammette difficoltà adapter | ✓ |
| 70% globale | Più permissivo | |
| 85% globale, 80% adapters | Aggressivo | |
| No gate Phase 1, attiva da Phase 2 | Solo informativa | |

### Q2: testcontainers (TimescaleDB) in CI obbligatorio?

| Option | Description | Selected |
|--------|-------------|----------|
| Obbligatorio in CI | Integration test su Timescale reale | ✓ |
| Opzionale, fallback Postgres+extension | Più veloce ma perde CAGG/compression | |
| Solo unit test in CI, integration in pre-merge | CI veloce ma drift rischioso | |

### Q3: Property-based testing (hypothesis) — quali aree?

| Option | Description | Selected |
|--------|-------------|----------|
| Normalizer + Timezone DST round-trip | Hotspot silent corruption per PITFALLS | ✓ |
| Anche idempotency writer | Aggiunge property test ON CONFLICT | |
| Case-by-case | Niente target | |

### Q4: VCR.py fixtures per ARPA — livello?

| Option | Description | Selected |
|--------|-------------|----------|
| Cassette VCR completi 5+ scenari | 200/304/404/500/timeout | ✓ |
| respx hand-written minimal | Più leggero ma meno fedele | |
| Entrambi: VCR happy + respx errors | Best of both | |

**Notes:** Coverage gate 80%/70% è bilanciato per scope Phase 1; testcontainers obbligatorio evita regression su DDL TimescaleDB; property-based focalizzato su Normalizer + Timezone (i due hotspot di silent corruption); VCR completi su 5 scenari realistici (rec una volta, replay in CI).

---

## Claude's Discretion

Aree dove il planner ha flessibilità (non richiedono decisione utente):
- Compose network topology (single vs separated) — sceglie planner.
- CI matrix strategy (single OS vs matrix) — default `ubuntu-22.04` + `python 3.12.7`.
- Adapter ABC interface contract (sync iter / async gen / batch return) — researcher in plan-phase decide; constraint: deve supportare entrambi station-batch e grid-batch.
- Logging config (structlog handlers, formatters) — JSON in prod / console in dev.
- Test fixture organization, helper layout.

---

## Deferred Ideas

- **Custom domain `climatepulse.federicocalo.dev`** — re-evaluate post-v1.0 se traffico giustifica DNS setup.
- **`mike` docs versioning** — Phase 5 (DOC-08, paired con tag v1.0.0).
- **Navbar `Author` link / social icon a federicocalo.dev** — declinato per v0.1; revisit se community chiede.
- **VCR cassette extra per scenari ARPA non-200** — estensione corpus in Phase 4 con Lombardia + Veneto adapter.
- **MinIO snapshot storage profile** — solo se volume locale diventa unmanageable; reconsider Phase 5.
- **`/v1/sources/status` UI endpoint** — Phase 3 (dashboard source health page); backend metric `last_successful_ingest_at` raccolto già in Phase 1 (ING-14).
- **CI matrix multi-OS / multi-Python** — defer a Phase 5; Phase 1 single target sufficiente.
