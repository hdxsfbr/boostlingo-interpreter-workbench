# AI Interpreter Workbench: Realtime API vs Cascade Pipeline

A Gauntlet partner project for **Boostlingo**. It is a browser workbench that interprets a live English ↔ Spanish conversation through two architectures:
- **Realtime mode:** OpenAI Realtime API, `gpt-realtime`, voice-to-voice.
- **Cascade mode:** a streaming STT → Translation → TTS pipeline with swappable providers.

Both modes are instrumented with per-stage latency, and a comparison write-up recommends which architecture fits which scenario.

## Status

Planning: no application code yet. **Due Sunday 2026-10-11.**

## Key files

- `docs/PRD.md`: the build-ready PRD (requirements, benchmarks, deliverables, open decisions)
- `sources/assignment.pdf`: the authoritative assignment brief from Boostlingo
- `sources/portal-project.md`: captured Gauntlet portal text (company info, brief, submission form)

## Planned layout

```
sources/                 # supplied originals (read-only)
docs/PRD.md              # requirements
docs/comparison.md       # 1–2 page Realtime vs Cascade write-up (deliverable)
docs/benchmarks/         # latency exports, utterance set, soak-test notes
AGENTS.md                # how the coding agent was directed (required)
backend/                 # ASP.NET Core (proposed; see PRD Q1)
frontend/                # React + TypeScript + Vite (proposed)
.env.example             # required variables, no values
```

Setup and run instructions will be added once the stack is scaffolded. API keys go in a local, gitignored `.env` file. They are never committed and never sent to the browser.

## Lab notes

- Host: `hdx-lab` at `~/code/boostlingo-interpreter-workbench`
- Remote: labs.gauntletai.com/andrebatista/boostlingo-interpreter-workbench (private)
- Owner: Andre (Gauntlet Cohort G7)
