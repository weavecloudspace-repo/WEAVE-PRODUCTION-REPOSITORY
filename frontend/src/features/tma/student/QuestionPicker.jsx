import Button from "../../../components/ui/Button";

export function QuestionPickerActions({
  position,
  total,
  busy,
  onLeave,
  onSubmit,
}) {
  return (
    <div className="student-tma-map-actions">
      <Button
        variant="outline"
        disabled={busy}
        onClick={onLeave}
        aria-label="Save and leave assignment"
      >
        Leave
      </Button>
      {total > 0 && position === total - 1 && (
        <Button disabled={busy} onClick={onSubmit}>
          Submit TMA
        </Button>
      )}
    </div>
  );
}

export default function QuestionPicker({
  questions,
  position,
  answers,
  pending,
  disabled,
  onPick,
}) {
  return (
    <nav className="student-tma-question-grid" aria-label="Question navigator">
      {questions.map((question, index) => (
        <button
          type="button"
          key={question.id}
          disabled={disabled}
          aria-current={position === index ? "step" : undefined}
          aria-label={`Question ${index + 1}, ${pending.includes(question.id) ? "saving" : answers[question.id] ? "answered" : "unanswered"}`}
          className={answers[question.id] ? "is-answered" : ""}
          onClick={() => onPick(index)}
        >
          {index + 1}
        </button>
      ))}
    </nav>
  );
}
