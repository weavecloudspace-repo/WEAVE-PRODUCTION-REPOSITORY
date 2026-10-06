import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Archive,
  ArrowRight,
  CheckCircle2,
  Edit3,
  Info,
} from "lucide-react";

import EmptyState from "../../components/shared/EmptyState";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import Input from "../../components/ui/Input";
import SearchableSelect from "../../components/ui/SearchableSelect";
import { cn } from "../../utils/cn";

export function WorkspaceGrid({ editor, content, wide = false }) {
  if (!editor || !content) {
    return (
      <section className="grid gap-4">
        <div className="min-w-0">{editor || content}</div>
      </section>
    );
  }

  return (
    <section
      className={cn(
        "grid gap-4",
        wide
          ? "2xl:grid-cols-[minmax(0,1.65fr)_minmax(300px,0.7fr)]"
          : "xl:grid-cols-[minmax(0,1.55fr)_minmax(300px,0.72fr)]",
      )}
    >
      <div className="min-w-0">{content}</div>
      <div className="min-w-0 xl:sticky xl:top-4 xl:self-start">{editor}</div>
    </section>
  );
}

export function WorkspacePanel({ title, description, children, actions }) {
  return (
    <Card className="rounded-xl p-4 shadow-none sm:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h3 className="section-title">{title}</h3>
          {description ? (
            <p className="mt-1 text-sm leading-6 text-text-muted">{description}</p>
          ) : null}
        </div>
        {actions ? (
          <div className="w-full sm:w-auto sm:max-w-xs sm:shrink-0">{actions}</div>
        ) : null}
      </div>
      <div className="mt-4">{children}</div>
    </Card>
  );
}

export function SelectControl({
  label,
  value,
  onChange,
  options,
  placeholder = "Select an option",
  required = false,
  disabled = false,
  error,
  searchPlaceholder,
  searchable = true,
  clearable = false,
}) {
  return (
    <SearchableSelect
      label={label}
      value={value || ""}
      onChange={onChange}
      options={options}
      placeholder={placeholder}
      searchPlaceholder={
        searchPlaceholder || `Search ${String(label || "options").toLowerCase()}`
      }
      required={required}
      disabled={disabled}
      error={error}
      searchable={searchable}
      clearable={clearable}
    />
  );
}

export function CheckboxControl({ label, checked, onChange, disabled = false }) {
  return (
    <label className="flex min-h-11 items-center gap-3 rounded-xl border border-border/70 bg-surface px-3 py-2 text-sm font-medium text-text-soft">
      <input
        type="checkbox"
        checked={Boolean(checked)}
        onChange={(event) => onChange(event.target.checked)}
        disabled={disabled}
        className="h-4 w-4 rounded border-border accent-primary"
      />
      {label}
    </label>
  );
}

export function FormActions({
  submitting,
  submitLabel,
  repeatLabel,
  closeLabel = "Save & close",
  editing = false,
  onCancel,
  disabled = false,
  repeatable = false,
}) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row">
      <Button type="submit" name="saveIntent" value="another" disabled={submitting || disabled}>
        {submitting ? "Saving..." : repeatable ? editing ? "Save changes" : repeatLabel || "Save & add another" : submitLabel}
      </Button>
      {repeatable && !editing ? (
        <Button type="submit" name="saveIntent" value="close" variant="outline" disabled={submitting || disabled}>
          {closeLabel}
        </Button>
      ) : null}
      {onCancel ? (
        <Button type="button" variant="outline" onClick={onCancel} disabled={submitting}>
          Cancel
        </Button>
      ) : null}
    </div>
  );
}

const lifecycleStatusMeta = (status) => {
  const value = String(status || "").toLowerCase();
  if (["active", "current", "submitted", "published", "complete"].includes(value)) {
    return {
      badge: "success",
      Icon: CheckCircle2,
      iconClassName: "text-success",
    };
  }
  if (["archived", "draft", "pending", "read_only"].includes(value)) {
    return {
      badge: "warning",
      Icon: value === "archived" ? Archive : AlertTriangle,
      iconClassName: "text-warning",
    };
  }
  if (["inactive", "ended", "failed", "revoked"].includes(value)) {
    return {
      badge: "error",
      Icon: AlertTriangle,
      iconClassName: "text-error",
    };
  }
  return {
    badge: "default",
    Icon: Info,
    iconClassName: "text-text-muted",
  };
};

const badgeVariant = (status) => {
  return lifecycleStatusMeta(status).badge;
};

