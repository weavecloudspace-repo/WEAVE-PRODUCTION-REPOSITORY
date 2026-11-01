import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ChevronLeft, ChevronRight } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import Button from "../../components/ui/Button";
import MathText from "./MathText.jsx";
import { TmaAssetImage } from "./TmaQuestionEditor";
import { tmaService } from "../../services/tmaService";
import "./tma-authoring.css";

export default function TmaQuestionPreviewPage({ role }) {
  const { assignmentId, questionId } = useParams();
  return (
    <QuestionPreview
      key={`${assignmentId}/${questionId}`}
      role={role}
      assignmentId={assignmentId}
      questionId={questionId}
    />
  );
}

function QuestionPreview({ role, assignmentId, questionId }) {
  const [questions, setQuestions] = useState(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const heading = useRef(null);
  const base = `/${role}/tma/${assignmentId}`;
  useEffect(() => {
    let active = true;
    tmaService
      .questions(assignmentId)
      .then((items) => {
        if (active) setQuestions(items);
      })
      .catch((e) => {
        if (active) setError(e.message || "Could not load this question.");
      });
    return () => {
      active = false;
    };
  }, [assignmentId, retry]);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  const index = questions?.findIndex((q) => q.id === questionId) ?? -1;
  const question = questions?.[index];
  return (
    <main className="tma-question-preview-page text-text">
      <Link
        to={base}
        className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-surface px-4 py-2 text-sm font-medium text-primary shadow-sm hover:bg-surface-muted"
      >
        <ArrowLeft size={16} /> Back to questions
      </Link>
      <header className="mb-5 mt-3">
        <h1 ref={heading} tabIndex={-1} className="text-2xl font-semibold">
          Question preview
        </h1>
        <p className="mt-1 text-sm text-text-muted">
          Review the saved question and its answer options.
        </p>
      </header>
      {error ? (
        <div role="alert" className="rounded-xl border border-error/30 p-5">
          <p>{error}</p>
          <Button
            variant="outline"
            onClick={() => {
              setError("");
              setRetry((v) => v + 1);
            }}
          >
            Try again
          </Button>
        </div>
      ) : !questions ? (
        <p role="status">Loading question preview…</p>
      ) : !question ? (
        <p role="status">
          This question is no longer available in the current revision.
        </p>
      ) : (
        <>
          <article className="tma-question-record">
            <header>
              <span className="tma-question-number">
                {String(index + 1).padStart(2, "0")}
              </span>
              <div>
                <h2 className="font-semibold">
                  Question {index + 1} of {questions.length}
                </h2>
                <p>Single choice · {question.options.length} options</p>
              </div>
            </header>
            <div className="tma-question-prompt">
              <MathText>{question.question_text}</MathText>
              {question.image_asset_id && (
                <TmaAssetImage
                  autoLoad
                  assignmentId={assignmentId}
                  assetId={question.image_asset_id}
                  alt="Question illustration"
                />
              )}
            </div>
            <div className="tma-preview-options" aria-label="Answer options">
              {question.options.map((option, i) => (
                <div className="tma-preview-option" key={option.id}>
                  <span className="tma-option-letter">
                    {String.fromCharCode(65 + i)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <MathText>{option.option_text}</MathText>
                    {option.image_asset_id && (
                      <TmaAssetImage
                        autoLoad
                        assignmentId={assignmentId}
                        assetId={option.image_asset_id}
                        alt={`Option ${i + 1}`}
                      />
                    )}
                  </div>
                </div>
              ))}
            </div>
            <footer className="border-t border-border px-5 py-4 text-sm text-text-muted">
              <strong className="text-text">Answer key: </strong>
              {question.options
                .map((o, i) =>
                  o.is_correct ? String.fromCharCode(65 + i) : null,
                )
                .filter(Boolean)
                .join(", ") || "No correct answer selected"}
            </footer>
          </article>
          <nav
            className="mt-4 flex flex-wrap items-center justify-between gap-3"
            aria-label="Question previews"
          >
            {index > 0 ? (
              <Link
                className="inline-flex min-h-11 items-center gap-2 text-sm text-primary"
                to={`${base}/questions/${questions[index - 1].id}`}
              >
                <ChevronLeft size={16} /> Previous question
              </Link>
            ) : (
              <span />
            )}
            {index + 1 < questions.length && (
              <Link
                className="inline-flex min-h-11 items-center gap-2 text-sm text-primary"
                to={`${base}/questions/${questions[index + 1].id}`}
              >
                Next question <ChevronRight size={16} />
              </Link>
            )}
          </nav>
        </>
      )}
    </main>
  );
}
