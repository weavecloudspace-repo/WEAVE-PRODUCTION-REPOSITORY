import { beginAcademicSubmission, endAcademicSubmission, finishAcademicCreation } from "./academicSubmission";
import { BookOpen, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import Button from "../../components/ui/Button";
import { useToast } from "../../hooks/useToast";
import { getErrorMessage, parseApiError } from "../../services/api";
import { subjectService } from "../../services/subject.service";
import {
  FormActions,
  Input,
  RecordList,
  WorkspaceGrid,
  WorkspacePanel,
} from "./AcademicWorkspacePrimitives";
import TypedConfirmationDialog from "./TypedConfirmationDialog";

const BLANK_SUBJECT = { name: "", code: "", description: "" };

const asItems = (response) =>
  Array.isArray(response)
    ? response
    : Array.isArray(response?.items)
      ? response.items
      : [];

const lifecycleStatus = (item) =>
  item?.archived_at ? "archived" : item?.is_active === false ? "inactive" : "active";

const dependencyLabel = (key) =>
  ({
    curriculum_subjects_live: "Live curriculum subjects",
    teacher_links_live: "Live teacher links",
    teacher_assignments_live: "Live teacher assignments",
    results_live: "Live result records",
    report_card_lines_live: "Live report-card lines",
    curriculum_subjects_total: "Curriculum subjects",
    teacher_links_total: "Teacher links",
    teacher_assignments_total: "Teacher assignments",
    results_total: "Result records",
    report_card_lines_total: "Report-card lines",
  })[key] || key.replaceAll("_", " ");

const errorWithDependencies = (error, fallback) => {
  const parsed = parseApiError(error, fallback);
  const counts =
    parsed.data?.dependency_counts ||
    parsed.data?.detail?.dependency_counts ||
    parsed.data?.payload?.dependency_counts ||
    {};
  const blockers = Object.entries(counts)
    .filter(([, count]) => Number(count) > 0)
    .map(([key, count]) => `${dependencyLabel(key)}: ${count}`);
  return blockers.length ? `${parsed.message} ${blockers.join("; ")}` : parsed.message;
};

function SubjectsWorkspace({ activeTab = "overview" }) {
  const { showError, showSuccess } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [subjects, setSubjects] = useState([]);
  const [query, setQuery] = useState("");
  const [form, setForm] = useState(BLANK_SUBJECT);
  const [editingId, setEditingId] = useState("");
  const [saving, setSaving] = useState("");
  const [confirmation, setConfirmation] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await subjectService.getSubjects({
        limit: 500,
        includeArchived: true,
      });
      setSubjects(asItems(response));
    } catch (error) {
      showError(getErrorMessage(error, "Could not load subjects."));
    } finally {
      setLoading(false);
    }
  }, [showError]);

  useEffect(() => {
    load();
  }, [load]);

  const rows = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return subjects.filter((item) => {
      const status = lifecycleStatus(item);
      if (["active", "inactive", "archived"].includes(activeTab) && status !== activeTab) {
        return false;
      }
      if (!normalizedQuery) return true;
      return `${item.name || ""} ${item.code || ""} ${item.description || ""}`
        .toLowerCase()
        .includes(normalizedQuery);
    });
  }, [activeTab, query, subjects]);

  const selectView = (view) => {
    const next = new URLSearchParams(searchParams);
    if (view === "create") next.set("returnView", activeTab === "create" ? "overview" : activeTab);
    else next.delete("returnView");
    next.set("view", view);
    next.delete("tab");
    setSearchParams(next, { replace: true });
  };

  const closeEditor = () => {
    setEditingId("");
    setForm(BLANK_SUBJECT);
    selectView(searchParams.get("returnView") || (activeTab === "create" ? "overview" : activeTab));
  };

  const editSubject = (item) => {
    setEditingId(item.id);
    setForm({
      name: item.name || "",
      code: item.code || "",
      description: item.description || "",
    });
  };

  const saveSubject = async (event) => {
    event.preventDefault();
    const submission = beginAcademicSubmission(event, Boolean(saving));
    if (!submission) return;
    setSaving("form");
    try {
      const payload = {
        name: form.name.trim(),
        code: form.code.trim() || null,
        description: form.description.trim() || null,
      };
      if (editingId) {
        await subjectService.updateSubject(editingId, payload);
        showSuccess("Subject updated.");
      } else {
        await subjectService.createSubject(payload);
        showSuccess("Subject created.");
      }
      finishAcademicCreation(submission, () => { setForm(BLANK_SUBJECT); }, closeEditor, Boolean(editingId));
      await load();
    } catch (error) {
      showError(errorWithDependencies(error, "Could not save subject."));
    } finally {
      endAcademicSubmission(submission);
      setSaving("");
    }
  };

  const executeLifecycle = async () => {
    if (!confirmation) return;
    const { item, action } = confirmation;
    setSaving(item.id);
    try {
      if (action === "activate") await subjectService.activateSubject(item.id);
      if (action === "deactivate") await subjectService.deactivateSubject(item.id);
      if (action === "archive") await subjectService.archiveSubject(item.id);
      if (action === "restore") await subjectService.restoreSubject(item.id);
      if (action === "delete") await subjectService.deleteSubject(item.id);
      showSuccess(
        action === "delete"
          ? "Subject permanently deleted."
          : action === "restore"
            ? "Subject restored as inactive."
            : `Subject ${action}d.`,
      );
      setConfirmation(null);
      await load();
    } catch (error) {
      showError(errorWithDependencies(error, `Could not ${action} subject.`));
    } finally {
      setSaving("");
    }
  };

  const requestLifecycle = (item, action) => {
    const config = {
      activate: {
        title: "Activate subject",
        description: `${item.name} becomes available to new curriculum and teaching workflows.`,
        confirmationText: "ACTIVATE_SUBJECT",
        confirmLabel: "Activate subject",
        variant: "success",
      },
      deactivate: {
        title: "Deactivate subject",
        description: `${item.name} can only be deactivated after live academic dependencies are removed. Historical records remain intact.`,
        confirmationText: "DEACTIVATE_SUBJECT",
        confirmLabel: "Deactivate subject",
        variant: "danger",
      },
      archive: {
        title: "Archive subject",
        description: `${item.name} must already be inactive and free of live dependencies. Archiving hides it from normal academic setup.`,
        confirmationText: "ARCHIVE_SUBJECT",
        confirmLabel: "Archive subject",
        variant: "danger",
      },
      restore: {
        title: "Restore subject",
        description: `${item.name} returns as inactive. Activate it separately when it is ready for use again.`,
        confirmationText: "RESTORE_SUBJECT",
        confirmLabel: "Restore subject",
        variant: "primary",
      },
      delete: {
        title: "Permanently delete subject",
        description: `${item.name} can only be permanently deleted if it has never been used by any protected academic record.`,
        confirmationText: "DELETE_SUBJECT",
        confirmLabel: "Delete permanently",
        variant: "danger",
      },
    }[action];
    setConfirmation({ item, action, ...config });
  };

  const showEditor = activeTab === "create" || Boolean(editingId);
  const editingSubject = subjects.find((item) => item.id === editingId) || null;

  const editor = (
    <WorkspacePanel
      title={editingId ? "Edit subject" : "Add subject"}
      onBack={closeEditor}
      backDisabled={Boolean(saving)}
      description={
        editingId
          ? "Name and code become immutable after the subject is first used. Description can still be maintained while the subject is not archived."
          : "Create the school-wide subject once. Curriculum decides which academic levels actually teach it."
      }
    >
      {editingSubject?.archived_at ? (
        <p className="mb-3 rounded-xl border border-warning/30 bg-warning-soft px-3 py-2 text-sm text-warning">
          Archived subjects must be restored before they can be edited.
        </p>
      ) : null}
      <form className="space-y-3" onSubmit={saveSubject}>
        <fieldset disabled={Boolean(saving)} className="space-y-3">
          <Input
            label="Subject name"
            value={form.name}
            onChange={(event) =>
              setForm((current) => ({ ...current, name: event.target.value }))
            }
            required
            disabled={Boolean(editingSubject?.archived_at)}
          />
          <Input
            label="Subject code"
            value={form.code}
            onChange={(event) =>
              setForm((current) => ({ ...current, code: event.target.value }))
            }
            placeholder="MTH"
            disabled={Boolean(editingSubject?.archived_at)}
          />
          <Input
            label="Description"
            value={form.description}
            onChange={(event) =>
              setForm((current) => ({ ...current, description: event.target.value }))
            }
            disabled={Boolean(editingSubject?.archived_at)}
          />
          <FormActions
            submitting={Boolean(saving)}
            submitLabel={editingId ? "Save subject" : "Add subject"}
            repeatable
            editing={Boolean(editingId)}
            disabled={Boolean(editingSubject?.archived_at)}
            onCancel={closeEditor}
          />
        </fieldset>
      </form>
    </WorkspacePanel>
  );

  return (
    <>
      <WorkspaceGrid
        content={
          <RecordList
            title={`Subjects${loading ? "" : ` (${rows.length})`}`}
            description="The tenant-wide subject catalogue. Curriculum placement and department applicability are configured separately."
            actions={
              !showEditor ? (
                <Button type="button" onClick={() => selectView("create")}>
                  Add subject
                </Button>
              ) : null
            }
            items={rows}
            emptyIcon={BookOpen}
            emptyTitle={query ? "No matching subjects" : "No subjects"}
            emptyDescription={
              query
                ? "Try another subject name, code, or description."
                : "Create the first subject in this school catalogue."
            }
            renderTitle={(item) => item.name}
            renderMeta={(item) => item.code || "No subject code"}
            renderDescription={(item) => item.description || "No description"}
            renderStatus={lifecycleStatus}
            showInspector={!showEditor}
            canEdit={(item) => !item.archived_at}
            onEdit={editSubject}
            renderActions={(item) => (
              <SubjectActions
                item={item}
                busy={saving === item.id}
                onAction={requestLifecycle}
              />
            )}
          />
        }
        editor={showEditor ? editor : null}
      />

      {!showEditor ? (
        <div className="mt-4 max-w-xl">
          <label className="relative block">
            <span className="sr-only">Search subjects</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search subjects by name or code"
              className="min-h-10 w-full rounded-lg border border-border bg-surface pl-9 pr-3 text-sm text-text outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15"
            />
          </label>
        </div>
      ) : null}

      <TypedConfirmationDialog
        open={Boolean(confirmation)}
        title={confirmation?.title}
        description={confirmation?.description}
        confirmationText={confirmation?.confirmationText || ""}
        confirmLabel={confirmation?.confirmLabel}
        variant={confirmation?.variant}
        isLoading={saving === confirmation?.item?.id}
        onConfirm={executeLifecycle}
        onCancel={() => setConfirmation(null)}
      />
    </>
  );
}

