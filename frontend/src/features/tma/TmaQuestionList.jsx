import { ArrowUpRight, BookOpen, Image, Pencil, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import Button from "../../components/ui/Button";

export default function TmaQuestionList({
  questions,
  assignmentPath,
  busy,
  editable,
  canEdit,
  onEdit,
  onDelete,
}) {
  if (!questions.length)
    return (
      <section className="tma-question-empty">
        <span>
          <BookOpen size={27} />
        </span>
        <h2>Your assignment starts here</h2>
        <p>
          Use Add question to write your first question and its answer options.
          You can also open the AI assistant from Actions.
        </p>
        <div className="tma-empty-steps">
          <span>01 · Create questions</span>
          <span>02 · Review answers</span>
          <span>03 · Publish</span>
        </div>
      </section>
    );
  return (
    <section className="tma-question-list" aria-label="Assignment questions">
      <div className="tma-question-list-heading" aria-hidden="true">
        <span>Question</span>
        <span>Type / options</span>
        <span>Actions</span>
      </div>
      {questions.map((q, i) => (
        <article key={q.id} className="tma-question-row">
          <Link
            className="tma-question-row-link"
            to={`${assignmentPath}/questions/${q.id}`}
            aria-label={`Preview question ${i + 1}`}
          >
            <span className="tma-question-number">
              {String(i + 1).padStart(2, "0")}
            </span>
            <div className="min-w-0">
              <h3 className="tma-question-excerpt">
                {q.question_text || "Image question"}
              </h3>
              {(q.image_asset_id ||
                q.options.some((o) => o.image_asset_id)) && (
                <span className="tma-question-media-label">
                  <Image size={14} aria-hidden="true" /> Includes media
                </span>
              )}
            </div>
            <ArrowUpRight
              size={16}
              className="tma-question-preview-arrow"
              aria-hidden="true"
            />
          </Link>
          <div className="tma-question-row-meta">
            <span>Single choice</span>
            <span>{q.options.length} options</span>
          </div>
          <div className="tma-question-row-actions">
            {editable && canEdit(q) ? (
              <>
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={() => onEdit(q)}
                  aria-label={`Edit question ${i + 1}`}
                >
                  <Pencil size={15} /> Edit
                </Button>
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() => onDelete(q)}
                  aria-label={`Delete question ${i + 1}`}
                >
                  <Trash2 size={15} className="text-error" /> Delete
                </Button>
              </>
            ) : (
              <span className="text-xs text-text-muted">Read only</span>
            )}
          </div>
        </article>
      ))}
    </section>
  );
}
