import { GraduationCap, ShieldCheck, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import { useToast } from "../../hooks/useToast";
import { academicService } from "../../services/academicService";
import { getErrorMessage } from "../../services/api";
import { Input, WorkspacePanel } from "./AcademicWorkspacePrimitives";
import TypedConfirmationDialog from "./TypedConfirmationDialog";

const BLANK_SCALE = {
  grade: "",
  min_score: "",
  max_score: "",
  remark: "",
};

const asItems = (response) =>
  Array.isArray(response)
    ? response
    : Array.isArray(response?.items)
      ? response.items
      : [];

function GradingScalesWorkspace({ activeTab }) {
  const [scales, setScales] = useState([]);
  const [readiness, setReadiness] = useState(null);
  const [form, setForm] = useState(BLANK_SCALE);
  const [editingId, setEditingId] = useState("");
  const [pendingAction, setPendingAction] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState("");
  const { showSuccess, showError, showWarning } = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [scaleResponse, readinessResponse] = await Promise.all([
        academicService.listGradingScales({ limit: 100 }),
        academicService.getGradingReadiness(),
      ]);
      setScales(asItems(scaleResponse));
      setReadiness(readinessResponse);
    } catch (error) {
      showError(getErrorMessage(error, "Could not load grading configuration."));
    } finally {
      setLoading(false);
    }
  }, [showError]);

  useEffect(() => {
    load();
  }, [load]);

  const visibleScales = useMemo(() => {
    if (activeTab === "active") return scales.filter((item) => item.is_active);
    if (activeTab === "inactive") return scales.filter((item) => !item.is_active);
    return scales;
  }, [activeTab, scales]);

  const resetForm = () => {
    setForm(BLANK_SCALE);
    setEditingId("");
  };

  const [searchParams, setSearchParams] = useSearchParams();
  const closeEditor = () => {
    if (saving) return;
    resetForm();
    if (activeTab === "create") {
      const next = new URLSearchParams(searchParams);
      next.set("view", searchParams.get("returnView") || "overview");
      next.delete("tab");
      next.delete("returnView");
      setSearchParams(next, { replace: true });
    }
  };

  const saveScale = async (event) => {
    event.preventDefault();
    const minimum = Number(form.min_score);
    const maximum = Number(form.max_score);
    if (!form.grade.trim()) return showWarning("Enter a grade label.");
    if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) {
      return showWarning("Enter valid score boundaries.");
    }
    if (minimum < 0 || maximum > 100 || minimum > maximum) {
      return showWarning("Score boundaries must remain between 0 and 100.");
    }

    setSaving("form");
    try {
      const payload = {
        grade: form.grade.trim(),
        min_score: minimum,
        max_score: maximum,
        remark: form.remark.trim() || null,
        ...(editingId ? {} : { is_active: false }),
      };
      if (editingId) {
        await academicService.updateGradingScale(editingId, payload);
        showSuccess("Grading scale updated.");
      } else {
        await academicService.createGradingScale(payload);
        showSuccess("Grading scale created as inactive. Activate it after reviewing readiness.");
      }
      resetForm();
      await load();
    } catch (error) {
      showError(getErrorMessage(error, "Could not save grading scale."));
    } finally {
      setSaving("");
    }
  };

  const requestAction = async (item, action) => {
    if (action === "delete") {
      setSaving(item.id);
      try {
        const preview = await academicService.getGradingScaleDependencies(item.id);
        if (!preview?.can_delete) {
          const message = (preview?.blocker_messages || []).join(" ") || "This grading scale cannot be deleted.";
          showWarning(message);
          return;
        }
        setPendingAction({ item, action, preview });
      } catch (error) {
        showError(getErrorMessage(error, "Could not inspect grading-scale dependencies."));
      } finally {
        setSaving("");
      }
      return;
    }
    setPendingAction({ item, action });
  };

  const executeAction = async () => {
    if (!pendingAction) return;
    const { item, action } = pendingAction;
    setSaving(item.id);
    try {
      if (action === "activate") {
        await academicService.activateGradingScale(item.id);
        showSuccess(`${item.grade} grading scale activated.`);
      } else if (action === "deactivate") {
        await academicService.deactivateGradingScale(item.id);
        showSuccess(`${item.grade} grading scale made inactive.`);
      } else if (action === "delete") {
        await academicService.deleteGradingScale(item.id);
        showSuccess(`${item.grade} grading scale deleted.`);
      }
      setPendingAction(null);
      await load();
    } catch (error) {
      showError(getErrorMessage(error, `Could not ${action} grading scale.`));
    } finally {
      setSaving("");
    }
  };

  const actionCopy = pendingAction
    ? {
        activate: {
          title: "Activate grading scale",
          description: `Activate ${pendingAction.item.grade} (${pendingAction.item.min_score}–${pendingAction.item.max_score})? The active scale set must remain complete and non-overlapping.`,
          confirmationText: "ACTIVATE_GRADING_SCALE",
          confirmLabel: "Activate scale",
          variant: "success",
        },
        deactivate: {
          title: "Make grading scale inactive",
          description: `Make ${pendingAction.item.grade} inactive? New results will no longer use this grade boundary. Existing historical results keep their stored grade and scale reference.`,
          confirmationText: "DEACTIVATE_GRADING_SCALE",
          confirmLabel: "Make inactive",
          variant: "danger",
        },
        delete: {
          title: "Delete inactive grading scale",
          description: `Permanently delete ${pendingAction.item.grade}? This is allowed only because the scale is inactive and has no result references.`,
          confirmationText: "DELETE_GRADING_SCALE",
          confirmLabel: "Delete scale",
          variant: "danger",
        },
      }[pendingAction.action]
    : null;

  if (activeTab === "create" || editingId) {
    return (
      <WorkspacePanel
        title={editingId ? "Edit inactive grading scale" : "Create grading scale"}
        onBack={closeEditor}
        backDisabled={Boolean(saving)}
        description="New grading scales are created inactive. Review the full range set before activation."
      >
        <form className="space-y-4" onSubmit={saveScale}>
          <Input
            label="Grade"
            value={form.grade}
            onChange={(event) => setForm((current) => ({ ...current, grade: event.target.value }))}
            placeholder="A"
            required
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              label="Minimum score"
              type="number"
              min="0"
              max="100"
              step="0.01"
              value={form.min_score}
              onChange={(event) => setForm((current) => ({ ...current, min_score: event.target.value }))}
              required
            />
            <Input
              label="Maximum score"
              type="number"
              min="0"
              max="100"
              step="0.01"
              value={form.max_score}
              onChange={(event) => setForm((current) => ({ ...current, max_score: event.target.value }))}
              required
            />
          </div>
          <Input
            label="Remark"
            value={form.remark}
            onChange={(event) => setForm((current) => ({ ...current, remark: event.target.value }))}
            placeholder="Excellent"
          />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={saving === "form"}>
              {saving === "form" ? "Saving..." : editingId ? "Update scale" : "Create inactive scale"}
            </Button>
            {editingId ? (
              <Button type="button" variant="outline" onClick={closeEditor} disabled={saving === "form"}>
                Cancel
              </Button>
            ) : null}
          </div>
        </form>
      </WorkspacePanel>
    );
  }

  return (
    <div className="space-y-4">
      {activeTab === "overview" ? (
        <WorkspacePanel
          title="Grading readiness"
          description="Active grading rules must cover the full 0–100 range without gaps or overlaps."
        >
          <div className={`rounded-xl border px-4 py-3 text-sm ${readiness?.is_ready ? "border-success/30 bg-success/5 text-success" : "border-warning/30 bg-warning/5 text-warning"}`}>
            <div className="flex items-center gap-2 font-semibold">
              <ShieldCheck className="h-4 w-4" />
              {readiness?.is_ready ? "Grading configuration is ready" : "Grading configuration needs attention"}
            </div>
            {(readiness?.messages || []).map((message) => (
              <p className="mt-2" key={message}>{message}</p>
            ))}
          </div>
        </WorkspacePanel>
      ) : null}

      <WorkspacePanel
        title={`${activeTab === "inactive" ? "Inactive" : activeTab === "active" ? "Active" : "All"} grading scales`}
        description="Activate, make inactive, edit, or safely delete grading rules according to their lifecycle state."
      >
        {loading ? (
          <p className="text-sm text-text-muted">Loading grading scales...</p>
        ) : visibleScales.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-border p-6 text-center">
            <GraduationCap className="mx-auto h-7 w-7 text-text-muted" />
            <p className="mt-3 text-sm font-semibold text-text">No grading scales in this view</p>
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {visibleScales.map((item) => (
              <div key={item.id} className="rounded-2xl border border-border/70 bg-surface p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-lg font-semibold text-text">{item.grade}</p>
                    <p className="text-sm text-text-muted">{item.min_score} – {item.max_score}</p>
                  </div>
                  <Badge variant={item.is_active ? "success" : "default"}>
                    {item.is_active ? "active" : "inactive"}
                  </Badge>
                </div>
                <p className="mt-3 text-sm text-text-muted">{item.remark || "No remark"}</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {item.is_active ? (
                    <Button type="button" size="small" variant="outline" disabled={saving === item.id} onClick={() => requestAction(item, "deactivate")}>
                      Make inactive
                    </Button>
                  ) : (
                    <>
                      <Button type="button" size="small" variant="success" disabled={saving === item.id} onClick={() => requestAction(item, "activate")}>
                        Activate
                      </Button>
                      <Button
                        type="button"
                        size="small"
                        variant="outline"
                        disabled={saving === item.id}
                        onClick={() => {
                          setEditingId(item.id);
                          setForm({
                            grade: item.grade || "",
                            min_score: item.min_score ?? "",
                            max_score: item.max_score ?? "",
                            remark: item.remark || "",
                          });
                        }}
                      >
                        Edit
                      </Button>
                      <Button type="button" size="small" variant="danger" disabled={saving === item.id} onClick={() => requestAction(item, "delete")}>
                        <Trash2 className="h-4 w-4" />
                        Delete
                      </Button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </WorkspacePanel>

      <TypedConfirmationDialog
        open={Boolean(pendingAction)}
        title={actionCopy?.title || "Confirm grading-scale action"}
        description={actionCopy?.description || "Confirm this grading-scale lifecycle action."}
        confirmationText={actionCopy?.confirmationText || "CONFIRM"}
        confirmLabel={actionCopy?.confirmLabel || "Confirm"}
        variant={actionCopy?.variant || "danger"}
        isLoading={Boolean(pendingAction && saving === pendingAction.item.id)}
        onConfirm={executeAction}
        onCancel={() => setPendingAction(null)}
      />
    </div>
  );
}

export default GradingScalesWorkspace;
