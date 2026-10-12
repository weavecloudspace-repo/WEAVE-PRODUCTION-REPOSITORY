import { beginAcademicSubmission, endAcademicSubmission, finishAcademicCreation } from "./academicSubmission";
import { Tags } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import Button from "../../components/ui/Button";
import { useToast } from "../../hooks/useToast";
import { armLabelService } from "../../services/academicsService";
import { getErrorMessage } from "../../services/api";
import {
  FormActions,
  Input,
  RecordList,
  WorkspaceGrid,
  WorkspacePanel,
} from "./AcademicWorkspacePrimitives";
import TypedConfirmationDialog from "./TypedConfirmationDialog";

const asItems = (value) => (Array.isArray(value) ? value : value?.items || []);
const lifecycleStatus = (item) =>
  item.archived_at ? "archived" : item.is_active ? "active" : "inactive";

function ArmLabelsWorkspace({ activeTab = "overview" }) {
  const { showError, showSuccess } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [armLabels, setArmLabels] = useState([]);
  const [label, setLabel] = useState("");
  const [editing, setEditing] = useState(null);
  const [pendingAction, setPendingAction] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      setArmLabels(asItems(await armLabelService.getArmLabels({ includeArchived: true })));
    } catch (error) {
      setLoadError(getErrorMessage(error, "Could not load arm labels."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const visibleLabels = useMemo(
    () =>
      ["active", "inactive", "archived"].includes(activeTab)
        ? armLabels.filter((row) => lifecycleStatus(row) === activeTab)
        : armLabels,
    [activeTab, armLabels],
  );

  const selectView = (view) => {
    const next = new URLSearchParams(searchParams);
    if (view === "create") next.set("returnView", activeTab === "create" ? "overview" : activeTab);
    else next.delete("returnView");
    next.set("view", view);
    next.delete("tab");
    setSearchParams(next, { replace: true });
  };

  const closeEditor = () => {
    setEditing(null);
    setLabel("");
    selectView(searchParams.get("returnView") || (activeTab === "create" ? "overview" : activeTab));
  };

  const save = async (event) => {
    event.preventDefault();
    if (!label.trim()) return;
    const submission = beginAcademicSubmission(event, Boolean(saving));
    if (!submission) return;
    setSaving(true);
    try {
      if (editing) await armLabelService.updateArmLabel(editing.id, { label: label.trim() });
      else await armLabelService.createArmLabel({ label: label.trim() });
      showSuccess(editing ? "Arm label updated." : "Arm label created.");
      finishAcademicCreation(submission, () => { setLabel(""); }, closeEditor, Boolean(editing));
      await load();
    } catch (error) {
      showError(getErrorMessage(error, "Could not save arm label."));
    } finally {
      endAcademicSubmission(submission);
      setSaving(false);
    }
  };

  const runLifecycle = async () => {
    if (!pendingAction) return;
    const { item, action } = pendingAction;
    setSaving(item.id);
    try {
      if (action === "activate") await armLabelService.activateArmLabel(item.id);
      if (action === "deactivate") await armLabelService.deactivateArmLabel(item.id);
      if (action === "archive") await armLabelService.archiveArmLabel(item.id);
      if (action === "restore") await armLabelService.restoreArmLabel(item.id);
      if (action === "delete") await armLabelService.deleteArmLabel(item.id);
      showSuccess(action === "delete" ? "Arm label permanently deleted." : `Arm label ${action}d.`);
      setPendingAction(null);
      await load();
    } catch (error) {
      showError(getErrorMessage(error, `Could not ${action} this arm label.`));
    } finally {
      setSaving(false);
    }
  };

  const actionConfig = pendingAction
    ? {
        activate: ["Activate arm label", "ACTIVATE_ARM_LABEL", "Activate"],
        deactivate: ["Deactivate arm label", "DEACTIVATE_ARM_LABEL", "Deactivate"],
        archive: ["Archive arm label", "ARCHIVE_ARM_LABEL", "Archive"],
        restore: ["Restore arm label", "RESTORE_ARM_LABEL", "Restore"],
        delete: ["Permanently delete arm label", "DELETE_ARM_LABEL", "Delete permanently"],
      }[pendingAction.action]
    : null;
  const showEditor = activeTab === "create" || Boolean(editing);

  return (
    <>
      <WorkspaceGrid
        editor={
          showEditor ? (
            <WorkspacePanel
              title={editing ? "Edit arm label" : "Add arm label"}
              onBack={closeEditor}
              backDisabled={Boolean(saving)}
              description="Create one reusable label that can be used across many levels."
            >
              <form className="space-y-3" onSubmit={save}>
                <fieldset disabled={Boolean(saving)} className="space-y-3">
                  <Input
                    label="Arm label"
                    value={label}
                    onChange={(event) => setLabel(event.target.value)}
                    placeholder="A"
                    required
                  />
                  <FormActions
                    submitting={Boolean(saving)}
                    submitLabel={editing ? "Save label" : "Add arm label"}
                    repeatable
                    editing={Boolean(editing)}
                    onCancel={closeEditor}
                  />
                </fieldset>
              </form>
            </WorkspacePanel>
          ) : null
        }
        content={
            <RecordList
              loading={loading}
              error={loadError}
              onRetry={load}
              title="Arm labels"
              description="Reusable class labels with explicit active, inactive, and archived states."
              actions={
                !showEditor ? (
                  <Button type="button" onClick={() => selectView("create")}>
                    Add arm label
                  </Button>
                ) : null
              }
              items={visibleLabels}
              emptyIcon={Tags}
              emptyTitle="No arm labels"
              emptyDescription="Add a label such as A, B, Science, or Arts."
              renderTitle={(item) => item.label}
              renderMeta={() => "Reusable across academic levels"}
              renderDescription={() =>
                "A label identifies a class arm; it does not own curriculum or progression rules."
              }
              renderStatus={lifecycleStatus}
              showInspector={!showEditor}
              onEdit={(item) => {
                setEditing(item);
                setLabel(item.label);
              }}
              canEdit={(item) => !item.archived_at}
              renderActions={(item) => {
                const status = lifecycleStatus(item);
                return (
                  <>
                    {status === "active" ? (
                      <Button
                        size="small"
                        variant="outline"
                        onClick={() => setPendingAction({ item, action: "deactivate" })}
                      >
                        Deactivate
                      </Button>
                    ) : null}
                    {status === "inactive" ? (
                      <Button
                        size="small"
                        variant="outline"
                        onClick={() => setPendingAction({ item, action: "activate" })}
                      >
                        Activate
                      </Button>
                    ) : null}
                    {status === "inactive" ? (
                      <Button
                        size="small"
                        variant="outline"
                        onClick={() => setPendingAction({ item, action: "archive" })}
                      >
                        Archive
                      </Button>
                    ) : null}
                    {status === "archived" ? (
                      <Button
                        size="small"
                        variant="outline"
                        onClick={() => setPendingAction({ item, action: "restore" })}
                      >
                        Restore
                      </Button>
                    ) : null}
                    {["inactive", "archived"].includes(status) ? (
                      <Button
                        size="small"
                        variant="danger"
                        onClick={() => setPendingAction({ item, action: "delete" })}
                      >
                        Delete permanently
                      </Button>
                    ) : null}
                  </>
                );
              }}
            />
        }
      />
      <TypedConfirmationDialog
        open={Boolean(pendingAction)}
        title={actionConfig?.[0]}
        description={
          pendingAction?.action === "delete"
            ? `${pendingAction?.item?.label || "This label"} will be permanently removed only if no classroom has ever referenced it. Used labels are rejected by the backend and must remain as history.`
            : `${pendingAction?.item?.label || "This label"} will move through the supported arm-label lifecycle. Classes using it are protected by backend dependency checks.`
        }
        confirmationText={actionConfig?.[1] || ""}
        confirmLabel={actionConfig?.[2]}
        variant={["deactivate", "archive", "delete"].includes(pendingAction?.action) ? "danger" : "primary"}
        isLoading={saving === pendingAction?.item?.id}
        onConfirm={runLifecycle}
        onCancel={() => setPendingAction(null)}
      />
    </>
  );
}

export default ArmLabelsWorkspace;
