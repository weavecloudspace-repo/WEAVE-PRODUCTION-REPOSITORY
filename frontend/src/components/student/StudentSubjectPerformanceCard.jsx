import { ArrowUpRight, BookOpen, UserRound } from "lucide-react";
import { Link } from "react-router-dom";
import {
  displayStatusLabel,
  hasValue,
  scoreDisplayValue,
  statusVariant,
} from "../../pages/student/studentPageUtils";
import { cleanText } from "../../utils/academicDashboard";
import { cn } from "../../utils/cn";
import Badge from "../ui/Badge";
import Card from "../ui/Card";

function ScoreRing({ score, maximum }) {
  const hasScore = hasValue(score) && Number.isFinite(Number(score));
  const hasMaximum =
    hasValue(maximum) &&
    Number.isFinite(Number(maximum)) &&
    Number(maximum) > 0;
  const ratio =
    hasScore && hasMaximum
      ? Math.min(1, Math.max(0, Number(score) / Number(maximum)))
      : 0;

  return (
    <div
      className="relative grid h-16 w-16 shrink-0 place-items-center rounded-full text-primary sm:h-20 sm:w-20"
      role={hasScore && hasMaximum ? "meter" : "img"}
      aria-label={
        hasScore && hasMaximum
          ? "Total score"
          : hasScore
            ? `Total score: ${scoreDisplayValue(score)}; no maximum configured`
            : "Total score: awaiting marks"
      }
      aria-valuemin={hasScore && hasMaximum ? 0 : undefined}
      aria-valuemax={hasScore && hasMaximum ? Number(maximum) : undefined}
      aria-valuenow={
        hasScore && hasMaximum
          ? Math.min(Number(maximum), Math.max(0, Number(score)))
          : undefined
      }
      aria-valuetext={
        hasScore && hasMaximum
          ? `${scoreDisplayValue(score)} out of ${scoreDisplayValue(maximum)}`
          : undefined
      }
      style={{
        background: `conic-gradient(currentColor ${ratio * 360}deg, rgb(var(--color-primary) / 0.12) 0deg)`,
      }}
    >
      <div className="absolute inset-1.5 rounded-full bg-surface" />
      <div className="relative text-center" aria-hidden="true">
        <p className="text-lg font-semibold leading-none text-text">
          {scoreDisplayValue(score)}
        </p>
        <p className="mt-1 text-[10px] text-text-muted">
          {hasMaximum ? `of ${scoreDisplayValue(maximum)}` : "No limit"}
        </p>
      </div>
    </div>
  );
}

function StudentSubjectPerformanceCard({
  card,
  classLabel,
  electiveGroupName,
  compact = false,
}) {
  const link = card?.id ? `/student/subjects/${card.id}` : undefined;

  return (
    <Card
      as={link ? Link : "div"}
      to={link}
      className={cn(
        "group flex h-full min-w-0 flex-col overflow-hidden border-border/80 text-left transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2",
        link && "hover:border-primary/35 hover:shadow-md",
        compact && "lg:flex-row lg:items-center",
      )}
    >
      <div
        className={cn(
          "flex items-center justify-between gap-3 border-b border-primary/10 bg-primary/5 px-4 py-2.5",
          compact && "lg:self-stretch lg:border-b-0 lg:border-r lg:px-4",
        )}
      >
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
          <BookOpen className="h-4 w-4" aria-hidden="true" />
        </span>
        <span
          className={cn(
            "text-xs font-semibold text-text-muted",
            compact && "lg:hidden",
          )}
        >
          {cleanText(card?.subject_code, "Subject")}
        </span>
      </div>
      <div
        className={cn(
          "flex min-w-0 flex-1 items-center gap-3 bg-surface px-4 py-4",
          compact && "lg:py-3",
        )}
      >
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-text-muted">
            {electiveGroupName
              ? `Elective / ${electiveGroupName}`
              : cleanText(card?.class_name || classLabel, "Class")}
          </p>
          <h3 className="mt-1.5 break-words text-base font-semibold leading-snug text-text">
            {cleanText(card?.subject_name, "Subject")}
          </h3>
          <div className="mt-2 flex min-w-0 items-start gap-2 text-[13px] text-text-muted">
            <UserRound className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span className="break-words">
              {cleanText(card?.teacher_name, "Teacher not assigned")}
            </span>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Badge variant={statusVariant(card?.status)}>
              {hasValue(card?.total_score)
                ? displayStatusLabel(card?.status)
                : "Awaiting marks"}
            </Badge>
            {electiveGroupName && (
              <span className="text-xs font-medium text-primary">Elective</span>
            )}
          </div>
        </div>
        <ScoreRing score={card?.total_score} maximum={card?.maximum_score} />
      </div>
      <div
        className={cn(
          "flex flex-wrap items-center justify-between gap-3 border-t border-border/70 bg-surface px-4 py-2.5",
          compact &&
            "lg:w-56 lg:shrink-0 lg:self-stretch lg:border-l lg:border-t-0",
        )}
      >
        <div>
          <p className="text-xs text-text-muted">Total score</p>
          <p className="mt-1 text-sm font-semibold tabular-nums text-text">
            {scoreDisplayValue(card?.total_score)}
            {Number(card?.maximum_score) > 0 && (
              <span className="font-normal text-text-muted">
                {" "}
                / {scoreDisplayValue(card.maximum_score)}
              </span>
            )}
            {hasValue(card?.grade) && (
              <span className="ml-2 text-primary">{card.grade}</span>
            )}
          </p>
        </div>
        {link && (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground transition-colors group-hover:bg-primary-hover">
            View subject <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
          </span>
        )}
      </div>
    </Card>
  );
}

export default StudentSubjectPerformanceCard;
