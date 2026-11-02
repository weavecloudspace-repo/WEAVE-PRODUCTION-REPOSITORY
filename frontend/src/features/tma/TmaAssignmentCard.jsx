import { ArrowUpRight, BookOpen, CalendarDays } from "lucide-react";
import { Link } from "react-router-dom";

const guidance = {
  draft: "Build questions and review before publishing",
  active: "Available for eligible students to complete",
  closed: "Student access is closed",
  cancelling: "Score reversal is being processed",
  cancelled: "Create a corrected revision when ready",
};
export default function TmaAssignmentCard({
  assignment,
  scope,
  component,
  to,
}) {
  const a = assignment;
  return (
    <Link
      to={to}
      className={`tma-assignment-card tma-assignment-card--${a.status}`}
    >
      <header>
        <span className="tma-card-icon">
          <BookOpen size={21} />
        </span>
        <span className="tma-card-status">
          {a.status === "cancelling" ? "Cancelling…" : a.status}
        </span>
        <ArrowUpRight size={18} className="tma-card-arrow" />
      </header>
      <div className="tma-card-title">
        <span className="tma-eyebrow">
          {scope?.level_name || "Tutor marked assignment"}
        </span>
        <h2>{scope?.subject_name || "Assignment"}</h2>
        <p>{guidance[a.status] || "Open assignment to view details"}</p>
      </div>
      <div className="tma-card-allocation">
        <span>{component?.name || "Assessment component"}</span>
        <strong>
          {component
            ? `${component.maximum_score} marks`
            : `Revision ${a.current_revision_number}`}
        </strong>
      </div>
      <footer>
        <div>
          <CalendarDays size={14} />
          <span>
            {a.closes_at
              ? `Expected ${new Date(a.closes_at).toLocaleDateString()}`
              : "No closing estimate"}
          </span>
        </div>
        <span>Revision {a.current_revision_number}</span>
      </footer>
      <div className="tma-card-open">
        {a.status === "draft" ? "Continue editing" : "Open assignment"}
        <ArrowUpRight size={15} />
      </div>
    </Link>
  );
}
