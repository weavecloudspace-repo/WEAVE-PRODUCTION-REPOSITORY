import {
  Children,
  cloneElement,
  isValidElement,
  useEffect,
  useId,
  useState,
} from "react";
import { ChevronDown, UserRound } from "lucide-react";

import Card from "../ui/Card";
import { cn } from "../../utils/cn";

export function DirectorySummary({ items }) {
  return (
    <dl className="people-directory-summary grid grid-cols-2 gap-2.5 sm:gap-3 md:grid-cols-4">
      {items.map(({ label, value, detail, icon: Icon, tone = "default" }) => (
        <Card
          key={label}
          className="rounded-xl border-border/80 p-3 shadow-sm"
        >
          <div className="flex flex-col items-start gap-2">
            <span
              className={cn(
                "grid h-9 w-9 shrink-0 place-items-center rounded-full",
                tone === "success"
                  ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-300"
                  : tone === "warning"
                    ? "bg-amber-50 text-amber-600 dark:bg-amber-950/50 dark:text-amber-300"
                    : tone === "error"
                      ? "bg-rose-50 text-rose-600 dark:bg-rose-950/50 dark:text-rose-300"
                      : tone === "primary"
                        ? "bg-violet-50 text-violet-600 dark:bg-violet-950/50 dark:text-violet-300"
                        : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
              )}
            >
              <Icon className="h-4 w-4" />
            </span>
            <div>
              <dt className="people-summary-label text-xs font-medium leading-4 text-text-muted">
                {label}
              </dt>
              <dd className="people-summary-value mt-0.5 text-xl font-semibold leading-none text-text sm:text-2xl">
                {value}
              </dd>
              {detail ? (
                <p className="people-summary-detail mt-1.5 line-clamp-1 text-[0.68rem] leading-4 text-text-muted sm:text-xs">
                  {detail}
                </p>
              ) : null}
            </div>
          </div>
        </Card>
      ))}
    </dl>
  );
}

export function DirectoryTable({ columns, children, label }) {
  return (
    <Card className="hidden overflow-hidden p-0 md:block">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-left" aria-label={label}>
          <thead>
            <tr className="border-b border-border/80 bg-surface-muted/35">
              {columns.map((column) => (
                <th
                  key={column.key || column.label}
                  scope="col"
                  className={cn(
                    "px-4 py-3 text-[0.68rem] font-bold uppercase tracking-[0.08em] text-text-muted",
                    column.className,
                  )}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/70">{children}</tbody>
        </table>
      </div>
    </Card>
  );
}

export function PersonIdentity({
  name,
  meta,
  avatarSrc,
  icon: Icon = UserRound,
  size = "default",
}) {
  const [imageFailed, setImageFailed] = useState(false);
  const prominent = size === "large";

  useEffect(() => {
    setImageFailed(false);
  }, [avatarSrc]);

  return (
    <div className={cn(
      "people-person-identity flex min-w-0 items-center py-0.5",
      prominent ? "gap-4" : "gap-3.5",
    )}>
      <span className={cn(
        "grid shrink-0 place-items-center overflow-hidden border border-primary/10 bg-primary-soft text-primary",
        prominent ? "h-16 w-16 rounded-2xl" : "h-10 w-10 rounded-xl",
      )}>
        {avatarSrc && !imageFailed ? (
          <img
            src={avatarSrc}
            alt=""
            className="h-full w-full object-cover object-center"
            onError={() => setImageFailed(true)}
          />
        ) : (
          <Icon
            className={prominent ? "h-7 w-7" : "h-[1.125rem] w-[1.125rem]"}
            aria-hidden="true"
          />
        )}
      </span>
      <div className="min-w-0">
        <p className={cn(
          "truncate font-semibold text-text",
          prominent ? "text-2xl leading-tight" : "text-sm leading-5",
        )}>{name}</p>
        <p className={cn(
          "truncate text-text-muted",
          prominent ? "mt-1 text-sm leading-5" : "text-xs leading-4",
        )}>{meta}</p>
      </div>
    </div>
  );
}

export function MobileDirectoryList({ children, className, label }) {
  const rows = Children.toArray(children);
  const rowIdentity = rows
    .map((row, index) => (isValidElement(row) ? row.key : index))
    .join("|");
  const [expandedIndex, setExpandedIndex] = useState(-1);

  useEffect(() => {
    setExpandedIndex(-1);
  }, [label, rowIdentity]);

  return (
    <section
      aria-label={label}
      className={cn(
        "people-mobile-list mobile-scroll-list overflow-hidden rounded-2xl border border-border/80 bg-surface md:hidden",
        className,
      )}
    >
      {rows.map((child, index) =>
        isValidElement(child)
          ? cloneElement(child, {
              expanded: expandedIndex === index,
              onExpandedChange: (nextExpanded) =>
                setExpandedIndex(nextExpanded ? index : -1),
            })
          : child,
      )}
    </section>
  );
}

export function MobilePersonCard({
  children,
  className,
  expanded = false,
  onExpandedChange,
  tone = "primary",
}) {
  const detailsId = useId();
  const sections = Children.toArray(children);
  const summary = sections[0];
  const details = sections.slice(1);

  return (
    <article
      data-tone={tone}
      className={cn(
        "people-mobile-row relative px-3.5 py-3.5 md:hidden",
        expanded && "is-expanded",
        className,
      )}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">{summary}</div>
        {details.length ? (
          <button
            type="button"
            aria-expanded={expanded}
            aria-controls={detailsId}
            aria-label={expanded ? "Hide row details" : "Show row details"}
            className="grid h-11 w-9 shrink-0 place-items-center rounded-xl text-text-muted transition hover:bg-surface-muted hover:text-text"
            onClick={() => {
              const nextExpanded = !expanded;
              onExpandedChange?.(nextExpanded);
            }}
          >
            <ChevronDown
              className={cn(
                "h-4 w-4 transition-transform duration-200",
                expanded && "rotate-180",
              )}
            />
          </button>
        ) : null}
      </div>
      {details.length ? (
        <div
          id={detailsId}
          className={cn(
            "people-mobile-row-details grid transition-[grid-template-rows,opacity] duration-200",
            expanded
              ? "grid-rows-[1fr] opacity-100"
              : "pointer-events-none grid-rows-[0fr] opacity-0",
          )}
        >
          <div className="min-h-0 overflow-hidden">{details}</div>
        </div>
      ) : null}
    </article>
  );
}
