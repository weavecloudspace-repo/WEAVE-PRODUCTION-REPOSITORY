import MultiSelect from "../../components/ui/MultiSelect";
import { createClassArms } from "./classArmBatch";
import {
  beginAcademicSubmission,
  endAcademicSubmission,
  finishAcademicCreation,
} from "./academicSubmission";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { displayClass } from "../../components/academic/academicDisplay";
import Button from "../../components/ui/Button";
import Modal from "../../components/ui/Modal";
import { useToast } from "../../hooks/useToast";
import { academicService } from "../../services/academicService";
import {
  academicLevelService,
  armLabelService,
  classService,
} from "../../services/academicsService";
import { getErrorMessage } from "../../services/api";
import { curriculumService } from "../../services/curriculumService";
import { departmentService } from "../../services/departmentService";
import { teacherService } from "../../services/teacherService";
import {
  FormActions,
  RecordList,
  SelectControl,
  WorkspaceGrid,
  WorkspacePanel,
} from "./AcademicWorkspacePrimitives";
import { isAssignableClassTeacher } from "./classTeacherEligibility";
import {
  currentOpenTerm,
  currentTermDepartmentRequirement,
  termLabel,
} from "./currentTermStructureIntegrity";

const asItems = (value) => (Array.isArray(value) ? value : value?.items || []);
const emptyClassForm = {
  academic_level_id: "",
  arm_label_id: "",
  teacher_membership_id: "",
  current_term_department_id: "",
};

const teacherLabel = (item) => {
  const account = item?.teacher_account || item?.account || {};
  return (
    [account.first_name, account.last_name].filter(Boolean).join(" ") ||
    account.email ||
    item.staff_id ||
    "Teacher"
  );
};

