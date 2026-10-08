# Portal capture: Boostlingo — AI Interpreter Workbench

Captured by Grok Bot on **2026-10-08 at ~5:50 PM CT** from the Gauntlet portal, using Andre's signed-in Chrome on hdx-macbook. The capture was read-only:
- Nothing was submitted, selected or changed.
- The submission dialog was opened only to read its fields, and the tab was closed without submitting.

Text inside the fenced blocks is copied verbatim from the page (`document.body.innerText`). Navigation chrome, such as notification badge counts and the "Back to Partner Projects" link, was removed.

| Item | Value |
|---|---|
| Project page | https://portal.gauntletai.com/projects/y0HErEPMMy4awsorSYIh |
| Listing | https://portal.gauntletai.com/projects ("Partner projects": Boostlingo · Platinum · **Not Started** · AI Interpreter Workbench) |
| Brief version | Version 1, "Last updated 8/7/2026" (as shown on the portal) |
| Attachment | `Boostlingo_Project Title AI Interpreter Workbench_ Realtime API vs. Cascade Pipeline.pdf`. Downloaded from the portal; SHA-256 `dfcb03bce12ba543e31d62f609f2bfb5d28bc09db5d1fd608909be1323d9f071`, **byte-identical** to `sources/assignment.pdf` |
| Links | "No links available." |
| Due date | **Not shown anywhere on the portal pages checked.** The due date of Sunday 2026-10-11 comes from Andre, relayed by the parent agent |
| Contacts | **None listed** on the project page, company card or partner listing. No technical contact is named, unlike some other briefs |
| Project already assigned? | Yes: it appears under "Your assigned projects and project submissions" with status "Not Started". No select/enroll action was needed or taken |

## 1. Project brief (project page)

```text
PROJECT BRIEF

AI Interpreter Workbench

Boostlingo

PLATINUM
Version 1
AI-SOLUTION

Last updated 8/7/2026

PRD

Boostlingo needs to evaluate two architectural approaches for live language interpretation: direct voice-to-voice models and composable cascade pipelines. The challenge is to build and instrument both approaches to understand their trade-offs in latency, quality, cost, and operational control.

PROBLEM & CONTEXT

BUSINESS CONTEXT

Live interpretation is Boostlingo's core product. As AI becomes more viable, the right architectural choice will determine cost efficiency, latency, vendor flexibility, and ability to support diverse language pairs in the interpretation market.

IMPACT METRICS

End-to-end latency (ms), Cost per minute of interpretation, Interpretation quality (WER), Provider flexibility, Time-to-onboard new language pairs

REQUIREMENTS & SUCCESS CRITERIA

FUNCTIONAL REQUIREMENTS

Browser-based SPA with microphone capture, Realtime mode with OpenAI Realtime API, Cascade mode with STT → Translation → TTS pipeline, Mode switching UI, Language pair selection (English ↔ Spanish), Live transcripts, Latency display

PERFORMANCE BENCHMARKS

Realtime mode: under 1.5s end-to-end perceived latency (speech end → first audio out).
Cascade mode: under 3s end-to-end, target under 2s with full streaming.
Stability: sustain a 5-minute back-and-forth conversation without disconnection, audio drift, or memory leaks.


CODE QUALITY EXPECTATIONS

Clean mode-specific transport separation, Provider abstractions, Targeted pipeline testing, Error handling, Comprehensive documentation, Meaningful git commits

TIME CONSTRAINTS

3-4 days (15-20 hours total effort)

TECHNOLOGY

REQUIRED LANGUAGES

.NET, C#, TypeScript, Python

AI / ML FRAMEWORKS

OpenAI Realtime API, OpenAI, Anthropic Claude, DeepL, Deepgram, AssemblyAI, Soniox, ElevenLabs, Azure Speech, Polly

DEV TOOLS

Git, Web framework, Package manager, Agentic coding assistant (Claude Code, Codex, Cursor)

CLOUD PLATFORMS

AWS

OTHER REQUIREMENTS

Provider abstractions for STT/translation/TTS, Streaming cascade pipeline, Per-stage latency instrumentation, Git history documentation

ATTACHMENTS

Boostlingo_Project Title AI Interpreter Workbench_ Realtime API vs. Cascade Pipeline.pdf 

LINKS

No links available.

Submit this project

Submit directly from this page. Your submission is tied to this project version.

Open Submission Interface
```

## 2. Company info (dialog opened from the projects list)

