import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Button from "../../components/ui/Button";
import { useToast } from "../../hooks/useToast";
import { authSession, getErrorMessage } from "../../services/api";
import { tmaService as service } from "../../services/tmaService";
import {
  aiDraftScope,
  createAIDraftController,
  createAIDraftStore,
  validateAIQuestion,
} from "./aiDrafts";
import { TextField } from "./TmaQuestionEditor";
import MathText from "./MathText.jsx";
import "./tma-authoring.css";

export function DraftIllustration({ image }) {
  if (
    !image?.data_base64 ||
    !["image/png", "image/jpeg", "image/webp"].includes(image.content_type)
  )
    return null;
  return (
    <img
      className="max-h-96 max-w-full rounded-xl object-contain"
      src={`data:${image.content_type};base64,${image.data_base64}`}
      alt={image.alt_text || "Question illustration"}
    />
  );
}

export default function TmaAIReviewPage({ role }) {
  const { assignmentId, draftId } = useParams();
  return (
    <Review
      key={`${assignmentId}/${draftId}`}
      role={role}
      assignmentId={assignmentId}
      draftId={draftId}
    />
  );
}

function Review({ role, assignmentId, draftId }) {
  const { showError, showSuccess } = useToast();
  const navigate = useNavigate();
  const scope = aiDraftScope(authSession.getUser(), role, assignmentId);
  const store = useMemo(
    () => (scope ? createAIDraftStore(scope) : null),
    [scope],
  );
  const controller = useMemo(
    () =>
      store ? createAIDraftController({ store, service, assignmentId }) : null,
    [store, assignmentId],
  );
  const [draft, setDraft] = useState(null);
  const [assignment, setAssignment] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [index, setIndex] = useState(0);
  const [editing, setEditing] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [reload, setReload] = useState(0);
  const pending = useRef(false);
  const heading = useRef(null);
  const base = `/${role}/tma/${assignmentId}`;
  useEffect(() => {
    let active = true;
    if (!store) {
      showError("Sign in to this school to open AI drafts.");
      setLoading(false);
      return;
    }
    Promise.all([store.get(draftId), service.get(assignmentId)])
      .then(([saved, a]) => {
        if (!active) return;
        setDraft(saved || null);
        setAssignment(a);
        if (!saved) showError("This draft is not available on this browser and school account.");
      })
      .catch((e) => {
        if (active) showError(getErrorMessage(e));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [store, assignmentId, draftId, reload, showError]);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  const run = async (fn) => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);

    try {
      await fn();
    } catch (e) {
      showError(
        getErrorMessage(e, "Could not confirm this operation. Your browser draft is preserved."),
      );
      const latest = await store?.get(draftId).catch(() => null);
      if (latest) setDraft(latest);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };
  const currentIndex = Math.min(
    index,
    Math.max(0, (draft?.questions.length || 1) - 1),
  );
  const question = draft?.questions[currentIndex];
  const available =
    assignment?.status === "draft" &&
    assignment.current_revision_number === draft?.revision_number;
  const locked =
    busy ||
    !available ||
    draft?.status !== "review" ||
    Boolean(draft?.pending_regeneration);
  const update = async (questions) => {
    setDraft(await controller.update(draftId, questions));
    setEditing(false);
    showSuccess("Browser draft updated.");
  };
  return (
    <main className="tma-question-preview-page text-text">
      <Link
        to={base}
        className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-surface px-4 py-2 text-sm font-medium text-primary shadow-sm hover:bg-surface-muted"
        onClick={(e) => {
          if (
            editing &&
            !window.confirm("Leave without saving your current edits?")
          )
            e.preventDefault();
        }}
      >
        <ArrowLeft size={16} /> Back to questions
      </Link>
      <header className="my-5 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 ref={heading} tabIndex={-1} className="text-2xl font-semibold">
            Review AI questions
          </h1>
          <p className="mt-1 text-sm text-text-muted">
            Edit and arrange this browser draft before adding it to your
            assignment.
          </p>
        </div>
        {draft && (
          <Button
            disabled={
              busy ||
              editing ||
              !available ||
              !draft.questions.length ||
              Boolean(draft.pending_regeneration) ||
              !["review", "saving"].includes(draft.status)
            }
            onClick={() =>
              run(async () => {
                await controller.save(draftId);
                showSuccess("Questions added to the assignment.");
                navigate(base);
              })
            }
          >
            {busy
              ? "Working…"
              : draft.status === "saving"
                ? "Retry Add all"
                : `Add all ${draft.questions.length} questions`}
          </Button>
        )}
      </header>
      {loading ? (
        <p role="status">Loading browser draft…</p>
      ) : !draft ? (
        <Button
          variant="outline"
          onClick={() => {
            setLoading(true);
            setReload((v) => v + 1);
          }}
        >
          Try again
        </Button>
      ) : (
        <>
          {!available && (
            <p
              role="alert"
              className="mb-4 rounded-xl border border-border bg-surface p-4 text-sm"
            >
              This assignment is no longer an editable draft of the same
              revision. Your local questions are preserved.
            </p>
          )}
          {(draft.status === "generating" || draft.pending_regeneration) && (
            <div className="mb-4 rounded-xl border border-border bg-surface p-5">
              <p className="mb-3 text-sm">
                Recover the pending AI response before continuing.
              </p>
              <Button
                disabled={busy || !available}
                onClick={() =>
                  run(async () => {
                    setDraft(await controller.recover(draftId));
                  })
                }
              >
                Recover questions
              </Button>
            </div>
          )}
          {draft.status === "saving" && (
            <p
              role="status"
              className="mb-4 rounded-xl border border-border bg-surface p-4 text-sm"
            >
              The last save is awaiting confirmation. Retry Add all to confirm
              the same batch safely.
            </p>
          )}
          {draft.questions.length > 0 && (
            <nav
              className="tma-ai-review-navigation"
              aria-label="AI draft questions"
            >
              <Button
                variant="outline"
                disabled={busy || editing || currentIndex === 0}
                onClick={() => setIndex(currentIndex - 1)}
              >
                <ChevronLeft size={16} /> Previous
              </Button>
              <span className="text-sm font-medium">
                Question {currentIndex + 1} of {draft.questions.length}
              </span>
              <Button
                variant="outline"
                disabled={
                  busy || editing || currentIndex + 1 >= draft.questions.length
                }
                onClick={() => setIndex(currentIndex + 1)}
              >
                Next <ChevronRight size={16} />
              </Button>
            </nav>
          )}
          {question &&
            (editing ? (
              <DraftEditor
                key={currentIndex}
                question={question}
                disabled={busy}
                onCancel={() => setEditing(false)}
                onSave={(updated) =>
                  run(() =>
                    update(
                      draft.questions.map((q, i) =>
                        i === currentIndex ? updated : q,
                      ),
                    ),
                  )
                }
              />
            ) : (
              <article className="tma-question-record">
                <header className="flex-wrap">
                  <h2 className="font-semibold">Question {currentIndex + 1}</h2>
                  <div className="ml-auto flex flex-wrap items-center gap-2">
                    <Button
                      variant="outline"
                      disabled={locked}
                      onClick={() => setEditing(true)}
                    >
                      <Pencil size={15} /> Edit
                    </Button>
                    <Button
                      variant="ghost"
                      disabled={locked}
                      onClick={() => {
                        if (
                          window.confirm(
                            "Remove this question from the browser draft?",
                          )
                        )
                          run(() =>
                            update(
                              draft.questions.filter(
                                (_, i) => i !== currentIndex,
                              ),
                            ),
                          );
                      }}
                    >
                      <Trash2 size={15} /> Remove
                    </Button>
                  </div>
                </header>
                <div className="tma-question-prompt">
                  {question.instruction && (
                    <MathText>{question.instruction}</MathText>
                  )}
                  <MathText>{question.prompt}</MathText>
                  <DraftIllustration image={question.image} />
                </div>
                <div className="tma-preview-options">
                  {question.options.map((o, i) => (
                    <div
                      key={i}
                      className={`tma-preview-option ${o.is_correct ? "border-primary bg-primary/5" : ""}`}
                    >
                      <span className="tma-option-letter">
                        {String.fromCharCode(65 + i)}
                      </span>
                      <div className="min-w-0 flex-1">
                        <MathText>{o.text}</MathText>
                        <DraftIllustration image={o.image} />
                      </div>
                      {o.is_correct && (
                        <span className="text-xs font-semibold text-primary">
                          Correct
                        </span>
                      )}
                    </div>
                  ))}
                </div>
                <div className="tma-ai-review-tools">
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      disabled={locked || currentIndex === 0}
                      onClick={() =>
                        run(async () => {
                          const next = [...draft.questions];
                          [next[currentIndex - 1], next[currentIndex]] = [
                            next[currentIndex],
                            next[currentIndex - 1],
                          ];
                          await update(next);
                          setIndex(currentIndex - 1);
                        })
                      }
                    >
                      Move earlier
                    </Button>
                    <Button
                      variant="outline"
                      disabled={
                        locked || currentIndex + 1 >= draft.questions.length
                      }
                      onClick={() =>
                        run(async () => {
                          const next = [...draft.questions];
                          [next[currentIndex + 1], next[currentIndex]] = [
                            next[currentIndex],
                            next[currentIndex + 1],
                          ];
                          await update(next);
                          setIndex(currentIndex + 1);
                        })
                      }
                    >
                      Move later
                    </Button>
                  </div>
                  <label className="grid gap-2 text-sm">
                    Refinement instruction
                    <textarea
                      className="input-base"
                      rows={2}
                      maxLength={10000}
                      disabled={locked}
                      value={instruction}
                      onChange={(e) => setInstruction(e.target.value)}
                      placeholder="Describe what should change…"
                    />
                  </label>
                  <Button
                    variant="outline"
                    disabled={locked || !instruction.trim()}
                    onClick={() =>
                      run(async () => {
                        setDraft(
                          await controller.regenerate(
                            draftId,
                            currentIndex,
                            instruction.trim(),
                          ),
                        );
                        setInstruction("");
                      })
                    }
                  >
                    Refine with AI
                  </Button>
                </div>
              </article>
            ))}
          {!draft.questions.length && draft.status === "review" && (
            <p className="rounded-xl border border-border bg-surface p-6 text-sm">
              No questions remain. Return to the assignment to generate another
              set.
            </p>
          )}
          <footer className="mt-5 flex flex-wrap items-center justify-between gap-3 text-sm text-text-muted">
            <p>Saved on this browser until you choose Add all.</p>
            <Button
              variant="ghost"
              disabled={busy || draft.status === "saving"}
              onClick={() => {
                if (
                  window.confirm(
                    "Discard this browser draft? Used AI credits are not refunded.",
                  )
                )
                  run(async () => {
                    await store.delete(draftId);
                    navigate(base);
                  });
              }}
            >
              Discard draft
            </Button>
          </footer>
        </>
      )}
    </main>
  );
}

function DraftEditor({ question, disabled, onSave, onCancel }) {
  const { showError } = useToast();
  const [value, setValue] = useState(() => structuredClone(question));
  const option = (index, patch) =>
    setValue((q) => ({
      ...q,
      options: q.options.map((o, i) => (i === index ? { ...o, ...patch } : o)),
    }));
  return (
    <form
      className="tma-ai-draft-editor"
      onSubmit={(e) => {
        e.preventDefault();
        const invalid = validateAIQuestion(value);
        if (invalid) showError(invalid);
        else onSave(value);
      }}
    >
      <fieldset disabled={disabled} className="space-y-5">
        <h2 className="font-semibold">Edit browser draft</h2>
        <label className="grid gap-2 text-sm">
          Instruction (optional)
          <textarea
            className="input-base"
            value={value.instruction || ""}
            onChange={(e) =>
              setValue({ ...value, instruction: e.target.value || null })
            }
          />
        </label>
        <TextField
          label="Question text"
          value={value.prompt}
          onChange={(prompt) => setValue({ ...value, prompt })}
        />
        {value.image && (
          <div className="space-y-2">
            <DraftIllustration image={value.image} />
            <Button
              variant="outline"
              onClick={() => setValue({ ...value, image: null })}
            >
              Remove question image
            </Button>
          </div>
        )}
        <p className="text-sm text-text-muted">
          Mark one correct answer. Keep at least four options.
        </p>
        {value.options.map((o, i) => (
          <div
            key={i}
            className="rounded-xl border border-border p-4 space-y-3"
          >
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <input
                type="radio"
                name="draft-correct"
                checked={o.is_correct}
                onChange={() =>
                  setValue({
                    ...value,
                    options: value.options.map((item, j) => ({
                      ...item,
                      is_correct: i === j,
                    })),
                  })
                }
              />
              Option {String.fromCharCode(65 + i)} · Correct answer
            </label>
            <TextField
              compact
              rows={2}
              label={`Option ${i + 1}`}
              value={o.text}
              onChange={(text) => option(i, { text })}
            />
            {o.image && (
              <>
                <DraftIllustration image={o.image} />
                <Button
                  variant="outline"
                  onClick={() => option(i, { image: null })}
                >
                  Remove option image
                </Button>
              </>
            )}
            <Button
              variant="ghost"
              disabled={value.options.length <= 4}
              onClick={() =>
                setValue({
                  ...value,
                  options: value.options.filter((_, j) => i !== j),
                })
              }
            >
              Remove option
            </Button>
          </div>
        ))}
        <Button
          variant="outline"
          disabled={value.options.length >= 50}
          onClick={() =>
            setValue({
              ...value,
              options: [
                ...value.options,
                { text: "", is_correct: false, image: null },
              ],
            })
          }
        >
          <Plus size={16} /> Add option
        </Button>
        <div className="flex gap-3">
          <Button type="submit">Save draft changes</Button>
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </fieldset>
    </form>
  );
}
