import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Cloud,
  LoaderCircle,
  Pause,
  BookOpen,
  ListChecks,
  X,
  ArrowUpRight,
} from "lucide-react";
import Button from "../../../components/ui/Button";
import Card from "../../../components/ui/Card";
import Modal from "../../../components/ui/Modal";
import { studentTmaService as service } from "../../../services/studentTmaService";
import MathText from "../MathText.jsx";
import QuestionPicker, { QuestionPickerActions } from "./QuestionPicker";

function StudentImage({ attemptId, assetId, alt }) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    service
      .image(attemptId, assetId)
      .then((data) => {
        if (active) {
          setUrl(data.signed_url);
          setError("");
        }
      })
      .catch(() => {
        if (active) setError("This image could not be loaded.");
      });
    return () => {
      active = false;
    };
  }, [attemptId, assetId, revision]);
  if (error)
    return (
      <span className="block py-3 text-sm text-error">
        {error}{" "}
        <button
          type="button"
          className="min-h-11 px-2 underline"
          onClick={(e) => {
            e.preventDefault();
            setUrl("");
            setError("");
            setRevision((r) => r + 1);
          }}
        >
          Retry image
        </button>
      </span>
    );
  return url ? (
    <img
      className="student-tma-image"
      src={url}
      alt={alt}
      onError={() => setError("This image has expired or could not be loaded.")}
    />
  ) : (
    <span role="status" className="block py-3 text-xs text-text-muted">
      Loading image…
    </span>
  );
}

