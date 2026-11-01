import { BookOpen, Pencil } from "lucide-react";
import Button from "../../components/ui/Button";
import MathText from "./MathText.jsx";
import { TmaAssetImage } from "./TmaQuestionEditor";

export default function TmaQuestionList({
  questions,
  assignmentId,
  editable,
  canEdit,
  onEdit,
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
    <div className="space-y-4">
      {questions.map((q, i) => (
        <article key={q.id} className="tma-question-record">
          <header>
            <span className="tma-question-number">
              {String(i + 1).padStart(2, "0")}
            </span>
            <div>
              <h3>Question {i + 1}</h3>
              <p>Single choice · {q.options.length} options</p>
            </div>
            {editable && canEdit(q) && (
              <Button variant="ghost" onClick={() => onEdit(q)}>
                <Pencil size={14} />
                Edit
              </Button>
            )}
          </header>
          <div className="tma-question-prompt">
            <MathText>{q.question_text}</MathText>
            {q.image_asset_id && (
              <TmaAssetImage
                key={q.image_asset_id}
                assignmentId={assignmentId}
                assetId={q.image_asset_id}
                alt="Question illustration"
              />
            )}
          </div>
          <details className="tma-question-answers">
            <summary>
              Answer options <span>1 correct answer</span>
            </summary>
            <div>
              {q.options.map((o, j) => (
                <div key={o.id} className={o.is_correct ? "is-correct" : ""}>
                  <span className="tma-option-letter">
                    {String.fromCharCode(65 + j)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <MathText>{o.option_text}</MathText>
                    {o.image_asset_id && (
                      <TmaAssetImage
                        key={o.image_asset_id}
                        assignmentId={assignmentId}
                        assetId={o.image_asset_id}
                        alt={`Option ${j + 1}`}
                      />
                    )}
                  </div>
                  {o.is_correct && (
                    <span className="text-[10px] font-semibold text-primary">
                      Correct
                    </span>
                  )}
                </div>
              ))}
            </div>
          </details>
        </article>
      ))}
    </div>
  );
}