```text
B

Boostlingo

SaaS

51–200 employees

PLATINUM PARTNER
www.boostlingo.com

Week 4

INTERVIEW ACCESS

26–50

ENG TEAM SIZE

ABOUT THE COMPANY

Why Boostlingo Exists — and Why It Matters Language is the foundation of human connection — and for millions of people navigating hospitals, courtrooms, schools, and government offices, a language barrier isn't just an inconvenience, it's a crisis. Boostlingo was built to fix that. We've engineered an all-in-one Language Intelligence Platform, offering both human and AI powered interpretation, AI translation, and a host of other critical language access solutions in a platform that makes language access instant, intelligent, and scalable — connecting people to certified human interpreters or AI-powered translation in seconds, across 300+ languages, 24/7. We replaced a fragmented, slow, and expensive industry with a platform that just works — and the market has responded. The Scale of the Problem We're Solving This isn't a niche market. The organizations depending on seamless language access include some of the most critical institutions in the world — health care systems, federal and state government agencies, legal systems, global enterprises, and universities. When communication breaks down in these environments, the consequences are real: missed diagnoses, legal errors, excluded students, disengaged employees. We eliminate that failure point. What Makes the Engineering Challenge Interesting Our platform has to do a lot of things exceptionally well — simultaneously: Route interpreter calls in under 13 seconds on average, at scale Support phone, video, and AI-driven translation across thousands of concurrent sessions Maintain HIPAA, SOC 2 Type II, and GDPR compliance without sacrificing speed or UX Integrate with Zoom, Microsoft Teams, Webex, QuickBooks, Stripe, and more Power a global network of 17,000+ interpreters through a scheduling, billing, and management system built for real-time operations This is genuinely hard infrastructure — and it matters every time it runs. The Opportunity Boostlingo is growing fast, operating at the intersection of AI, real-time communications, and global enterprise software — one of the most exciting corners of the tech landscape right now. Companies that switch to our platform save around 20% on interpreting costs, and our customer satisfaction scores reflect a product people genuinely love. You'd be joining a team solving meaningful problems, at meaningful scale, with technology that is getting smarter every day. If you're the kind of engineer who wants their work to matter beyond the sprint cycle — this is the role.

TECHNICAL STACK

DATABASES & DATA STORES

Postgres
SQL Server
Redis

INFRASTRUCTURE & DEPLOY

AWS
Docker
CI/CD

DATA & MESSAGING

SQS

AI & APPLIED ML

LLM APIs
Agents
Prompt Engineering

ENGINEERING ENVIRONMENT

COVERAGE

Mixed greenfield and legacy

PRIMARY FOCUS

Customer facing solutions

WORKING STYLE

Async / Remote-First

5/5

High Autonomy

5/5

Ambiguous Problem Solving

5/5

Cross-Functional Collaboration

5/5

Customer-Facing Interaction

3/5

INTERVIEW PROCESS

3–4

INTERVIEW ROUNDS

No

CODING ASSESSMENT
```

## 3. Partner listing (https://portal.gauntletai.com/partners)

The Boostlingo card on the "Hiring partners" page (verbatim):

```text
Boostlingo

SaaS

Platinum
Remote

Remote

Senior Full-Stack Agentic Engineer · full-stack

View full profile →
```

"View full profile" opens the same company dialog as §2.

## 4. Submission interface (dialog from "Open Submission Interface"; read only, cancelled)

```text
SUBMISSION

Submit Assignment

AI Interpreter Workbench

Assignment Details:

Boostlingo needs to evaluate two architectural approaches for live language interpretation: direct voice-to-voice models and composable cascade pipelines. The challenge is to build and instrument both approaches to understand their trade-offs in latency, quality, cost, and operational control.

Hiring Partner

REQUIRED

Project Name

REQUIRED

GitLab Repository

REQUIRED

Deployed Link (Optional)

Project Access (Optional)

If your deployed app requires login credentials, provide them so graders and the hiring partner can access it.

Username

Password

Demo Video URL (Optional)

Additional Notes (Optional)

Cancel
Submit Assignment
```

Form fields as rendered (prefilled values and placeholders):

```text
INPUT name= type=text placeholder= value=Boostlingo text=
INPUT name= type=text placeholder=Enter the name of your project value=AI Interpreter Workbench text=
INPUT name= type=url placeholder=https://labs.gauntletai.com/group/project value= text=
INPUT name= type=url placeholder=https://your-app.vercel.app value= text=
INPUT name= type=text placeholder=demo@example.com value= text=
INPUT name= type=text placeholder=password123 value= text=
INPUT name= type=url placeholder=https://youtube.com/watch?v=... or https://vimeo.com/... value= text=
TEXTAREA name= type=textarea placeholder=Any additional comments or notes about your submission... value= text=
```

**Submission requirements, from the form:**
- Required: Hiring Partner (prefilled "Boostlingo"), Project Name (prefilled "AI Interpreter Workbench") and GitLab Repository (placeholder `https://labs.gauntletai.com/group/project`).
- Optional: Deployed Link, Project Access (username/password for a deployed app), Demo Video URL (YouTube/Vimeo) and Additional Notes.

## 5. Differences between the portal and the PDF

- **Last updated date.** The portal shows "Last updated 8/7/2026". The PDF has no date.
- **Impact metrics.** The portal lists "Interpretation quality (WER)". The PDF says "interpretation quality (subjective + WER)".
- **Functional requirements.** The portal gives a condensed list. It omits the PDF's must-have #8 (the 1–2 page comparison write-up) and the "mid-session or pre-session" detail of the mode toggle. **The PDF is more complete and is treated as authoritative.**
- **Required languages.** The portal lists ".NET, C#, TypeScript, Python" without the PDF's nuance: "Candidate's choice — preferred: .NET / C# (backend), TypeScript (frontend). Python is acceptable. Candidate should explain their choice."
- **Cloud platforms.** The portal lists "AWS". The PDF says cloud is optional, deployment is encouraged but not required, AWS is preferred if deploying, and local-only is fine.
- **Code quality.** The portal adds "Comprehensive documentation".
- **Portal-only information:**
  - company size (51–200 employees; engineering team 26–50);
  - "Week 4" interview access;
  - 3–4 interview rounds, no coding assessment;
  - the partner's technical stack;
  - working-style ratings;
  - the role title "Senior Full-Stack Agentic Engineer · full-stack" (Remote).
