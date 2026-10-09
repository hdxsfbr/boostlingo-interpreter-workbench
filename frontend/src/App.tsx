import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { harnessHook, InterpreterSession, type RealtimeKind } from "./session/InterpreterSession";
import type { TurnMode } from "./session/transports/realtimeWebrtc";
import type { Mode, Pipeline, SessionEvent, Speaker } from "./session/protocol";
import { dismissError, initialState, reduce, type State } from "./store/reducer";
import { useTurnSink } from "./store/turnSink";
import { Controls, type RecordingConfig, type Swaps } from "./ui/Controls";
import { ErrorBanner } from "./ui/ErrorBanner";
import { MetricsSummary } from "./ui/MetricsSummary";
import { TranscriptPane } from "./ui/TranscriptPane";
import { ReviewTab } from "./review/ReviewTab";
import { ExperimentsTab } from "./experiments/ExperimentsTab";
import { fetchLanguages, pickPair, type LanguagesConfig } from "./languages";
import { setLanguageNames } from "./session/realtimePrompt";


type Action = { kind: "ev"; ev: SessionEvent } | { kind: "dismiss"; id: number };
const appReducer = (s: State, a: Action): State => (a.kind === "ev" ? reduce(s, a.ev) : dismissError(s, a.id));

export default function App() {
  const params = new URLSearchParams(location.search);
  const [pipeline, setPipelineState] = useState<Pipeline>((params.get("pipeline") as Pipeline) ?? "cascade");
  const initialMode: Mode = params.get("mode") === "realtime" ? "realtime" : "cascade";
  const realtimeKind = (params.get("rt") as RealtimeKind | null) ?? "auto";
  const [turnMode, setTurnModeState] = useState<TurnMode>(params.get("turn") === "vad" ? "vad" : "ptt");
  const [state, dispatch] = useReducer(appReducer, initialState(initialMode));
  const initialProviders: Record<string, string> = {};
  for (const k of ["mt", "tts"]) if (params.get(k)) initialProviders[k] = params.get(k)!;
  const [chosen, setChosen] = useState<Record<string, string>>(initialProviders);
  const [swaps, setSwaps] = useState<Swaps | null>(null);
  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((h) => setSwaps(h.swaps ?? null))
      .catch(() => setSwaps(null));
  }, []);
  // A11: opt-in recording; the server flag gates the toggle (and the server refuses on its own).
  const [recCfg, setRecCfg] = useState<RecordingConfig | null>(null);
  const [recordWanted, setRecordWanted] = useState(params.get("record") === "1");
  useEffect(() => {
    fetch("/api/recordings/config")
      .then((r) => r.json())
      .then((c) => setRecCfg(c))
      .catch(() => setRecCfg(null));
  }, []);
  const recording = recordWanted && !!recCfg?.enabled;
  type Tab = "interpreter" | "review" | "experiments";
  const [tab, setTab] = useState<Tab>((["review", "experiments"].includes(params.get("tab") ?? "") ? params.get("tab") : "interpreter") as Tab);
  // A14: pairs come from config/languages.yaml; ?pair= picks one (id or "a-b"), else the default pair.
  const [langs, setLangs] = useState<LanguagesConfig | null>(null);
  const [pairId, setPairId] = useState<string | null>(null);
  const [langErr, setLangErr] = useState<string | null>(null);
  useEffect(() => {
    fetchLanguages().then(
      (c) => {
        setLanguageNames(Object.fromEntries(Object.entries(c.languages).map(([k, v]) => [k, v.name])));
        setLangs(c);
        setPairId(pickPair(c, params.get("pair")).id);
      },
      (e) => setLangErr((e as Error).message),
    );
  }, []);
  const pairInfo = langs && pairId ? langs.pairs.find((p) => p.id === pairId) ?? null : null;
  const pair = pairInfo ? { a: pairInfo.a, b: pairInfo.b } : null;
  const pairRef = useRef<{ a: string; b: string } | null>(null);
  pairRef.current = pair;
  const sessionPair = useRef<string | null>(null);
  const sessionRef = useRef<InterpreterSession | null>(null);
  const [active, setActive] = useState<Speaker | null>(null);

  const session = useCallback(() => {
    const want = pairRef.current ?? { a: "", b: "" };
    if (sessionRef.current && sessionPair.current !== `${want.a}-${want.b}`) {
      void sessionRef.current.stop(); // the pair changed while idle: next session uses the new pair
      sessionRef.current = null;
    }
    if (!sessionRef.current) {
      sessionPair.current = `${want.a}-${want.b}`;
      const s = new InterpreterSession({ pair: want, mode: initialMode, pipeline, turnMode, realtime: realtimeKind, providers: initialProviders,
        source: params.get("source") === "file" ? "file" : "mic",
        silenceDurationMs: Number(params.get("vad_ms")) || undefined,
        pauseHintMs: Number(params.get("hint_ms")) || null, // off by default: no gain measured in M4
        minSegmentMs: Number(params.get("min_seg_ms")) || 0, // A/B only: the server merges fragments instead (M5)
        vadSpeaker: params.get("vad_speaker") === "B" ? "B" : "A",
        realtimeModel: params.get("rt_model") ?? undefined });
      s.on((ev) => dispatch({ kind: "ev", ev }));
      sessionRef.current = s;
    }
    return sessionRef.current;
  }, []);

  useTurnSink(state);
  useEffect(() => {
    harnessHook().state = state;
  }, [state]);

  const running = state.sessionState === "ready" || state.sessionState === "connecting";
  const start = () => {
    session().setRecording(recording);
    void session().start();
  };
  const stop = () => void session().stop();
  const setMode = (m: Mode) => void session().setMode(m);
  const setProvider = (kind: "mt" | "tts", name: string) => {
    setChosen((c) => ({ ...c, [kind]: name }));
    void session().setProviders({ [kind]: name });
  };
  const [vadSpeaker, setVadSpeakerState] = useState<Speaker>(params.get("vad_speaker") === "B" ? "B" : "A");
  const setVadSpeaker = (sp: Speaker) => {
    setVadSpeakerState(sp);
    session().setVadSpeaker(sp);
  };
  const setTurnMode = (m: TurnMode) => {
    setTurnModeState(m);
    void session().setTurnMode(m);
  };
  const setPipeline = (p: Pipeline) => {
    setPipelineState(p);
    void session().setPipeline(p);
  };
  const down = (sp: Speaker) => {
    if (active) return;
    setActive(sp);
    session().pttDown(sp);
  };
  const up = (sp: Speaker) => {
    if (active !== sp) return;
    setActive(null);
    session().pttUp(sp);
  };

  // Keyboard PTT: hold F = Speaker A, hold J = Speaker B.
  useEffect(() => {
    const keyToSpeaker = (k: string): Speaker | null => (k === "f" ? "A" : k === "j" ? "B" : null);
    if (tab !== "interpreter") return; // the Review tab owns the keyboard
    const kd = (e: KeyboardEvent) => {
      const sp = keyToSpeaker(e.key.toLowerCase());
      if (sp && !e.repeat && state.sessionState === "ready") down(sp);
    };
    const ku = (e: KeyboardEvent) => {
      const sp = keyToSpeaker(e.key.toLowerCase());
      if (sp) up(sp);
    };
    window.addEventListener("keydown", kd);
    window.addEventListener("keyup", ku);
    return () => {
      window.removeEventListener("keydown", kd);
      window.removeEventListener("keyup", ku);
    };
  });

  return (
    <div className="app">
      <header>
        <h1>AI Interpreter Workbench</h1>
        <nav className="toggle tabs" role="tablist" aria-label="Workbench">
          {(["interpreter", "review", "experiments"] as const).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)} data-testid={`tab-${t}`}>
              {t === "interpreter" ? "Interpreter" : t === "review" ? "Review" : "Experiments"}
            </button>
          ))}
        </nav>
        {running && recording && (
          <span className="rec-indicator" data-testid="rec-indicator" title="Both sides of every turn are being saved on this server">
            ● Recording
          </span>
        )}
        <span className={`state state-${state.sessionState}`}>{state.sessionState}</span>
      </header>
      {tab === "review" ? (
        <ReviewTab />
      ) : tab === "experiments" ? (
        <ExperimentsTab />
      ) : (
        <>
      {langErr ? <div className="error blocking" role="alert">Could not load language pairs ({langErr}); reload the page.</div> : null}
      <ErrorBanner errors={state.errors} onDismiss={(id) => dispatch({ kind: "dismiss", id })} onRetry={start} sessionState={state.sessionState} />
      <Controls
        mode={state.mode}
        turnMode={turnMode}
        swaps={swaps}
        chosen={chosen}
        onProvider={setProvider}
        recording={{ config: recCfg, on: recording, onToggle: setRecordWanted }}
        onTurnMode={setTurnMode}
        vadSpeaker={vadSpeaker}
        onVadSpeaker={setVadSpeaker}
        pipeline={pipeline}
        pair={pair ?? { a: "", b: "" }}
        pairs={langs?.pairs}
        canStart={!!pair}
        onPair={(id) => setPairId(id)}
        running={running}
        ready={state.sessionState === "ready"}
        active={active}
        providers={state.providers}
        onStart={start}
        onStop={stop}
        onMode={setMode}
        onPipeline={setPipeline}
        onDown={down}
        onUp={up}
      />
      <main>
        <TranscriptPane state={state} />
        <MetricsSummary state={state} />
      </main>
        </>
      )}
    </div>
  );
}