export function AcademicStatusBadge({ label, status, helper }) {
  const readableStatus = String(status || "Not set").replaceAll("_", " ");
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      {label ? <span className="text-sm font-semibold text-text-soft">{label}:</span> : null}
      <Badge variant={badgeVariant(status)} title={readableStatus}>
        {readableStatus}
      </Badge>
      {helper ? <span className="text-sm text-text-muted">{helper}</span> : null}
    </div>
  );
}

export function AcademicOverviewCard({ icon: Icon, label, value, status, description, action }) {
  return (
    <Card className="flex min-h-[7.5rem] flex-col p-3 sm:min-h-[9rem] sm:p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-text-muted sm:text-sm">{label}</p>
          <p className="mt-1 break-words text-lg font-semibold leading-tight text-text sm:mt-2 sm:text-2xl">
            {value}
          </p>
        </div>
        {Icon ? (
          <div className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary sm:h-10 sm:w-10">
            <Icon className="h-4 w-4 sm:h-5 sm:w-5" />
          </div>
        ) : null}
      </div>
      {status ? (
        <div className="mt-2 sm:mt-3">
          <AcademicStatusBadge status={status} />
        </div>
      ) : null}
      {description ? (
        <p className="mt-auto line-clamp-2 pt-2 text-xs leading-5 text-text-muted sm:pt-3 sm:text-sm sm:leading-6">
          {description}
        </p>
      ) : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </Card>
  );
}

export function AcademicNextActionCard({
  title = "Recommended next action",
  action,
  description,
  buttonLabel,
  onAction,
}) {
  const content = (
    <>
      <ArrowRight className="h-4 w-4" />
      {buttonLabel || "Continue"}
    </>
  );

  return (
    <Card className="border-primary/30 bg-primary-soft/40 p-3 sm:p-5">
      <p className="text-xs font-semibold uppercase text-primary sm:text-sm">{title}</p>
      <h3 className="mt-1 text-base font-semibold leading-tight text-text sm:mt-2 sm:text-xl">
        {action}
      </h3>
      {description ? (
        <p className="mt-2 line-clamp-2 text-xs leading-5 text-text-muted sm:text-sm sm:leading-6">
          {description}
        </p>
      ) : null}
      {onAction ? (
        <div className="mt-3 sm:mt-4">
          <Button type="button" size="small" onClick={onAction}>
            {content}
          </Button>
        </div>
      ) : null}
    </Card>
  );
}

export function AcademicBlockerList({ title = "Needs attention", blockers = [] }) {
  const items = blockers.filter(Boolean);
  return (
    <Card className="p-3 sm:p-5">
      <div className="flex items-center gap-2">
        <AlertTriangle className="h-5 w-5 text-warning" />
        <h3 className="section-title">{title}</h3>
      </div>
      {items.length === 0 ? (
        <p className="mt-3 text-sm text-text-muted">No blockers need attention right now.</p>
      ) : (
        <div className="mt-3 grid gap-2 sm:block sm:space-y-2">
          {items.map((blocker) => (
            <div
              key={blocker.key || blocker.label || blocker.message}
              className="rounded-xl border border-warning/30 bg-warning-soft px-3 py-2 text-sm text-amber-950"
            >
              <p className="font-semibold">{blocker.label || blocker.message}</p>
              {blocker.description ? <p className="mt-1">{blocker.description}</p> : null}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export function AcademicLifecycleStepper({ steps, current }) {
  return (
    <div className="grid gap-2 sm:grid-cols-4">
      {steps.map((step, index) => {
        const active = step.id === current;
        const complete = steps.findIndex((item) => item.id === current) > index;
        return (
          <div
            key={step.id}
            data-state={active ? "active" : complete ? "complete" : "idle"}
            className={cn(
              "academic-lifecycle-step rounded-lg border px-3 py-2.5",
              active
                ? "border-primary/40 bg-primary-soft"
                : complete
                  ? "border-success/30 bg-success-soft"
                  : "border-border/70 bg-surface",
            )}
          >
            <div className="flex items-center gap-2">
              {complete ? <CheckCircle2 className="h-4 w-4 text-success" /> : null}
              <p className="academic-lifecycle-step-title text-sm font-semibold text-text">
                {step.label}
              </p>
            </div>
            {active && step.helper ? (
              <p className="academic-lifecycle-step-helper mt-1 text-xs leading-5 text-text-muted">
                {step.helper}
              </p>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function DefaultRecordInspector({
  item,
  renderTitle,
  renderMeta,
  renderDescription,
  renderStatus,
  renderActions,
  onEdit,
  canEdit,
  showDefaultEditAction = true,
}) {
  const status = renderStatus?.(item);
  const statusMeta = lifecycleStatusMeta(status);
  const StatusIcon = statusMeta.Icon;
  const showEdit =
    showDefaultEditAction && Boolean(onEdit) && (canEdit ? canEdit(item) : true);

  return (
    <div className="overflow-hidden rounded-xl border border-border/70 bg-surface">
      <div className="border-b border-border/70 px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-base font-semibold text-text">{renderTitle(item)}</p>
            {renderMeta ? (
              <p className="mt-1 text-xs leading-5 text-text-muted">{renderMeta(item)}</p>
            ) : null}
          </div>
          {status ? (
            <Badge variant={badgeVariant(status)}>{String(status).replaceAll("_", " ")}</Badge>
          ) : null}
        </div>
      </div>

      <div className="divide-y divide-border/70">
        <section className="px-4 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-text-faint">
            Details
          </p>
          <p className="mt-2 text-sm leading-6 text-text-muted">
            {renderDescription ? renderDescription(item) : "No additional details are available."}
          </p>
        </section>

        <section className="px-4 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-text-faint">
            Lifecycle
          </p>
          <div className="mt-2 flex items-start gap-2">
            <StatusIcon
              className={cn(
                "mt-0.5 h-4 w-4 shrink-0",
                statusMeta.iconClassName,
              )}
            />
            <div>
              <p className="text-sm font-semibold text-text">
                {status ? String(status).replaceAll("_", " ") : "No lifecycle state"}
              </p>
              <p className="mt-1 text-xs leading-5 text-text-muted">
                Lifecycle operations shown here use the same backend guards as the row actions.
              </p>
            </div>
          </div>
        </section>

        {showEdit || renderActions ? (
          <section className="px-4 py-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-text-faint">
              Quick actions
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {renderActions ? renderActions(item) : null}
              {showEdit ? (
                <Button type="button" size="small" variant="outline" onClick={() => onEdit(item)}>
                  <Edit3 className="h-4 w-4" /> Edit
                </Button>
              ) : null}
            </div>
          </section>
        ) : null}
      </div>
    </div>
  );
}

export function RecordList({
  title,
  description,
  items: records,
  emptyTitle,
  emptyDescription,
  emptyIcon,
  renderTitle,
  renderMeta,
  renderDescription,
  renderStatus,
  renderActions,
  renderInspector,
  onEdit,
  canEdit,
  showDefaultEditAction = true,
  actions,
  toolbar,
  listClassName,
  showInspector = true,
  loading = false,
  error = "",
  onRetry,
  recordLabel = "Record",
  detailsLabel = "Details",
}) {
  const [query, setQuery] = useState("");
  const items = useMemo(() => {
    const search = query.trim().toLowerCase();
    return search ? records.filter((item) =>
      [renderTitle(item), renderMeta?.(item), renderDescription?.(item), renderStatus?.(item)]
        .filter((value) => typeof value === "string").join(" ").toLowerCase().includes(search),
    ) : records;
  }, [query, records, renderTitle, renderMeta, renderDescription, renderStatus]);
  const [selectedRecordId, setSelectedRecordId] = useState(items[0]?.id || "");

  useEffect(() => {
    if (!items.length) {
      setSelectedRecordId("");
      return;
    }
    if (!items.some((item) => String(item.id) === String(selectedRecordId))) {
      setSelectedRecordId(items[0].id);
    }
  }, [items, selectedRecordId]);

  const selectedItem = useMemo(
    () =>
      items.find((item) => String(item.id) === String(selectedRecordId)) || items[0] || null,
    [items, selectedRecordId],
  );

  return (
    <WorkspacePanel title={title} description={description} actions={actions}>
      {toolbar}
      <div className="mb-3 flex items-end gap-3">
        <Input label={`Search ${title}`} value={query} onChange={(event) => setQuery(event.target.value)} />
        <span className="shrink-0 pb-3 text-xs text-text-muted" role="status">{items.length} of {records.length}</span>
      </div>
      {error ? (
        <div role="alert" className="space-y-2 text-sm text-error">
          <p>{error}</p>
          {onRetry ? <Button type="button" variant="outline" onClick={onRetry}>Retry loading</Button> : null}
        </div>
      ) : loading ? <p role="status" className="text-sm text-text-muted">Loading records…</p> : items.length === 0 ? (
        <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />
      ) : (
        <div
          className={cn(
            "grid gap-4",
            showInspector && "xl:grid-cols-[minmax(0,1.6fr)_minmax(280px,0.62fr)]",
          )}
        >
          <div className="min-w-0">
            <div
              className={cn(
                "hidden overflow-x-auto rounded-lg border border-border/70 lg:block",
                listClassName,
              )}
            >
              <table className="w-full min-w-[46rem] border-collapse text-left">
                <thead className="bg-surface-muted/55 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
                  <tr>
                    <th className="px-4 py-3">{recordLabel}</th>
                    <th className="px-4 py-3">{detailsLabel}</th>
                    <th className="px-4 py-3">Lifecycle</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/70">
                  {items.map((item) => {
                    const status = renderStatus?.(item);
                    const showEdit =
                      showDefaultEditAction &&
                      Boolean(onEdit) &&
                      (canEdit ? canEdit(item) : true);
                    const selected = String(item.id) === String(selectedItem?.id);
                    return (
                      <tr
                        key={item.id}
                        onClick={() => setSelectedRecordId(item.id)}
                        className={cn(
                          "cursor-pointer bg-surface transition hover:bg-surface-muted/35",
                          selected && "bg-primary-soft/35",
                        )}
                      >
                        <td className="px-4 py-3 align-top">
                          <button type="button" className="text-left font-semibold text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary" aria-pressed={selected} onClick={() => setSelectedRecordId(item.id)}>{renderTitle(item)}</button>
                          {renderMeta ? (
                            <p className="mt-1 text-xs text-text-muted">{renderMeta(item)}</p>
                          ) : null}
                        </td>
                        <td className="max-w-md px-4 py-3 align-top text-sm leading-5 text-text-muted">
                          {renderDescription ? renderDescription(item) : "-"}
                        </td>
                        <td className="px-4 py-3 align-top">
                          {status ? (
                            <Badge
                              variant={badgeVariant(status)}
                              title={String(status).replaceAll("_", " ")}
                            >
                              {String(status).replaceAll("_", " ")}
                            </Badge>
                          ) : (
                            <span className="text-sm text-text-muted">-</span>
                          )}
                        </td>
                        <td className="px-4 py-3 align-top">
                          <div className="flex flex-wrap justify-end gap-2">
                            {renderActions ? renderActions(item) : null}
                            {showEdit ? (
                              <Button
                                type="button"
                                size="small"
                                variant="outline"
                                onClick={() => onEdit(item)}
                              >
                                <Edit3 className="h-4 w-4" /> Edit
                              </Button>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="mobile-scroll-list record-list-grid grid grid-cols-1 gap-3 lg:hidden">
              {items.map((item) => {
                const status = renderStatus?.(item);
                const showEdit =
                  showDefaultEditAction &&
                  Boolean(onEdit) &&
                  (canEdit ? canEdit(item) : true);
                return (
                  <div
                    key={item.id}
                    className="flex min-h-[9rem] flex-col rounded-xl border border-border/70 bg-surface px-4 py-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="break-words text-sm font-semibold text-text">
                          {renderTitle(item)}
                        </p>
                        {renderMeta ? (
                          <p className="mt-1 break-words text-xs text-text-muted">
                            {renderMeta(item)}
                          </p>
                        ) : null}
                      </div>
                      {status ? (
                        <Badge variant={badgeVariant(status)}>
                          {String(status).replaceAll("_", " ")}
                        </Badge>
                      ) : null}
                    </div>
                    {renderDescription ? (
                      <p className="mt-3 line-clamp-3 text-sm leading-6 text-text-muted">
                        {renderDescription(item)}
                      </p>
                    ) : null}
                    {showEdit || renderActions ? (
                      <div className="mt-auto flex flex-wrap gap-2 pt-4">
                        {renderActions ? renderActions(item) : null}
                        {showEdit ? (
                          <Button
                            type="button"
                            size="small"
                            variant="outline"
                            onClick={() => onEdit(item)}
                          >
                            <Edit3 className="h-4 w-4" /> Edit
                          </Button>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>

          {showInspector && selectedItem ? (
            <aside className="hidden min-w-0 xl:block xl:sticky xl:top-4 xl:self-start">
              {renderInspector ? (
                renderInspector(selectedItem)
              ) : (
                <DefaultRecordInspector
                  item={selectedItem}
                  renderTitle={renderTitle}
                  renderMeta={renderMeta}
                  renderDescription={renderDescription}
                  renderStatus={renderStatus}
                  renderActions={renderActions}
                  onEdit={onEdit}
                  canEdit={canEdit}
                  showDefaultEditAction={showDefaultEditAction}
                />
              )}
            </aside>
          ) : null}
        </div>
      )}
    </WorkspacePanel>
  );
}

export { Input };
