import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp,
  ArrowLeft,
  X,
  SlidersHorizontal,
  Bot,
  Wallet,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useToast } from "../../hooks/useToast";
import { createAIDraftController, createAIDraftStore, aiDraftScope } from "./aiDrafts";
import { api, authSession, getErrorMessage } from "../../services/api";
import { tmaService as service } from "../../services/tmaService";

// CBT composer interaction model, adapted to authenticated TMA generation APIs.
export default function TmaAIComposer({
  open,
  assignmentId,
  label,
  onClose,
  role,
  revisionNumber,
  onReview,
}) {
  const { showError } = useToast();
  const [prompt, setPrompt] = useState("");
  const [sent, setSent] = useState("");
  const [count, setCount] = useState(5);
  const [difficulty, setDifficulty] = useState("medium");
  const [visuals, setVisuals] = useState("text_only");
  const difficultyOptions = ["easy", "medium", "difficult"];
  const [busy, setBusy] = useState(false);
  const [drafts, setDrafts] = useState([]);
  const user = authSession.getUser();
  const scope = user ? aiDraftScope(user, role, assignmentId) : null;
  const store = useMemo(() => scope ? createAIDraftStore(scope) : null, [scope]);
  const controller = useMemo(() => store ? createAIDraftController({ store, service, assignmentId, revisionNumber }) : null, [store, assignmentId, revisionNumber]);
  const [quota, setQuota] = useState(null);
  const credits = quota?.total_available_credits ?? null;
  const pending = useRef(false);
  const mounted = useRef(false);
  const composer = useRef(null);
  const options = useRef(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event) => {
      if (options.current && !options.current.contains(event.target)) options.current.open = false;
    };
    const escape = (event) => {
      if (event.key === "Escape" && options.current?.open) {
        options.current.open = false;
        options.current.querySelector("summary")?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!open) return;
    composer.current?.focus();
    store?.list().then(setDrafts).catch(() => showError("Browser draft storage is unavailable. Enable site storage to continue."));
    let active = true;
    api
      .get("/ai/quota")
      .then((r) => {
        if (active) setQuota(r);
      })
      .catch(() => {
        if (active) setQuota(null);
      });
    return () => {
      active = false;
    };
  }, [open, store, showError]);
  const act = async (fn) => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);

    try {
      await fn();
    } catch (e) {
      if (mounted.current)
        showError(
          getErrorMessage(e, "This operation could not be confirmed. Please retry."),
        );
    } finally {
      pending.current = false;
      if (mounted.current) {
        setBusy(false);
        api
          .get("/ai/quota")
          .then((r) => {
            if (mounted.current) setQuota(r);
          })
          .catch(() => {});
      }
    }
  };
  const generate = (e) => {
    e.preventDefault();
    if (
      !prompt.trim() ||
      !Number.isInteger(count) ||
      count < 1 ||
      count > 50 ||
      credits === 0
    )
      return;
    const body = {
      generation_prompt: prompt.trim(),
      question_count: count,
      difficulty,
      visual_mode: visuals,
    };
    setSent(prompt.trim());
    setPrompt("");
    act(async () => {
      if (!controller || !revisionNumber) throw new Error("Wait for the assignment to load before generating.");
      try {
        const draft = await controller.generate(body);
        onReview(draft.draft_id);
      } finally {
        if (mounted.current) setDrafts(await store.list());
      }
    });
  };
  return (
    <aside className="tma-ai-composer" aria-label="AI question assistant">
      <button type="button" className="tma-ai-return" onClick={onClose}>
        <ArrowLeft size={18} /> Back to assignment
      </button>
      <header className="tma-ai-heading">
        <span className="tma-ai-icon">
          <Bot size={18} />
        </span>
        <div>
          <h2>Generate questions</h2>
          <p>{label}</p>
        </div>
        <button type="button" aria-label="Close AI assistant" onClick={onClose}>
          <X size={19} />
        </button>
      </header>
      <div className="tma-ai-conversation" aria-busy={busy}>
        {!sent && (
          <div className="tma-ai-welcome">
            <img src="/icons/weave-email-icon.png" alt="" />
            <h3>What are we teaching today?</h3>
            <p>
              Describe a topic. Weave will use this assignment’s level and
              subject to prepare questions for review.
            </p>
          </div>
        )}
        {sent && <div className="tma-ai-user-message">{sent}</div>}
        {busy && (
          <p role="status" className="tma-ai-progress">
            <span />
            Preparing your questions…
          </p>
        )}
        {drafts.length > 0 && (
          <div className="space-y-3">
            <p className="text-xs font-semibold text-text-muted">Saved on this browser</p>
            {drafts.map((draft) => (
              <Link key={draft.draft_id} className="block rounded-xl border border-border bg-surface p-3 text-sm hover:bg-surface-muted"
                to={`/${role}/tma/${assignmentId}/ai-drafts/${draft.draft_id}`}
                onClick={(e) => { e.preventDefault(); onReview(draft.draft_id); }}>
                <strong>{draft.questions.length || draft.input.question_count} questions · {draft.status === "review" ? "Review draft" : "Recover draft"}</strong>
                <span className="mt-1 block truncate text-xs text-text-muted">{draft.input.generation_prompt}</span>
              </Link>
            ))}
          </div>
        )}
      </div>
      <div className="tma-ai-bottom">
        <form className="tma-ai-prompt" onSubmit={generate}>
          <textarea
            ref={composer}
            aria-label="Describe questions to generate"
            placeholder="e.g. Questions on cell structures with everyday examples…"
            rows={3}
            maxLength={10000}
            value={prompt}
            disabled={busy}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                e.currentTarget.form.requestSubmit();
              }
            }}
          />
          <div className="tma-ai-prompt-actions">
            <details ref={options} className="tma-ai-options">
              <summary>
                <SlidersHorizontal size={15} />
                {count} questions · {difficulty}
              </summary>
              <div>
                <label>
                  Questions
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={count}
                    disabled={busy}
                    onChange={(e) => setCount(Number(e.target.value))}
                  />
                </label>
                <div className="tma-ai-difficulty">
                  <label htmlFor="tma-ai-difficulty">Difficulty · {difficulty}</label>
                  <input
                    id="tma-ai-difficulty"
                    type="range"
                    min={0}
                    max={2}
                    step={1}
                    value={difficultyOptions.indexOf(difficulty)}
                    disabled={busy}
                    aria-valuetext={difficulty}
                    onChange={(e) => setDifficulty(difficultyOptions[Number(e.target.value)])}
                  />
                  <div aria-hidden="true" className="tma-ai-difficulty-labels">
                    <span>Easy</span><span>Medium</span><span>Difficult</span>
                  </div>
                </div>
                <fieldset className="tma-ai-choices">
                  <legend>Visuals</legend>
                  {[
                    ["text_only", "Text only"],
                    ["auto", "Allow images"],
                  ].map(([v, label]) => (
                    <label key={v}>
                      <input
                        type="radio"
                        name="tma-visuals"
                        value={v}
                        checked={visuals === v}
                        disabled={busy}
                        onChange={() => setVisuals(v)}
                      />
                      <span>{label}</span>
                    </label>
                  ))}
                </fieldset>
                <p>Single-choice questions · at least four options.</p>
              </div>
            </details>
            <button
              type="submit"
              className="tma-ai-send"
              aria-label="Generate questions"
              disabled={
                busy ||
                !prompt.trim() ||
                !Number.isInteger(count) ||
                count < 1 ||
                count > 50 ||
                credits === 0
              }
            >
              <ArrowUp size={19} />
            </button>
          </div>
        </form>
        <div className="tma-ai-footer">
          <span>
            <Wallet size={14} />
            {credits ?? "—"} AI credits
          </span>
          <span>Review before adding</span>
        </div>
        {credits === 0 && (
          <p className="text-xs text-error">
            Your AI credit balance is exhausted.
          </p>
        )}
      </div>
    </aside>
  );
}