function ClassesWorkspace({ activeTab = "overview" }) {
  const { showError, showSuccess } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [levels, setLevels] = useState([]);
  const [classes, setClasses] = useState([]);
  const [armLabels, setArmLabels] = useState([]);
  const [teachers, setTeachers] = useState([]);
  const [currentTerm, setCurrentTerm] = useState(null);
  const [departmentAvailability, setDepartmentAvailability] = useState([]);
  const [classForm, setClassForm] = useState(emptyClassForm);
  const [selectedArms, setSelectedArms] = useState([]);
  const [editingClassId, setEditingClassId] = useState("");
  const [activationTarget, setActivationTarget] = useState(null);
  const [activationDepartmentId, setActivationDepartmentId] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const [
        levelRows,
        classRows,
        armLabelRows,
        teacherRows,
        termRows,
        departmentRows,
      ] = await Promise.all([
        academicLevelService.getLevels({ activeOnly: true }),
        classService.getClasses({ includeArchived: true }),
        armLabelService.getArmLabels({ includeArchived: true }),
        teacherService.getTeachers({ limit: 100 }),
        academicService.listTerms({ is_current: true, limit: 100 }),
        departmentService.getLevelAvailability(),
      ]);
      setLevels(asItems(levelRows));
      setClasses(asItems(classRows));
      setArmLabels(asItems(armLabelRows));
      setTeachers(asItems(teacherRows).filter(isAssignableClassTeacher));
      setCurrentTerm(currentOpenTerm(termRows));
      setDepartmentAvailability(asItems(departmentRows));
    } catch (error) {
      setLoadError(getErrorMessage(error, "Could not load class structure."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const levelOptions = useMemo(
    () => levels.map((item) => ({ value: item.id, label: item.name })),
    [levels],
  );
  const teacherOptions = useMemo(
    () => teachers.map((item) => ({ value: item.id, label: teacherLabel(item) })),
    [teachers],
  );
  const armLabelOptions = useMemo(
    () =>
      armLabels
        .filter((item) => item.is_active && !item.archived_at)
        .map((item) => ({ value: item.id, label: item.label })),
    [armLabels],
  );
  const selectedLevel = levels.find(
    (item) => String(item.id) === String(classForm.academic_level_id),
  );
  const editingClass = classes.find(
    (item) => String(item.id) === String(editingClassId),
  );
  const changingLevel = Boolean(
    editingClass &&
      String(editingClass.academic_level_id) !==
        String(classForm.academic_level_id),
  );
  const formSpecialization = currentTermDepartmentRequirement({
    level: selectedLevel,
    term: currentTerm,
    availability: departmentAvailability,
  });
  const formNeedsCurrentDepartment =
    formSpecialization.required && (!editingClassId || changingLevel);

  const selectView = (view) => {
    const next = new URLSearchParams(searchParams);
    if (view === "create")
      next.set(
        "returnView",
        activeTab === "create" ? "overview" : activeTab,
      );
    else next.delete("returnView");
    next.set("view", view);
    next.delete("tab");
    setSearchParams(next, { replace: true });
  };

  const closeEditor = () => {
    setSelectedArms([]);
    setEditingClassId("");
    setClassForm(emptyClassForm);
    selectView(
      searchParams.get("returnView") ||
        (activeTab === "create" ? "overview" : activeTab),
    );
  };

  const saveClass = async (event) => {
    event.preventDefault();
    const wasEditing = Boolean(editingClassId);
    if (!wasEditing && (!classForm.academic_level_id || !selectedArms.length)) {
      showError("Choose an academic level and at least one arm.");
      return;
    }
    if (formNeedsCurrentDepartment && formSpecialization.blocked) {
      showError(
        `${selectedLevel?.name || "This level"} requires specialization in ${termLabel(currentTerm)}, but it has no active departments yet. Configure departments for the level before making a class active.`,
      );
      return;
    }
    if (
      formNeedsCurrentDepartment &&
      !classForm.current_term_department_id
    ) {
      showError(`Choose a department for ${termLabel(currentTerm)} first.`);
      return;
    }

    const submission = beginAcademicSubmission(event, Boolean(saving));
    if (!submission) return;
    setSaving(true);
    try {
      const payload = {
        academic_level_id: classForm.academic_level_id,
        arm_label_id: classForm.arm_label_id,
        teacher_membership_id: classForm.teacher_membership_id || null,
        ...(formNeedsCurrentDepartment
          ? {
              current_term_department_id:
                classForm.current_term_department_id,
            }
          : {}),
      };
      if (wasEditing) {
        await classService.updateClass(editingClassId, payload);
      } else {
        const result = await createClassArms(
          classService.createClass,
          classForm.academic_level_id,
          selectedArms,
          formNeedsCurrentDepartment
            ? {
                current_term_department_id:
                  classForm.current_term_department_id,
              }
            : {},
        );
        setSelectedArms(result.failed.map((item) => item.armLabelId));
        if (result.failed.length) {
          showError(
            `${result.created.length} classes created; ${result.failed.length} could not be created. ${getErrorMessage(result.failed[0].error, "Review the selected arms and retry.")}`,
          );
          await load();
          return;
        }
      }
      showSuccess(
        wasEditing
          ? "Class arm updated."
          : `${selectedArms.length} classes created.`,
      );
      finishAcademicCreation(
        submission,
        () => {
          setClassForm((current) => ({
            ...emptyClassForm,
            academic_level_id: current.academic_level_id,
          }));
        },
        closeEditor,
        wasEditing,
      );
      await load();
    } catch (error) {
      showError(
        getErrorMessage(
          error,
          wasEditing
            ? "Could not update class arm."
            : "Could not create class arm.",
        ),
      );
    } finally {
      endAcademicSubmission(submission);
      setSaving(false);
    }
  };

  const activateClass = async (item) => {
    const level = levels.find(
      (row) => String(row.id) === String(item.academic_level_id),
    );
    const requirement = currentTermDepartmentRequirement({
      level,
      term: currentTerm,
      availability: departmentAvailability,
    });
    if (!requirement.required) {
      await classService.activateClass(item.id);
      return true;
    }
    if (requirement.blocked) {
      showError(
        `${level?.name || "This level"} requires specialization in ${termLabel(currentTerm)}, but no active departments are configured for the level. Configure departments first.`,
      );
      return false;
    }

    try {
      const existing = await curriculumService.getClassDepartment(
        item.id,
        currentTerm.id,
      );
      if (existing?.id) {
        await classService.activateClass(item.id);
        return true;
      }
    } catch {
      // Missing exact-term specialization is handled by the selection modal below.
    }

    setActivationTarget(item);
    setActivationDepartmentId("");
    return false;
  };

  const updateLifecycle = async (item, action) => {
    setSaving(item.id);
    try {
      if (action === "activate") {
        const activated = await activateClass(item);
        if (!activated) return;
      }
      if (action === "deactivate") await classService.deactivateClass(item.id);
      if (action === "archive") await classService.archiveClass(item.id);
      if (action === "restore") await classService.restoreClass(item.id);
      showSuccess(`Class ${action}d.`);
      await load();
    } catch (error) {
      showError(getErrorMessage(error, `Could not ${action} this class.`));
    } finally {
      setSaving(false);
    }
  };

  const confirmActivation = async () => {
    if (!activationTarget || !activationDepartmentId) return;
    setSaving(activationTarget.id);
    try {
      await classService.activateClass(
        activationTarget.id,
        activationDepartmentId,
      );
      showSuccess("Class activated with its current-term specialization.");
      setActivationTarget(null);
      setActivationDepartmentId("");
      await load();
    } catch (error) {
      showError(getErrorMessage(error, "Could not activate this class."));
    } finally {
      setSaving(false);
    }
  };

  const filteredClasses = classes.filter((item) => {
    if (activeTab === "active") return item.is_active && !item.archived_at;
    if (activeTab === "inactive") return !item.is_active && !item.archived_at;
    if (activeTab === "archived") return Boolean(item.archived_at);
    return true;
  });
  const showEditor = activeTab === "create" || Boolean(editingClassId);
  const activationLevel = levels.find(
    (item) =>
      String(item.id) === String(activationTarget?.academic_level_id || ""),
  );
  const activationRequirement = currentTermDepartmentRequirement({
    level: activationLevel,
    term: currentTerm,
    availability: departmentAvailability,
  });

  return (
    <>
      <WorkspaceGrid
        editor={
          showEditor ? (
            <WorkspacePanel
              title={editingClassId ? "Edit class" : "Create class"}
              onBack={closeEditor}
              backDisabled={Boolean(saving)}
              description={
                editingClassId
                  ? "Update this class and its teacher. If you move an active class into a level that specializes now, its current-term department is required."
                  : "Choose a level, then select all the arms you want to create. If the level specializes in the current term, Weave also requires the department now."
              }
            >
              <form className="space-y-3" onSubmit={saveClass}>
                <fieldset disabled={Boolean(saving)} className="space-y-3">
                  <SelectControl
                    label="Academic level"
                    value={classForm.academic_level_id}
                    onChange={(value) => {
                      setSelectedArms([]);
                      setClassForm((current) => ({
                        ...current,
                        academic_level_id: value,
                        current_term_department_id: "",
                      }));
                    }}
                    options={levelOptions}
                    required
                  />
                  {editingClassId ? (
                    <SelectControl
                      label="Arm"
                      value={classForm.arm_label_id}
                      onChange={(value) =>
                        setClassForm((current) => ({
                          ...current,
                          arm_label_id: value,
                        }))
                      }
                      options={armLabelOptions}
                      placeholder="Select arm"
                      required
                    />
                  ) : (
                    <MultiSelect
                      label="Arms"
                      value={selectedArms}
                      options={armLabelOptions.filter(
                        (option) =>
                          !classes.some(
                            (item) =>
                              item.academic_level_id ===
                                classForm.academic_level_id &&
                              item.arm_label_id === option.value,
                          ),
                      )}
                      onChange={(event) =>
                        setSelectedArms(event.target.value)
                      }
                      disabled={
                        !classForm.academic_level_id || Boolean(saving)
                      }
                      placeholder="Select arms to create"
                      searchPlaceholder="Search arms"
                      required
                    />
                  )}
                  {!editingClassId ? (
                    <p className="text-xs text-text-muted">
                      {selectedArms.length} arms selected. Existing class arms are
                      excluded, including archived classes.
                    </p>
                  ) : null}

                  {formNeedsCurrentDepartment && formSpecialization.blocked ? (
                    <div
                      role="alert"
                      className="rounded-2xl border border-warning/40 bg-warning/10 p-4 text-sm text-text"
                    >
                      <p className="font-semibold">
                        Departments must be configured first
                      </p>
                      <p className="mt-1 text-text-muted">
                        {selectedLevel?.name || "This level"} requires
                        specialization in {termLabel(currentTerm)}, but no active
                        departments are available for the level. Add level
                        departments before making a class active.
                      </p>
                    </div>
                  ) : null}
                  {formNeedsCurrentDepartment && !formSpecialization.blocked ? (
                    <SelectControl
                      label={`Department for ${termLabel(currentTerm)}`}
                      value={classForm.current_term_department_id}
                      onChange={(value) =>
                        setClassForm((current) => ({
                          ...current,
                          current_term_department_id: value,
                        }))
                      }
                      options={formSpecialization.options}
                      placeholder="Select current-term department"
                      required
                    />
                  ) : null}

                  {editingClassId ? (
                    <SelectControl
                      label="Class teacher"
                      value={classForm.teacher_membership_id}
                      onChange={(value) =>
                        setClassForm((current) => ({
                          ...current,
                          teacher_membership_id: value,
                        }))
                      }
                      options={teacherOptions}
                      clearable
                    />
                  ) : null}
                  <FormActions
                    submitting={Boolean(saving)}
                    submitLabel={
                      editingClassId
                        ? "Save class"
                        : `Create classes (${selectedArms.length})`
                    }
                    repeatable
                    editing={Boolean(editingClassId)}
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
            title="Classes"
            description="Concrete student groups within academic levels. Select a row to inspect it; lifecycle actions remain available directly from the directory."
            actions={
              !showEditor ? (
                <Button type="button" onClick={() => selectView("create")}>
                  Create class
                </Button>
              ) : null
            }
            items={filteredClasses}
            emptyTitle="No classes"
            emptyDescription="No classes match this lifecycle view."
            renderTitle={displayClass}
            renderMeta={(item) =>
              item.academic_level_name || "Academic level"
            }
            renderDescription={(item) =>
              item.teacher_membership_id
                ? "Class teacher assigned"
                : "No class teacher assigned"
            }
            renderStatus={(item) =>
              item.archived_at
                ? "archived"
                : item.is_active
                  ? "active"
                  : "inactive"
            }
            showInspector={!showEditor}
            onEdit={(item) => {
              setEditingClassId(item.id);
              setClassForm({
                academic_level_id: item.academic_level_id,
                arm_label_id: item.arm_label_id || "",
                teacher_membership_id: item.teacher_membership_id || "",
                current_term_department_id: "",
              });
            }}
            canEdit={(item) => !item.archived_at}
            renderActions={(item) => (
              <>
                {!item.archived_at && item.is_active ? (
                  <Button
                    size="small"
                    variant="outline"
                    disabled={saving === item.id}
                    onClick={() => updateLifecycle(item, "deactivate")}
                  >
                    Deactivate
                  </Button>
                ) : null}
                {!item.archived_at && !item.is_active ? (
                  <>
                    <Button
                      size="small"
                      variant="outline"
                      disabled={saving === item.id}
                      onClick={() => updateLifecycle(item, "activate")}
                    >
                      Activate
                    </Button>
                    <Button
                      size="small"
                      variant="outline"
                      disabled={saving === item.id}
                      onClick={() => updateLifecycle(item, "archive")}
                    >
                      Archive
                    </Button>
                  </>
                ) : null}
                {item.archived_at ? (
                  <Button
                    size="small"
                    variant="outline"
                    disabled={saving === item.id}
                    onClick={() => updateLifecycle(item, "restore")}
                  >
                    Restore
                  </Button>
                ) : null}
              </>
            )}
          />
        }
      />

      <Modal
        open={Boolean(activationTarget)}
        onClose={() => {
          if (!saving) {
            setActivationTarget(null);
            setActivationDepartmentId("");
          }
        }}
        title="Choose current-term specialization"
        description={`${activationLevel?.name || "This level"} requires a department in ${termLabel(currentTerm)} before this class can become active.`}
        footer={
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              disabled={Boolean(saving)}
              onClick={() => {
                setActivationTarget(null);
                setActivationDepartmentId("");
              }}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={!activationDepartmentId || Boolean(saving)}
              onClick={confirmActivation}
            >
              {saving ? "Activating..." : "Assign and activate"}
            </Button>
          </div>
        }
      >
        <SelectControl
          label={`Department for ${termLabel(currentTerm)}`}
          value={activationDepartmentId}
          onChange={setActivationDepartmentId}
          options={activationRequirement.options}
          placeholder="Select department"
          required
        />
      </Modal>
    </>
  );
}

export default ClassesWorkspace;
