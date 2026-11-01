import { useEffect, useState } from "react";
import { ArrowUpRight, BookOpen, CheckCircle2, Eye, EyeOff, Image, Pencil, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import Button from "../../components/ui/Button";
import MathText from "./MathText";
import { TmaAssetImage } from "./TmaQuestionEditor";

/**
 * CBT-style question bank with a dedicated audit surface.
 * The saved answer key is visible only in author view; student preview hides it.
 */
export default function TmaQuestionList({
  questions,
  assignmentPath,
  busy,
  editable,
  canEdit,
  onEdit,
  onDelete,
}) {
  const [selectedId, setSelectedId] = useState(null);
  const [studentView, setStudentView] = useState(false);
  const selectedIndex = Math.max(0, questions.findIndex((q) => q.id === selectedId));
  const question = questions[selectedIndex];
  useEffect(() => {
    if (!questions.some((q) => q.id === selectedId)) setSelectedId(questions[0]?.id ?? null);
  }, [questions, selectedId]);
  if (!questions.length) return (
    <section className="tma-question-empty">
      <span><BookOpen size={27} /></span>
      <h2>Start your assignment question bank</h2>
      <p>Add a question manually or use AI to prepare a reviewed draft. Save at least four options and one correct answer for each question.</p>
      <div className="tma-empty-steps"><span>01 · Author</span><span>02 · Review key</span><span>03 · Publish</span></div>
    </section>
  );
  const correct = question?.options.findIndex((option) => option.is_correct) ?? -1;
  return <section className="tma-audit-workspace" aria-label="Assignment question review">
    <aside className="tma-audit-sidebar" aria-label="Question navigation">
      <header className="tma-audit-sidebar-header">
        <div><h2>Question bank</h2><p>{questions.length} saved questions</p></div>
        <BookOpen size={19} aria-hidden="true" />
      </header>
      <div className="tma-audit-question-nav">
        {questions.map((item, i) => <button
          key={item.id} type="button"
          className={`tma-audit-nav-item ${item.id === question?.id ? "is-selected" : ""}`}
          aria-current={item.id === question?.id ? "true" : undefined}
          onClick={() => { setSelectedId(item.id); setStudentView(false); }}
        >
          <span className="tma-audit-nav-number">{String(i + 1).padStart(2, "0")}</span>
          <span className="tma-audit-nav-copy">
            <strong>{item.question_text || "Image-based question"}</strong>
            <small>Single choice · {item.options.length} options</small>
          </span>
          {(item.image_asset_id || item.options.some((o) => o.image_asset_id)) &&
            <Image size={14} aria-label="Contains image" />}
        </button>)}
      </div>
    </aside>
    <div className="tma-audit-detail" aria-live="polite">
      <header className="tma-audit-detail-toolbar">
        <div>
          <span className="tma-eyebrow">{studentView ? "Student-facing preview" : "Answer key review"}</span>
          <h2>Question {selectedIndex + 1} <span>of {questions.length}</span></h2>
        </div>
        <div className="tma-audit-toolbar-actions">
          <Button variant="outline" size="sm" onClick={() => setStudentView((value) => !value)}>
            {studentView ? <EyeOff size={16} /> : <Eye size={16} />}
            {studentView ? "Show answer key" : "Student view"}
          </Button>
          <Link to={`${assignmentPath}/questions/${question.id}`}
            className="tma-audit-open-preview" aria-label={`Open full preview of question ${selectedIndex + 1}`}>
            <ArrowUpRight size={16} /> Full preview
          </Link>
        </div>
      </header>
      <div className="tma-audit-body">
        <div className="tma-audit-prompt">
          <MathText>{question.question_text || ""}</MathText>
          {question.image_asset_id && <TmaAssetImage autoLoad assignmentId={question.assignment_id}
            assetId={question.image_asset_id} alt="Question illustration" />}
        </div>
        <div className="tma-audit-answer-heading">
          <h3>Answer options</h3>
          <span>{studentView ? "Correct answer hidden" : "Correct answer highlighted"}</span>
        </div>
        <div className="tma-audit-options">
          {question.options.map((option, i) => (
            <div key={option.id || i}
              className={`tma-audit-option ${!studentView && option.is_correct ? "is-correct" : ""}`}>
              <span className="tma-option-letter">{String.fromCharCode(65 + i)}</span>
              <div className="min-w-0 flex-1">
                <MathText>{option.option_text || ""}</MathText>
                {option.image_asset_id && <TmaAssetImage autoLoad assignmentId={question.assignment_id}
                  assetId={option.image_asset_id} alt={`Option ${i + 1}`} />}
              </div>
              {!studentView && option.is_correct && <span className="tma-audit-correct-label">
                <CheckCircle2 size={16} /> Correct
              </span>}
            </div>
          ))}
        </div>
        {!studentView && <p className="tma-audit-answer-note">
          Answer key: <strong>{correct < 0 ? "Missing correct answer" : String.fromCharCode(65 + correct)}</strong>
          <span> · Confirm the key before publishing.</span>
        </p>}
      </div>
      <footer className="tma-audit-detail-footer">
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" disabled={selectedIndex === 0}
            onClick={() => { setSelectedId(questions[selectedIndex - 1].id); setStudentView(false); }}>Previous</Button>
          <Button size="sm" variant="outline" disabled={selectedIndex === questions.length - 1}
            onClick={() => { setSelectedId(questions[selectedIndex + 1].id); setStudentView(false); }}>Next</Button>
        </div>
        {editable && canEdit(question) ? <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={busy} onClick={() => onEdit(question)}>
            <Pencil size={15} /> Edit
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => onDelete(question)}
            aria-label={`Delete question ${selectedIndex + 1}`}>
            <Trash2 size={15} className="text-error" /> Delete
          </Button>
        </div> : <span className="text-xs text-text-muted">Read only after publishing</span>}
      </footer>
    </div>
  </section>;
}