function SubjectActions({ item, busy, onAction }) {
  const status = lifecycleStatus(item);
  if (status === "active") {
    return (
      <>
        <Button
          type="button"
          size="small"
          variant="outline"
          disabled={busy}
          onClick={() => onAction(item, "deactivate")}
        >
          Deactivate
        </Button>
        <Button
          type="button"
          size="small"
          variant="danger"
          disabled={busy}
          onClick={() => onAction(item, "delete")}
        >
          Delete
        </Button>
      </>
    );
  }
  if (status === "inactive") {
    return (
      <>
        <Button
          type="button"
          size="small"
          variant="success"
          disabled={busy}
          onClick={() => onAction(item, "activate")}
        >
          Activate
        </Button>
        <Button
          type="button"
          size="small"
          variant="outline"
          disabled={busy}
          onClick={() => onAction(item, "archive")}
        >
          Archive
        </Button>
        <Button
          type="button"
          size="small"
          variant="danger"
          disabled={busy}
          onClick={() => onAction(item, "delete")}
        >
          Delete
        </Button>
      </>
    );
  }
  return (
    <>
      <Button
        type="button"
        size="small"
        variant="outline"
        disabled={busy}
        onClick={() => onAction(item, "restore")}
      >
        Restore
      </Button>
      <Button
        type="button"
        size="small"
        variant="danger"
        disabled={busy}
        onClick={() => onAction(item, "delete")}
      >
        Delete
      </Button>
    </>
  );
}

export default SubjectsWorkspace;
