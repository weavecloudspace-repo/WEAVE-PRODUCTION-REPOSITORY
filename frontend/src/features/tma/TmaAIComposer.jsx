import { useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  X,
  SlidersHorizontal,
  Sparkles,
  Wallet,
  RotateCw,
  Check,
} from "lucide-react";
import Button from "../../components/ui/Button";
import MathText from "./MathText.jsx";
import { api } from "../../services/api";
import { tmaService as service } from "../../services/tmaService";

function Illustration({ image }) {
  return image?.data_base64 &&
    ["image/png", "image/jpeg", "image/webp"].includes(image.content_type) ? (
    <img
      className="max-h-56 max-w-full rounded-xl object-contain"
      src={`data:${image.content_type};base64,${image.data_base64}`}
      alt={image.alt_text || "Question illustration"}
    />
  ) : null;
}

// CBT composer interaction model, adapted to authenticated TMA generation APIs.
export default function TmaAIComposer({
  open,
  assignmentId,
  label,
  onClose,
  onImported,
}) {
  const [prompt, setPrompt] = useState("");
  const [sent, setSent] = useState("");
  const [count, setCount] = useState(5);
  const [difficulty, setDifficulty] = useState("medium");
  const [visuals, setVisuals] = useState("text_only");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [questions, setQuestions] = useState([]);
  const [credits, setCredits] = useState(null);
  const [instruction, setInstruction] = useState("");
  const request = useRef(null);
  const regeneration = useRef(null);
  const pending = useRef(false);
  const mounted = useRef(false);
  const composer = useRef(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!open) return;
    composer.current?.focus();
    let active = true;
    api
      .get("/ai/quota")
      .then((r) => {
        if (active) setCredits(r.total_available_credits);
      })
      .catch(() => {
        if (active) setCredits(null);
      });
    return () => {
      active = false;
    };
  }, [open]);
  const act = async (fn) => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      if (mounted.current)
        setError(
          e.message || "This operation could not be confirmed. Please retry.",
        );
    } finally {
      pending.current = false;
      if (mounted.current) {
        setBusy(false);
        api
          .get("/ai/quota")
          .then((r) => {
            if (mounted.current) setCredits(r.total_available_credits);
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
    if (
      questions.length &&
      !window.confirm("Replace the unimported previews with a new generation?")
    )
      return;
    const body = {
      generation_prompt: prompt.trim(),
      question_count: count,
      difficulty,
      visual_mode: visuals,
    };
    const fingerprint = JSON.stringify(body);
    if (request.current?.fingerprint !== fingerprint)
      request.current = { fingerprint, key: crypto.randomUUID() };
    setSent(prompt.trim());
    act(async () => {
      const result = await service.generate(
        assignmentId,
        body,
        request.current.key,
      );
      if (mounted.current) {
        setQuestions(result.questions);
        request.current = null;
      }
    });
  };
  return (
    <aside className="tma-ai-composer" aria-label="AI question assistant">
      <header className="tma-ai-heading">
        <span className="tma-ai-icon">
          <Sparkles size={18} />
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
        {!sent && !questions.length && (
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
        {error && (
          <p
            role="alert"
            className="rounded-xl border border-error/30 bg-error-soft p-3 text-sm text-error"
          >
            {error}
          </p>
        )}
        {questions.length > 0 && (
          <>
            <p className="text-xs font-semibold text-text-muted">
              {questions.length} previews ready · review each answer before
              importing
            </p>
            <label className="grid gap-2 text-xs text-text-muted">
              Refinement instruction
              <input
                className="tma-ai-input"
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="For example: make it more practical"
              />
            </label>
          </>
        )}
        {questions.map((q, i) => (
          <article className="tma-ai-preview" key={i}>
            <div className="tma-eyebrow">Preview {i + 1}</div>
            <MathText>{q.prompt}</MathText>
            <Illustration image={q.image} />
            <div className="space-y-2">
              {q.options.map((o, j) => (
                <div
                  key={j}
                  className={`tma-ai-option ${o.is_correct ? "is-correct" : ""}`}
                >
                  <span>
                    {String.fromCharCode(65 + j)}
                    {o.is_correct && <Check size={12} />}
                  </span>
                  <div className="min-w-0">
                    <MathText>{o.text}</MathText>
                    <Illustration image={o.image} />
                  </div>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    await service.importQuestion(assignmentId, q);
                    if (mounted.current)
                      setQuestions((list) =>
                        list.filter((_, index) => index !== i),
                      );
                    await onImported();
                  })
                }
              >
                <Check size={14} />
                Import
              </Button>
              <Button
                variant="outline"
                disabled={busy || !instruction.trim()}
                onClick={() =>
                  act(async () => {
                    const body = {
                      generation_prompt: sent,
                      existing_question: q,
                      instruction: instruction.trim(),
                      difficulty,
                      visual_mode: visuals,
                    };
                    const fingerprint = JSON.stringify(body);
                    if (regeneration.current?.fingerprint !== fingerprint)
                      regeneration.current = {
                        fingerprint,
                        key: crypto.randomUUID(),
                      };
                    const result = await service.regenerate(
                      assignmentId,
                      body,
                      regeneration.current.key,
                    );
                    if (mounted.current) {
                      setQuestions((list) =>
                        list.map((old, index) =>
                          index === i ? result.question : old,
                        ),
                      );
                      regeneration.current = null;
                    }
                  })
                }
              >
                <RotateCw size={14} />
                Refine
              </Button>
            </div>
          </article>
        ))}
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
            <details className="tma-ai-options">
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
                <fieldset className="tma-ai-choices">
                  <legend>Difficulty</legend>
                  {["easy", "medium", "difficult"].map((v) => (
                    <label key={v}>
                      <input
                        type="radio"
                        name="tma-difficulty"
                        value={v}
                        checked={difficulty === v}
                        disabled={busy}
                        onChange={() => setDifficulty(v)}
                      />
                      <span>{v}</span>
                    </label>
                  ))}
                </fieldset>
                <fieldset className="tma-ai-choices">
                  <legend>Visuals</legend>
                  {[
                    ["text_only", "Text only"],
                    ["auto", "Automatic"],
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
