import ClassSpecializationWorkspace from "./ClassSpecializationWorkspace";
import { beginAcademicSubmission, endAcademicSubmission, finishAcademicCreation } from "./academicSubmission";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import Button from "../../components/ui/Button";
import { useToast } from "../../hooks/useToast";
import { academicLevelService } from "../../services/academicsService";
import { getErrorMessage } from "../../services/api";
import { departmentService } from "../../services/departmentService";
import {
  FormActions,
  Input,
  SelectControl,
  WorkspaceGrid,
  WorkspacePanel,
} from "./AcademicWorkspacePrimitives";
import { levelSupportsSpecialization } from "./academicDepartmentCapability";
import TypedConfirmationDialog from "./TypedConfirmationDialog";

const items = (value) => (Array.isArray(value) ? value : value?.items || []);
const lifecycleStatus = (row) =>
  row.archived_at ? "archived" : row.is_active ? "active" : "inactive";
const normalizeName = (value) =>
  String(value || "")
    .trim()
    .replace(/\s+/g, " ")
    .toLocaleLowerCase();

export default function DepartmentsWorkspace({ activeTab = "pool", setupTermId }) {
  const { showError, showSuccess } = useToast();
  const [levels, setLevels] = useState([]);
  const [categories, setCategories] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [levelDepartmentsByLevel, setLevelDepartmentsByLevel] = useState({});
  const [levelId, setLevelId] = useState("");

  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [name, setName] = useState("");
  const [attachDepartmentId, setAttachDepartmentId] = useState("");

  const [pendingAction, setPendingAction] = useState(null);
  const [saving, setSaving] = useState("");
  const [loadErrors, setLoadErrors] = useState({});
  const [loadStatus, setLoadStatus] = useState({ pool: true, base: true, availability: true });

  const [searchParams, setSearchParams] = useSearchParams();
  const closeEditor = () => {
    if (saving) return;
    setEditorOpen(false);
    setEditing(null);
    setName("");
  };
  const returnToPool = () => {
    if (saving) return;
    const next = new URLSearchParams(searchParams);
    next.set("view", "pool");
    next.delete("tab");
    setSearchParams(next, { replace: true });
  };

  const loadPool = useCallback(async () => {
    setLoadStatus((current) => ({ ...current, pool: true }));
    setLoadErrors((current) => ({ ...current, pool: "" }));
    try {
      setDepartments(
        items(await departmentService.getDepartments({ includeArchived: true })),
      );
    } catch (error) {
      setLoadErrors((current) => ({ ...current, pool: getErrorMessage(error, "Could not load the department pool.") }));
    } finally {
      setLoadStatus((current) => ({ ...current, pool: false }));
    }
  }, []);

  const loadBase = useCallback(async () => {
    setLoadStatus((current) => ({ ...current, base: true }));
    setLoadErrors((current) => ({ ...current, base: "" }));
    try {
      const [levelResponse, categoryResponse] =
        await Promise.all([
          academicLevelService.getLevels({ activeOnly: true }),
          academicLevelService.getCategories(),
        ]);
      setLevels(items(levelResponse));
      setCategories(items(categoryResponse));
    } catch (error) {
      setLoadErrors((current) => ({ ...current, base: getErrorMessage(error, "Could not load department setup.") }));
    } finally {
      setLoadStatus((current) => ({ ...current, base: false }));
    }
  }, []);

  const eligibleLevels = useMemo(() => {
    const allowed = new Set(
      categories.filter((row) => row.supports_departments).map((row) => row.value),
    );
    return levels.filter(
      (row) => allowed.has(row.category) && levelSupportsSpecialization(row),
    );
  }, [categories, levels]);

  const levelDepartments = useMemo(
    () => (levelId ? levelDepartmentsByLevel[String(levelId)] || [] : []),
    [levelDepartmentsByLevel, levelId],
  );

  const loadLevelDepartments = useCallback(async () => {
    setLoadErrors((current) => ({ ...current, availability: "" }));
    if (!eligibleLevels.length) {
      setLevelDepartmentsByLevel({});
      setLoadStatus((current) => ({ ...current, availability: false }));
      return;
    }
    setLoadStatus((current) => ({ ...current, availability: true }));
    try {
      const rows = items(await departmentService.getLevelAvailability());
      const grouped = {};
      rows.forEach((row) => { (grouped[String(row.academic_level_id)] ||= []).push(row); });
      setLevelDepartmentsByLevel(grouped);
    } catch (error) {
      setLoadErrors((current) => ({ ...current, availability: getErrorMessage(error, "Could not load level department availability.") }));
    } finally {
      setLoadStatus((current) => ({ ...current, availability: false }));
    }
  }, [eligibleLevels]);

  useEffect(() => {
    loadBase();
    loadPool();
  }, [loadBase, loadPool]);

  useEffect(() => {
    if (!eligibleLevels.some((row) => row.id === levelId)) {
      setLevelId(eligibleLevels[0]?.id || "");
    }
  }, [eligibleLevels, levelId]);

  useEffect(() => {
    loadLevelDepartments();
  }, [loadLevelDepartments]);

  useEffect(() => {
    setEditorOpen(activeTab === "create");
    setEditing(null);
    setName("");
    setAttachDepartmentId("");
  }, [activeTab]);

  const exactDuplicate = useMemo(() => {
    const candidate = normalizeName(name);
    if (!candidate) return null;
    return (
      departments.find(
        (row) => row.id !== editing?.id && normalizeName(row.name) === candidate,
      ) || null
    );
  }, [departments, editing?.id, name]);

  const attachedCanonicalIds = useMemo(
    () => new Set(levelDepartments.map((row) => row.department_id)),
    [levelDepartments],
  );
  const attachableDepartments = useMemo(
    () =>
      departments.filter(
        (row) =>
          lifecycleStatus(row) === "active" && !attachedCanonicalIds.has(row.id),
      ),
    [attachedCanonicalIds, departments],
  );
  const saveDepartment = async (event) => {
    event.preventDefault();
    if (!name.trim() || exactDuplicate) return;
    const submission = beginAcademicSubmission(event, Boolean(saving));
    if (!submission) return;
    setSaving("department");
    try {
      if (editing) {
        await departmentService.updateDepartment(editing.id, { name: name.trim() });
        showSuccess("Department updated across its level mappings.");
      } else {
        await departmentService.createDepartment({ name: name.trim() });
        showSuccess("Department added to the school-wide pool.");
      }
      setEditing(null);
      setName("");
      finishAcademicCreation(submission, () => setName(""), () => setEditorOpen(false), Boolean(editing));
      await loadPool();
      await loadLevelDepartments();
    } catch (error) {
      showError(getErrorMessage(error, "Could not save department."));
    } finally {
      endAcademicSubmission(submission);
      setSaving("");
    }
  };

  const attachToLevel = async (event) => {
    event.preventDefault();
    if (!levelId || !attachDepartmentId) return;
    const submission = beginAcademicSubmission(event, Boolean(saving));
    if (!submission) return;
    setSaving("attach");
    try {
      await departmentService.attachDepartment(levelId, attachDepartmentId);
      setAttachDepartmentId("");
      await loadLevelDepartments();
      showSuccess("Department made available to this academic level.");
    } catch (error) {
      showError(getErrorMessage(error, "Could not attach department to this level."));
    } finally {
      endAcademicSubmission(submission);
      setSaving("");
    }
  };

  const runLifecycle = async () => {
    if (!pendingAction || saving) return;
    const { scope, item, action, academicLevelId } = pendingAction;
    setSaving(item.id);
    try {
      if (scope === "pool") {
        if (action === "activate") await departmentService.activateDepartment(item.id);
        if (action === "deactivate") await departmentService.deactivateDepartment(item.id);
        if (action === "archive") await departmentService.archiveDepartment(item.id);
        if (action === "restore") await departmentService.restoreDepartment(item.id);
        if (action === "delete") await departmentService.deleteDepartment(item.id);
        await loadPool();
        await loadLevelDepartments();
      } else {
        if (action === "activate")
          await departmentService.activateLevelDepartment(academicLevelId, item.id);
        if (action === "deactivate")
          await departmentService.deactivateLevelDepartment(academicLevelId, item.id);
        if (action === "archive")
          await departmentService.archiveLevelDepartment(academicLevelId, item.id);
        if (action === "restore")
          await departmentService.restoreLevelDepartment(academicLevelId, item.id);
        if (action === "delete")
          await departmentService.deleteLevelDepartment(academicLevelId, item.id);
        await loadLevelDepartments();
      }
      showSuccess(action === "delete" ? "Record permanently deleted." : `Department ${action}d.`);
      setPendingAction(null);
    } catch (error) {
      showError(getErrorMessage(error, `Could not ${action} this department.`));
    } finally {
      setSaving("");
    }
  };

  const poolActionConfig = {
    activate: ["Activate department", "ACTIVATE_DEPARTMENT", "Activate"],
    deactivate: ["Deactivate department", "DEACTIVATE_DEPARTMENT", "Deactivate"],
    archive: ["Archive department", "ARCHIVE_DEPARTMENT", "Archive"],
    restore: ["Restore department", "RESTORE_DEPARTMENT", "Restore"],
    delete: ["Permanently delete department", "DELETE_DEPARTMENT", "Delete permanently"],
  };
  const levelActionConfig = {
    activate: ["Activate level availability", "ACTIVATE_LEVEL_DEPARTMENT", "Activate"],
    deactivate: ["Deactivate level availability", "DEACTIVATE_LEVEL_DEPARTMENT", "Deactivate"],
    archive: ["Archive level availability", "ARCHIVE_LEVEL_DEPARTMENT", "Archive"],
    restore: ["Restore level availability", "RESTORE_LEVEL_DEPARTMENT", "Restore"],
    delete: ["Remove level availability", "DELETE_LEVEL_DEPARTMENT", "Delete permanently"],
  };
  const actionConfig = pendingAction
    ? (pendingAction.scope === "pool" ? poolActionConfig : levelActionConfig)[
        pendingAction.action
      ]
    : null;

  const lifecycleButtons = (row, scope, academicLevelId = null) => {
    const state = lifecycleStatus(row);
    const queueAction = (action) =>
      setPendingAction({ scope, item: row, action, academicLevelId });

    return (
      <>
        {state === "active" ? (
          <Button
            size="small"
            variant="outline"
            onClick={() => queueAction("deactivate")}
          >
            Deactivate
          </Button>
        ) : null}
        {state === "inactive" ? (
          <Button
            size="small"
            variant="outline"
            onClick={() => queueAction("activate")}
          >
            Activate
          </Button>
        ) : null}
        {state === "inactive" ? (
          <Button
            size="small"
            variant="outline"
            onClick={() => queueAction("archive")}
          >
            Archive
          </Button>
        ) : null}
        {state === "archived" ? (
          <Button
            size="small"
            variant="outline"
            onClick={() => queueAction("restore")}
          >
            Restore
          </Button>
        ) : null}
        {["inactive", "archived"].includes(state) ? (
          <Button
            size="small"
            variant="danger"
            onClick={() => queueAction("delete")}
          >
            Delete permanently
          </Button>
        ) : null}
      </>
    );
  };

  const loading = Object.values(loadStatus).some(Boolean);
  const loadError = Object.values(loadErrors).filter(Boolean).join(" ");
  const retryLoading = () => Promise.all([loadBase(), loadPool(), loadLevelDepartments()]);
  const loadFeedback = loadError ? (
    <div role="alert" className="space-y-2 text-sm text-error">
      <p>{loadError}</p>
      <Button type="button" variant="outline" onClick={retryLoading}>Retry loading departments</Button>
    </div>
  ) : loading ? <p role="status">Loading departments and level availability...</p> : null;

  if (activeTab === "availability") {
    return (
      <WorkspaceGrid
        editor={
          <WorkspacePanel
            title="Make a department available"
            onBack={setupTermId ? undefined : returnToPool}
            backDisabled={Boolean(saving)}
            description="Choose a school-wide department and the level where it will be available."
          >
            <form className="space-y-3" onSubmit={attachToLevel}>
              <fieldset disabled={Boolean(saving) || loading || Boolean(loadError)} className="space-y-3">
                <SelectControl
                  label="Academic level"
                  value={levelId}
                  onChange={setLevelId}
                  options={eligibleLevels.map((row) => ({ value: row.id, label: row.name }))}
                  required
                />
                <SelectControl
                  label="Department"
                  value={attachDepartmentId}
                  onChange={setAttachDepartmentId}
                  options={attachableDepartments.map((row) => ({
                    value: row.id,
                    label: row.name,
                  }))}
                  placeholder={
                    attachableDepartments.length
                      ? "Select department from pool"
                      : "All active departments are already attached"
                  }
                  required
                />
                <Button
                  type="submit"
                  disabled={saving === "attach" || !levelId || !attachDepartmentId}
                >
                  {saving === "attach" ? "Saving…" : "Make available"}
                </Button>
              </fieldset>
            </form>
          </WorkspacePanel>
        }
        content={<div className="space-y-4">
          {loadFeedback}
          <WorkspacePanel title="Department availability by level" description="Select a cell to add availability. Use the lifecycle actions below to deactivate or restore existing availability safely.">
            <div className="overflow-x-auto"><table className="w-full text-left text-sm">
              <thead><tr><th className="p-3">Level</th>{departments.filter((row) => lifecycleStatus(row) === "active").map((row) => <th className="p-3" key={row.id}>{row.name}</th>)}</tr></thead>
              <tbody>{eligibleLevels.map((level) => <tr key={level.id} className="border-t border-border"><th className="p-3">{level.name}</th>{departments.filter((row) => lifecycleStatus(row) === "active").map((department) => {
                const link = (levelDepartmentsByLevel[String(level.id)] || []).find((row) => row.department_id === department.id);
                return <td className="p-3" key={department.id}><Button type="button" size="small" variant="outline" disabled={Boolean(saving) || loading || Boolean(loadError)} aria-label={`${level.name}: ${department.name}, ${link ? lifecycleStatus(link) : "not available"}`} onClick={async () => {
                  if (saving) return;
                  if (link) { setLevelId(level.id); setPendingAction({ scope: "level", item: link, action: link.archived_at ? "restore" : link.is_active ? "deactivate" : "activate", academicLevelId: level.id }); return; }
                  setSaving("matrix");
                  try { await departmentService.attachDepartment(level.id, department.id); await loadLevelDepartments(); showSuccess(`${department.name} is available in ${level.name}.`); }
                  catch (error) { showError(getErrorMessage(error, "Could not update availability.")); }
                  finally { setSaving(""); }
                }}>{link ? lifecycleStatus(link) === "active" ? "Available" : lifecycleStatus(link) : "Add"}</Button></td>;
              })}</tr>)}</tbody>
            </table></div>
          </WorkspacePanel>
          <TypedConfirmationDialog open={Boolean(pendingAction)} title={actionConfig?.[0]} description="Existing curriculum and term references are protected. Resolve any blockers before changing availability." confirmationText={actionConfig?.[1] || ""} confirmLabel={actionConfig?.[2]} isLoading={Boolean(saving)} onConfirm={runLifecycle} onCancel={() => setPendingAction(null)} />
        </div>}
      />
    );
  }

  if (activeTab === "placements") {
    return <div className="space-y-4">{loadFeedback}<ClassSpecializationWorkspace levels={eligibleLevels} availability={levelDepartmentsByLevel} setupTermId={setupTermId} /></div>;
  }

  return (
    <>
      <WorkspaceGrid
        editor={
          editorOpen ? (
            <WorkspacePanel
              title={editing ? "Edit department" : "Add department to pool"}
              onBack={closeEditor}
              backDisabled={Boolean(saving)}
              description="Department names are school-wide. Level availability is configured separately."
            >
              <form className="space-y-3" onSubmit={saveDepartment}>
                <fieldset disabled={Boolean(saving) || loading || Boolean(loadError)} className="space-y-3">
                  <Input
                    label="Department name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="Science"
                    required
                  />
                  {exactDuplicate ? (
                    <p className="rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">
                      {exactDuplicate.name} already exists in the department pool.
                    </p>
                  ) : null}
                  <FormActions repeatable editing={Boolean(editing)} submitting={Boolean(saving)} disabled={!name.trim() || Boolean(exactDuplicate)} onCancel={closeEditor} />
                </fieldset>
              </form>
            </WorkspacePanel>
          ) : null
        }
        content={
          <WorkspacePanel
            title="Department catalog"
            description="Create each specialization once for the school, then make it available only to levels that actually specialize."
            actions={
              !editorOpen ? (
                <Button
                  type="button"
                  onClick={() => {
                    setEditing(null);
                    setName("");
                    setEditorOpen(true);
                  }}
                >
                  Add department
                </Button>
              ) : null
            }
          >
            {loadFeedback}
            {!loading && !loadError && departments.length === 0 ? (
              <p className="text-sm text-text-muted">
                No departments yet. Create the first school-wide specialization.
              </p>
            ) : null}
            {departments.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="p-3">Department</th>
                      <th className="p-3">Available in</th>
                      <th className="p-3">Status</th>
                      <th className="p-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {departments.map((row) => {
                      const availableIn = eligibleLevels
                        .filter((level) =>
                          (levelDepartmentsByLevel[String(level.id)] || []).some(
                            (link) =>
                              link.department_id === row.id &&
                              link.is_active &&
                              !link.archived_at,
                          ),
                        )
                        .map((level) => level.name);
                      const status = lifecycleStatus(row);
                      return (
                        <tr key={row.id} className="border-b border-border/70 last:border-b-0">
                          <td className="p-3 font-semibold text-text">{row.name}</td>
                          <td className="p-3 text-text-muted">
                            {availableIn.length ? availableIn.join(", ") : "No specialization levels"}
                          </td>
                          <td className="p-3 capitalize text-text-muted">{status}</td>
                          <td className="p-3">
                            <div className="flex flex-wrap justify-end gap-2">
                              {!row.archived_at ? (
                                <Button
                                  type="button"
                                  size="small"
                                  variant="outline"
                                  onClick={() => {
                                    setEditing(row);
                                    setName(row.name);
                                    setEditorOpen(true);
                                  }}
                                >
                                  Edit
                                </Button>
                              ) : null}
                              {lifecycleButtons(row, "pool")}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}
          </WorkspacePanel>
        }
      />
      <TypedConfirmationDialog
        open={Boolean(pendingAction)}
        title={actionConfig?.[0]}
        description={
          pendingAction?.scope === "pool"
            ? "Canonical department lifecycle changes apply everywhere this department is mapped. Active level mappings and historical usage remain protected by backend dependency checks."
            : "This changes availability only for this academic level. Term placements and curriculum applicability remain protected by backend dependency checks."
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