export default function StudentTmaView({
  back,
  error,
  delivery,
  result,
  saveState,
  loading,
  subject,
  assignment,
  component,
  questions,
  current,
  answered,
  answers,
  position,
  busy,
  confirmation,
  submissionStarted,
  questionHeading,
  leave,
  start,
  submit,
  choose,
  go,
  setConfirmation,
  setReload,
  onRetrySave,
}) {
  const entry = useRef(null);
  const missedZero = Boolean(result?.auto_zeroed_at && !result?.auto_zero_resolved_at);
  const [guideOpen, setGuideOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(true);
  const [mobilePickerOpen, setMobilePickerOpen] = useState(false);
  const pickerToggle = useRef(null);
  const requestSubmission = () => {
    setMobilePickerOpen(false);
    setConfirmation(true);
  };
  const pickerProps = {
    questions,
    position,
    answers,
    pending: saveState.pending,
    disabled: busy || submissionStarted,
    onPick: go,
  };
  const pickerActions = {
    position,
    total: questions.length,
    busy,
    onLeave: leave,
    onSubmit: requestSubmission,
  };
  const dismissConfirmation = () => {
    if (busy) return;
    setConfirmation(false);
    window.requestAnimationFrame(() =>
      questionHeading.current?.focus({ preventScroll: true }),
    );
  };
  useLayoutEffect(() => {
    const element = entry.current;
    if (!element) return;
    const viewport = document.getElementById("dashboard-scroll-viewport");
    const resize = () => {
      const bottom =
        viewport?.getBoundingClientRect().bottom ?? window.innerHeight;
      const height = Math.max(
        380,
        Math.floor(bottom - element.getBoundingClientRect().top - 20),
      );
      element.style.setProperty("--tma-entry-height", height + "px");
    };
    resize();
    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
    if (viewport) observer?.observe(viewport);
    window.addEventListener("resize", resize);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", resize);
    };
  }, [loading, delivery, result, assignment]);
  return (
    <div
      className={`student-tma ${delivery && !result ? "student-tma--attempt" : ""}`}
    >
      {(!delivery ||
        result ||
        saveState.error ||
        saveState.pending.length > 0) && (
        <div
          className={`student-tma-topline ${delivery && !result ? "student-tma-topline--quiz" : ""}`}
        >
          {(!delivery || result) && (
            <button
              type="button"
              disabled={busy}
              onClick={leave}
              className="student-tma-back"
            >
              <ArrowLeft size={16} />
              Back to subject
            </button>
          )}
          {delivery && !result && (
            <span className="student-tma-save" role="status" aria-live="polite">
              {saveState.error ? (
                "Some answers are not saved"
              ) : (
                <>
                  <LoaderCircle className="animate-spin" size={15} /> Saving
                  answers…
                </>
              )}
            </span>
          )}
        </div>
      )}
      {error && (
        <div role="alert" className="student-tma-alert">
          {error}
          {!delivery && (
            <button
              type="button"
              className="min-h-11 px-3 font-semibold underline"
              onClick={() => setReload((r) => r + 1)}
            >
              Try again
            </button>
          )}
        </div>
      )}
      {loading ? (
        <p role="status" className="py-12 text-center text-text-muted">
          Loading your assignment…
        </p>
      ) : result ? (
        <Card className="student-tma-result">
          <span className="student-tma-success-icon">
            <CheckCircle2 size={32} />
          </span>
          <p className="student-tma-eyebrow">
            {missedZero ? "Missed deadline" : "Assignment submitted"}
          </p>
          <h2>{missedZero ? "Submission deadline passed" : "Your work is complete"}</h2>
          <p>
            {missedZero
              ? "This assignment was not submitted by the deadline, so a zero was recorded."
              : "Your answers have been graded and your score has been recorded."}
          </p>
          <div className="student-tma-score">
            <strong>{result.component_score}</strong>
            {assignment && (
              <span>/ {assignment.component_maximum_score} marks</span>
            )}
          </div>
          {!missedZero && (
            <p>
              {result.correct_answers} of {result.total_questions} answers correct
            </p>
          )}
          <p className="text-xs text-text-muted">
            {missedZero ? "Zero recorded" : "Submitted"}{" "}
            {new Date(result.submitted_at).toLocaleString()}
          </p>
          <Link className="student-tma-link" to={back + "?tab=assessment"}>
            View subject assessments <ArrowRight size={16} />
          </Link>
        </Card>
      ) : delivery ? (
        <div
          className={`student-tma-workspace ${pickerOpen ? "" : "student-tma-workspace--picker-closed"}`}
        >
          <header className="student-tma-quiz-heading">
            <div>
              <h2>{subject?.subject_name || "Your assignment"}</h2>
              <p>
                {component?.name || "Tutor Marked Assignment"}{" "}
                <span aria-hidden="true">·</span> {questions.length} questions{" "}
                <span aria-hidden="true">·</span> Single choice
              </p>
            </div>
            <button
              ref={pickerToggle}
              type="button"
              className="student-tma-picker-toggle"
              aria-expanded={pickerOpen}
              aria-controls="student-tma-desktop-picker"
              onClick={() => setPickerOpen((open) => !open)}
            >
              <ListChecks size={18} />
              <span>{pickerOpen ? "Collapse picker" : "Question picker"}</span>
            </button>
            <div className="student-tma-header-progress">
              <span>
                {answered} / {questions.length} answered
              </span>
              <progress
                max={questions.length || 1}
                value={answered}
                aria-label="Answered questions"
              />
            </div>
          </header>
          <div className="student-tma-main">
            {saveState.error && (
              <div role="alert" className="student-tma-alert">
                Your latest choices are still on this screen but have not been
                saved. Keep this page open and retry.
                <Button variant="outline" disabled={busy} onClick={onRetrySave}>
                  Retry saving
                </Button>
              </div>
            )}
            {submissionStarted && !result && (
              <p role="status" className="student-tma-alert">
                Submission is awaiting confirmation. Use Submit again to check
                the result. Answers are locked while submission is being
                confirmed.
              </p>
            )}
            {current ? (
              <>
                <section
                  className="student-tma-question"
                  aria-labelledby="student-tma-question-heading"
                >
                  <div
                    className="student-tma-question-meta"
                    ref={questionHeading}
                    tabIndex={-1}
                  >
                    <h3 id="student-tma-question-heading">
                      Question {position + 1} of {questions.length}
                    </h3>
                  </div>
                  <div className="student-tma-prompt">
                    <MathText>{current.question_text}</MathText>
                    {current.image_asset_id && (
                      <StudentImage
                        key={current.image_asset_id}
                        attemptId={delivery.attempt.id}
                        assetId={current.image_asset_id}
                        alt={`Question ${position + 1} illustration`}
                      />
                    )}
                  </div>
                  <fieldset
                    className="student-tma-options"
                    disabled={busy || confirmation || submissionStarted}
                  >
                    <legend className="sr-only">
                      Answer for question {position + 1}
                    </legend>
                    {current.options.map((option, index) => (
                      <div
                        key={option.id}
                        className={`student-tma-option ${answers[current.id] === option.id ? "is-selected" : ""}`}
                      >
                        <label className="student-tma-option-control">
                          <input
                            type="radio"
                            name={current.id}
                            checked={answers[current.id] === option.id}
                            onChange={() => choose(current.id, option.id)}
                            aria-label={`Option ${String.fromCharCode(65 + index)}`}
                            aria-describedby={`tma-option-${option.id}`}
                          />

                          <span
                            className="student-tma-option-content"
                            id={`tma-option-${option.id}`}
                          >
                            <MathText>{option.option_text}</MathText>
                          </span>
                        </label>
                        {option.image_asset_id && (
                          <div className="student-tma-option-image">
                            <StudentImage
                              key={option.image_asset_id}
                              attemptId={delivery.attempt.id}
                              assetId={option.image_asset_id}
                              alt={`Option ${String.fromCharCode(65 + index)} illustration`}
                            />
                          </div>
                        )}
                      </div>
                    ))}
                  </fieldset>
                  <button
                    type="button"
                    className="student-tma-clear"
                    disabled={
                      !answers[current.id] ||
                      busy ||
                      confirmation ||
                      submissionStarted
                    }
                    onClick={() => choose(current.id, null)}
                  >
                    Clear selection
                  </button>
                </section>
                <div className="student-tma-question-nav">
                  <Button
                    variant="outline"
                    disabled={position === 0 || busy || submissionStarted}
                    onClick={() => go(position - 1)}
                  >
                    <ArrowLeft size={16} />
                    Previous
                  </Button>
                  <span>
                    {position + 1} / {questions.length}
                  </span>
                  <Button
                    variant="primary"
                    disabled={
                      busy ||
                      (submissionStarted && position !== questions.length - 1)
                    }
                    onClick={
                      position === questions.length - 1
                        ? requestSubmission
                        : () => go(position + 1)
                    }
                  >
                    {position === questions.length - 1
                      ? "Review & submit"
                      : "Next"}
                    <ArrowRight size={16} />
                  </Button>
                </div>
              </>
            ) : (
              <Card className="p-6">
                No questions were returned.{" "}
                <button
                  type="button"
                  onClick={() => setReload((r) => r + 1)}
                  className="underline"
                >
                  Reload assignment
                </button>
              </Card>
            )}
          </div>
          <aside
            id="student-tma-desktop-picker"
            className="student-tma-map"
            hidden={!pickerOpen}
          >
            <header>
              <h2>
                <ListChecks size={20} aria-hidden="true" />
                Your questions
              </h2>
              <button
                type="button"
                aria-label="Collapse question picker"
                onClick={() => {
                  setPickerOpen(false);
                  pickerToggle.current?.focus();
                }}
              >
                <X size={18} />
              </button>
            </header>
            <QuestionPicker {...pickerProps} />
            <QuestionPickerActions {...pickerActions} />
          </aside>
          {typeof document !== "undefined" &&
            !confirmation &&
            createPortal(
              <button
                type="button"
                className="student-tma-picker-fab"
                aria-label="Open question picker"
                aria-haspopup="dialog"
                aria-expanded={mobilePickerOpen}
                onClick={() => setMobilePickerOpen(true)}
              >
                <ListChecks size={20} />
                <span>Questions</span>
                <strong>
                  {position + 1}/{questions.length}
                </strong>
              </button>,
              document.querySelector?.('[data-tenant-branding-scope="true"]') ||
                document.body,
            )}
          <Modal
            open={mobilePickerOpen}
            title="Your questions"
            placement="responsive"
            className="max-w-lg student-tma-mobile-picker"
            onClose={() => setMobilePickerOpen(false)}
            footer={<QuestionPickerActions {...pickerActions} />}
          >
            <QuestionPicker
              {...pickerProps}
              onPick={(index) => {
                go(index);
                setMobilePickerOpen(false);
                window.requestAnimationFrame(() =>
                  questionHeading.current?.focus({ preventScroll: true }),
                );
              }}
            />
          </Modal>
        </div>
      ) : assignment && !error ? (
        <section className="student-tma-welcome" ref={entry}>
          <div className="student-tma-intro">
            <p className="student-tma-eyebrow">
              {component?.name || "Tutor Marked Assignment"}
            </p>
            <h2>{subject?.subject_name}</h2>
            <p>
              {assignment.status === "closed"
                ? "This assignment is closed. You can no longer start or submit it."
                : "Take your time. You can pause and come back before the deadline."}
            </p>
          </div>
          <Button
            className="student-tma-start"
            disabled={busy || !assignment.can_start_or_resume || assignment.status === "closed"}
            onClick={start}
          >
            {busy && <LoaderCircle className="animate-spin" size={18} />}
            {busy
              ? "Opening your TMA…"
              : assignment.status === "closed"
                ? "Closed"
                : assignment.attempt_status === "in_progress"
                  ? "Continue TMA"
                  : "Start TMA"}
            {!busy && <ArrowRight size={18} />}
          </Button>
          <div className="student-tma-entry-notes">
            <p>
              {assignment.component_maximum_score} marks{" "}
              <span aria-hidden="true">·</span> One attempt{" "}
              <span aria-hidden="true">·</span> No timer
            </p>
            <button
              type="button"
              className="student-tma-guide-trigger"
              aria-haspopup="dialog"
              aria-expanded={guideOpen}
              onClick={() => setGuideOpen(true)}
            >
              <BookOpen size={17} />
              <span>Before you start</span>
              <ArrowUpRight size={15} />
            </button>
          </div>
        </section>
      ) : null}
      <Modal
        open={guideOpen}
        title="Before you start"
        description="A few things to keep in mind."
        onClose={() => setGuideOpen(false)}
        className="max-w-2xl"
        placement="bottom"
        footer={
          <div className="flex justify-center">
            <Button
              className="w-full sm:w-auto sm:min-w-40"
              onClick={() => setGuideOpen(false)}
            >
              Got it
            </Button>
          </div>
        }
      >
        <div className="student-tma-guide">
          <div>
            <span>
              <Cloud size={21} />
            </span>
            <div>
              <h3>Your progress is saved</h3>
              <p>
                Choose an answer and it saves automatically. Wait until “Saving
                answers…” disappears before leaving. If your connection drops,
                keep the page open and retry.
              </p>
            </div>
          </div>
          <div>
            <span>
              <Pause size={21} />
            </span>
            <div>
              <h3>Take a break anytime</h3>
              <p>
                You can return to your saved attempt before the deadline, while
                the assignment and academic term are still open.
              </p>
            </div>
          </div>
          <div>
            <span>
              <CheckCircle2 size={21} />
            </span>
            <div>
              <h3>One attempt. Submit when ready.</h3>
              <p>
                Review your answers before submitting. You will see your score
                immediately, and your answers cannot be changed afterwards.
              </p>
            </div>
          </div>
          {assignment?.closes_at && (
            <p className="student-tma-guide-estimate">
              Submission deadline:{" "}
              {new Date(assignment.closes_at).toLocaleString()}. The assignment
              closes automatically at this time.
            </p>
          )}
        </div>
      </Modal>
      <Modal
        open={confirmation}
        title="Submit your assignment?"
        onClose={dismissConfirmation}
        closeOnOverlay={!busy}
        showClose={!busy}
      >
        <div className="space-y-5 text-sm leading-6 text-text">
          <p>
            You have answered{" "}
            <strong>
              {answered} of {questions.length}
            </strong>{" "}
            questions.
          </p>
          {answered < questions.length && (
            <p className="text-sm text-text-muted">
              {questions.length - answered} questions are unanswered and will
              receive no marks.
            </p>
          )}
          <p>You cannot change your answers after submitting.</p>
          {error && (
            <p role="alert" className="text-error">
              {error}
            </p>
          )}
          <div className="flex flex-wrap justify-end gap-3">
            <Button
              variant="outline"
              disabled={busy}
              onClick={dismissConfirmation}
            >
              Keep working
            </Button>
            <Button disabled={busy} onClick={submit}>
              {busy ? "Saving & submitting…" : "Confirm submission"}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
