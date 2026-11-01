import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ClipboardList } from "lucide-react";
import { studentTmaService } from "../../../services/studentTmaService";
import { subjectAssignments } from "./attemptState";

export default function StudentSubjectTma({ subject }) {
  const [items, setItems] = useState([]);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const request = useRef(0);
  const mounted = useRef(false);
  const refresh = useCallback(async () => {
    const version = ++request.current;
    try {
      const response = await studentTmaService.list();
      if (mounted.current && request.current === version) {
        setItems(response);
        setError(false);
      }
    } catch {
      if (mounted.current && request.current === version) setError(true);
    } finally {
      if (mounted.current && request.current === version) setLoading(false);
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    refresh();
    const visible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    const timer = window.setInterval(visible, 30000);
    window.addEventListener("focus", visible);
    document.addEventListener("visibilitychange", visible);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", visible);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [refresh]);
  if (loading)
    return (
      <p role="status" className="px-5 pb-4 text-xs text-text-muted">
        Checking for assignments…
      </p>
    );
  if (error)
    return (
      <div
        role="alert"
        className="flex flex-wrap items-center gap-3 px-5 pb-4 text-xs text-text-muted"
      >
        Assignments could not be checked.{" "}
        <button
          type="button"
          className="min-h-11 font-semibold text-primary underline"
          onClick={refresh}
        >
          Try again
        </button>
      </div>
    );
  const available = subjectAssignments(items, subject);
  if (!available.length) return null;
  return (
    <div className="space-y-3 border-t border-border/70 bg-primary/5 px-5 py-4 sm:px-6">
      {available.map((item) => {
        const name =
          subject.components?.find(
            (c) => c.assessment_component_id === item.assessment_component_id,
          )?.name || "Tutor Marked Assignment";
        return (
          <div
            key={item.assignment_id}
            className="flex flex-wrap items-center justify-between gap-3"
          >
            <div className="flex items-center gap-3">
              <ClipboardList className="h-5 w-5 shrink-0 text-primary" />
              <div>
                <p className="text-sm font-semibold text-text">{name}</p>
                {item.status === "closed" && (
                  <span className="mt-1 inline-flex rounded-full border border-border px-2 py-0.5 text-xs font-semibold text-text-muted">
                    Closed
                  </span>
                )}
                <p className="mt-1 text-xs text-text-muted">
                  {item.attempt_status === "submitted"
                    ? "Submitted · your result is ready"
                    : item.status === "closed"
                      ? "Closed · the submission deadline has passed"
                      : item.attempt_status === "in_progress"
                        ? "Your saved attempt is ready to continue"
                        : "A new assignment is available"}{" "}
                  · {item.component_maximum_score} marks
                </p>
              </div>
            </div>
            {item.attempt_status === "submitted" ? (
              <Link
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none focus-visible:ring-primary focus-visible:ring-offset-2"
                to={`/student/subjects/${subject.id}/tma/${item.assignment_id}`}
              >
                View TMA result <ArrowRight size={16} />
              </Link>
            ) : item.status === "closed" || !item.can_start_or_resume ? (
              <span className="inline-flex min-h-11 items-center rounded-xl border border-border bg-surface-muted px-4 py-2 text-sm font-semibold text-text-muted">
                Closed
              </span>
            ) : (
              <Link
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
                to={`/student/subjects/${subject.id}/tma/${item.assignment_id}`}
              >
                {item.attempt_status === "in_progress" ? "Continue TMA" : "Start TMA"}
                <ArrowRight size={16} />
              </Link>
            )}
          </div>
        );
      })}
    </div>
  );
}
