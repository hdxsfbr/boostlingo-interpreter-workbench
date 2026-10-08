import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { harnessHook, InterpreterSession } from "./session/InterpreterSession";
import type { Mode, Pipeline, SessionEvent, Speaker } from "./session/protocol";
import { dismissError, initialState, reduce, type State } from "./store/reducer";
import { useTurnSink } from "./store/turnSink";
import { Controls } from "./ui/Controls";
import { ErrorBanner } from "./ui/ErrorBanner";
import { MetricsSummary } from "./ui/MetricsSummary";
import { TranscriptPane } from "./ui/TranscriptPane";

const PAIR = { a: "en", b: "es" };

type Action = { kind: "ev"; ev: SessionEvent } | { kind: "dismiss"; id: number };
const appReducer = (s: State, a: Action): State => (a.kind === "ev" ? reduce(s, a.ev) : dismissError(s, a.id));

export default function App() {
  const params = new URLSearchParams(location.search);
  const [pipeline, setPipelineState] = useState<Pipeline>((params.get("pipeline") as Pipeline) ?? "cascade");
  const [state, dispatch] = useReducer(appReducer, initialState("cascade"));
  const sessionRef = useRef<InterpreterSession | null>(null);
  const [active, setActive] = useState<Speaker | null>(null);

  const session = useCallback(() => {
    if (!sessionRef.current) {
      const s = new InterpreterSession({ pair: PAIR, mode: "cascade", pipeline });
      s.on((ev) => dispatch({ kind: "ev", ev }));
      sessionRef.current = s;
    }
    return sessionRef.current;
  }, [pipeline]);

  useTurnSink(state);
  useEffect(() => {
    harnessHook().state = state;
  }, [state]);

  const running = state.sessionState === "ready" || state.sessionState === "connecting";
  const start = () => void session().start();
  const stop = () => void session().stop();
  const setMode = (m: Mode) => void session().setMode(m);
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
        <span className={`state state-${state.sessionState}`}>{state.sessionState}</span>
      </header>
      <ErrorBanner errors={state.errors} onDismiss={(id) => dispatch({ kind: "dismiss", id })} onRetry={start} sessionState={state.sessionState} />
      <Controls
        mode={state.mode}
        pipeline={pipeline}
        pair={PAIR}
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
    </div>
  );
}
