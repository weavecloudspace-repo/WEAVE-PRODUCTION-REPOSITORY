import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import CurriculumCopyPanel from "./CurriculumCopyPanel";
import ElectiveGroupManager from "./ElectiveGroupManager";
import {
  beginAcademicSubmission,
  endAcademicSubmission,
  finishAcademicCreation,
} from "./academicSubmission";

import Button from "../../components/ui/Button";
import { useToast } from "../../hooks/useToast";
import { academicLevelService } from "../../services/academicsService";
import { getErrorMessage, parseApiError } from "../../services/api";
import { curriculumService } from "../../services/curriculumService";
import { departmentService } from "../../services/departmentService";
import { subjectService } from "../../services/subject.service";
import {
  FormActions,
  Input,
  RecordList,
  SelectControl,
  WorkspaceGrid,
  WorkspacePanel,
} from "./AcademicWorkspacePrimitives";
import TypedConfirmationDialog from "./TypedConfirmationDialog";
import { levelSupportsSpecialization } from "./academicDepartmentCapability";

const items = (value) => (Array.isArray(value) ? value : value?.items || []);

const scopeLabel = (row) => {
  const departments = row?.departments || [];
  if (departments.length === 0) return "General";
  return departments
    .map((item) => item.department_name || "Department")
    .filter(Boolean)
    .join(" · ");
};

const dependencyLabel = (key) =>
  ({
    teacher_assignments_total: "Teacher assignments",
    teacher_assignment_audits_total: "Teacher assignment history",
    results_total: "Result records",
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
  return blockers.length
    ? `${parsed.message} ${blockers.join("; ")}`
    : parsed.message;
};

export default function CurriculumWorkspace({ activeTab = "subjects" }) {
  const { showError, showSuccess } = useToast();
  const levelRequest = useRef(0);
  const [levels, setLevels] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [levelDepartments, setLevelDepartments] = useState([]);
  const [electiveGroups, setElectiveGroups] = useState([]);
  const [levelId, setLevelId] = useState("");
  const [curriculum, setCurriculum] = useState(null);
  const [selectedSubjectIds, setSelectedSubjectIds] = useState([]);
  const [query, setQuery] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const [addDepartmentIds, setAddDepartmentIds] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [elective, setElective] = useState(false);
  const [addElectiveGroupId, setAddElectiveGroupId] = useState("");
  const [scopeSubjectId, setScopeSubjectId] = useState("");
  const [selectedDepartmentIds, setSelectedDepartmentIds] = useState([]);
  const [semanticSubject, setSemanticSubject] = useState(null);
  const [semanticElective, setSemanticElective] = useState(false);
  const [semanticGroupId, setSemanticGroupId] = useState("");
  const [editorMode, setEditorMode] = useState("");
  const [saving, setSaving] = useState("");
  const [pendingDelete, setPendingDelete] = useState(null);

  const loadBase = useCallback(async () => {
    try {
      const [levelResponse, subjectResponse] = await Promise.all([
        academicLevelService.getLevels({ activeOnly: true }),
        subjectService.getSubjects({ limit: 500 }),
      ]);
      const levelRows = items(levelResponse);
      setLevels(levelRows);
      setSubjects(items(subjectResponse));
      setLevelId((current) => current || levelRows[0]?.id || "");
    } catch (error) {
      showError(getErrorMessage(error, "Could not load curriculum setup."));
    }
  }, [showError]);

  const loadLevel = useCallback(async () => {
    const request = ++levelRequest.current;
    if (!levelId) {
      setCurriculum(null);
      setLevelDepartments([]);
      setElectiveGroups([]);
      return;
    }
    setLoading(true);
    setLoadError("");
    setCurriculum(null);
    try {
      const [curriculumResponse, departmentResponse, groupResponse] =
        await Promise.all([
          curriculumService.getCurriculum(levelId),
          departmentService.getLevelDepartments(levelId, { activeOnly: true }),
          curriculumService.listElectiveGroups(levelId),
        ]);
      if (request !== levelRequest.current) return;
      const curriculumRows = curriculumResponse?.subjects || [];
      setCurriculum(curriculumResponse);
      setLevelDepartments(items(departmentResponse));
      setElectiveGroups(items(groupResponse));
      setScopeSubjectId((current) =>
        curriculumRows.some((row) => row.id === current)
          ? current
          : curriculumRows[0]?.id || "",
      );
    } catch (error) {
      if (request !== levelRequest.current) return;
      setLoadError(
        getErrorMessage(error, "Could not load this level curriculum."),
      );
    } finally {
      if (request === levelRequest.current) setLoading(false);
    }
  }, [levelId]);

  useEffect(() => {
    loadBase();
  }, [loadBase]);

  useEffect(() => {
    loadLevel();
    return () => {
      levelRequest.current += 1;
    };
  }, [loadLevel]);

  useEffect(() => {
    setEditorMode("");
    setSelectedSubjectIds([]);
    setAddDepartmentIds([]);
    setElective(false);
    setAddElectiveGroupId("");
    setSemanticSubject(null);
    setSemanticElective(false);
    setSemanticGroupId("");
    setReviewing(false);
  }, [activeTab, levelId]);

  const curriculumSubjects = useMemo(
    () => curriculum?.subjects || [],
    [curriculum],
  );
  const selectedLevel = useMemo(
    () => levels.find((row) => row.id === levelId) || null,
    [levelId, levels],
  );
  const activeElectiveGroups = useMemo(
    () => electiveGroups.filter((group) => group.lifecycle === "ACTIVE"),
    [electiveGroups],
  );
  const electiveGroupById = useMemo(
    () => new Map(electiveGroups.map((group) => [group.id, group])),
    [electiveGroups],
  );
  const specializationEnabled = levelSupportsSpecialization(selectedLevel);
  const attached = useMemo(
    () => new Set(curriculumSubjects.map((row) => row.subject_id)),
    [curriculumSubjects],
  );
  const available = subjects.filter(
    (row) =>
      !attached.has(row.id) && row.is_active !== false && !row.archived_at,
  );
  const matchingSubjects = subjects.filter((row) =>
    row.name.toLowerCase().includes(query.trim().toLowerCase()),
  );
  const selectedScopeSubject = useMemo(
    () => curriculumSubjects.find((row) => row.id === scopeSubjectId) || null,
    [curriculumSubjects, scopeSubjectId],
  );

  useEffect(() => {
    setSelectedDepartmentIds(
      (selectedScopeSubject?.departments || []).map(
        (item) => item.academic_level_department_id,
      ),
    );
  }, [selectedScopeSubject]);

  const addSubject = async (event) => {
    event.preventDefault();
    if (
      !selectedSubjectIds.length ||
      selectedSubjectIds.length > 100 ||
      !levelId ||
      !reviewing ||
      (elective && !addElectiveGroupId)
    )
      return;
    const submission = beginAcademicSubmission(event, Boolean(saving));
    if (!submission) return;
    setSaving("subject");
    try {
      await curriculumService.addSubjects(levelId, {
        subjects: selectedSubjectIds.map((subject_id) => ({
          subject_id,
          is_elective: elective,
          elective_group_id: elective ? addElectiveGroupId : null,
          academic_level_department_ids: specializationEnabled
            ? addDepartmentIds
            : [],
        })),
      });
      showSuccess(
        `${selectedSubjectIds.length} subjects added to the curriculum.`,
      );
      finishAcademicCreation(
        submission,
        () => {
          setSelectedSubjectIds([]);
          setElective(false);
          setAddElectiveGroupId("");
          setAddDepartmentIds([]);
          setReviewing(false);
        },
        () => setEditorMode(""),
      );
      await loadLevel();
    } catch (error) {
      showError(
        getErrorMessage(
          error,
          "Could not confirm subjects were saved. Refresh the curriculum before retrying.",
        ),
      );
    } finally {
      endAcademicSubmission(submission);
      setSaving("");
    }
  };

  const copyCurriculum = async (event, sourceLevelId) => {
    const submission = beginAcademicSubmission(event, Boolean(saving));
    if (!submission) return;
    setSaving("copy");
    try {
      const result = await curriculumService.copyCurriculum(
        levelId,
        sourceLevelId,
      );
      showSuccess(
        `${result.created} subjects copied. ${result.skipped_existing} already present; ${result.skipped_inactive} inactive subjects skipped.`,
      );
      setEditorMode("");
      await loadLevel();
    } catch (error) {
      showError(
        getErrorMessage(
          error,
          "Could not confirm the curriculum was copied. Refresh before retrying.",
        ),
      );
    } finally {
      endAcademicSubmission(submission);
      setSaving("");
    }
  };

  const beginSemanticEdit = (row) => {
    if (saving || row.is_active === false) return;
    setSemanticSubject(row);
    setSemanticElective(Boolean(row.is_elective));
    setSemanticGroupId(row.elective_group_id || "");
    setEditorMode("semantics");
  };

  const saveSemantics = async (event) => {
    event.preventDefault();
    if (!semanticSubject || saving || (semanticElective && !semanticGroupId)) {
      return;
    }
    const submission = beginAcademicSubmission(event, Boolean(saving));
    if (!submission) return;
    setSaving("semantics");
    try {
      await curriculumService.updateSubject(semanticSubject.id, {
        is_elective: semanticElective,
        elective_group_id: semanticElective ? semanticGroupId : null,
      });
      setSemanticSubject(null);
      setSemanticElective(false);
      setSemanticGroupId("");
      setEditorMode("");
      await loadLevel();
      showSuccess("Curriculum subject elective settings updated.");
    } catch (error) {
      showError(
        errorWithDependencies(
          error,
          "Could not update curriculum subject elective settings.",
        ),
      );
    } finally {
      endAcademicSubmission(submission);
      setSaving("");
    }
  };

  const updateLifecycle = async (row, action) => {
    if (saving) return;
    setSaving(row.id);
    try {
      if (action === "activate")
        await curriculumService.activateSubject(row.id);
      if (action === "deactivate")
        await curriculumService.deactivateSubject(row.id);
      await loadLevel();
      showSuccess(`Curriculum subject ${action}d.`);
    } catch (error) {
      showError(
        getErrorMessage(error, `Could not ${action} curriculum subject.`),
      );
    } finally {
      setSaving("");
    }
  };

  const deleteCurriculumSubject = async () => {
    if (!pendingDelete || saving) return;
    setSaving(pendingDelete.id);
    try {
      await curriculumService.deleteSubject(pendingDelete.id);
      showSuccess("Unused curriculum subject deleted.");
      setPendingDelete(null);
      await loadLevel();
    } catch (error) {
      showError(
        errorWithDependencies(
          error,
          "Could not delete curriculum subject. Deactivate it instead if academic history exists.",
        ),
      );
    } finally {
      setSaving("");
    }
  };

  const toggleDepartment = (departmentId) => {
    setSelectedDepartmentIds((current) =>
      current.includes(departmentId)
        ? current.filter((id) => id !== departmentId)
        : [...current, departmentId],
    );
  };

  const saveApplicability = async (event) => {
    event.preventDefault();
    if (!specializationEnabled || !scopeSubjectId || saving) return;
    const submission = beginAcademicSubmission(event, Boolean(saving));
    if (!submission) return;
    setSaving("applicability");
    try {
      await curriculumService.updateSubject(scopeSubjectId, {
        academic_level_department_ids: selectedDepartmentIds,
      });
      setEditorMode("");
      await loadLevel();
      showSuccess(
        selectedDepartmentIds.length
          ? "Subject applicability updated."
          : "Subject is now available to all specializations.",
      );
    } catch (error) {
      showError(
        getErrorMessage(error, "Could not update subject applicability."),
      );
    } finally {
      endAcademicSubmission(submission);
      setSaving("");
    }
  };

  const editApplicability = async (row) => {
    if (!specializationEnabled || !levelId || saving) return;
    try {
      const departmentResponse = await departmentService.getLevelDepartments(
        levelId,
        {
          activeOnly: true,
        },
      );
      const activeDepartments = items(departmentResponse);
      setLevelDepartments(activeDepartments);
      if (!activeDepartments.length) {
        showError(
          "Configure department specializations for this level before assigning a subject to a specialization.",
        );
        return;
      }
      setScopeSubjectId(row.id);
      setSelectedDepartmentIds(
        (row.departments || []).map(
          (item) => item.academic_level_department_id,
        ),
      );
      setEditorMode("applicability");
    } catch (error) {
      showError(
        getErrorMessage(error, "Could not load department specializations."),
      );
    }
  };

  const levelControl = (
    <SelectControl
      label="Academic level"
      value={levelId}
      onChange={setLevelId}
      options={levels.map((row) => ({ value: row.id, label: row.name }))}
      required
      disabled={Boolean(saving)}
    />
  );

  const applicabilityEditorOpen =
    editorMode === "applicability" && specializationEnabled;
  const applicabilityEditor = applicabilityEditorOpen ? (
    <WorkspacePanel
      title="Subject applicability"
      description="Choose which specializations receive this subject once specialization is active. With no departments selected, the subject is general and remains available to every class."
    >
      <form className="space-y-4" onSubmit={saveApplicability}>
        <fieldset disabled={Boolean(saving)} className="space-y-4">
          <SelectControl
            label="Curriculum subject"
            value={scopeSubjectId}
            onChange={setScopeSubjectId}
            options={curriculumSubjects
              .filter((row) => row.is_active !== false)
              .map((row) => ({ value: row.id, label: row.subject_name }))}
            required
          />

          {specializationEnabled && levelDepartments.length ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-text">Available to</p>
                <Button
                  type="button"
                  size="small"
                  variant="outline"
                  onClick={() => setSelectedDepartmentIds([])}
                >
                  All specializations
                </Button>
              </div>
              <div className="space-y-2 rounded-xl border border-border bg-surface-muted p-3">
                {levelDepartments.map((row) => (
                  <label
                    key={row.id}
                    className="flex items-center gap-3 text-sm text-text"
                  >
                    <input
                      type="checkbox"
                      checked={selectedDepartmentIds.includes(row.id)}
                      onChange={() => toggleDepartment(row.id)}
                    />
                    <span>{row.department_name || "Department"}</span>
                  </label>
                ))}
              </div>
              <p className="text-xs leading-5 text-text-muted">
                {selectedDepartmentIds.length === 0
                  ? "General subject — available to every specialization."
                  : "Specialization-scoped subject — available only to the selected departments after specialization begins."}
              </p>
            </div>
          ) : (
            <p className="text-sm leading-6 text-text-muted">
              This level has no department specializations. Subjects are
              available to every class in the level.
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            <Button
              type="submit"
              disabled={saving === "applicability" || !scopeSubjectId}
            >
              {saving === "applicability" ? "Saving…" : "Save changes"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => setEditorMode("")}
            >
              Cancel
            </Button>
          </div>
        </fieldset>
      </form>
    </WorkspacePanel>
  ) : null;

  if (activeTab === "applicability") {
    return (
      <>
        <WorkspaceGrid
          editor={applicabilityEditor}
          content={
            <RecordList
              title="Subject applicability"
              description={
                specializationEnabled
                  ? "Department scope is part of the level curriculum. Before specialization begins, every active curriculum subject remains available to every class."
                  : "This level does not specialize. Every curriculum subject is General and available to every class in the level."
              }
              actions={<div className="min-w-[18rem]">{levelControl}</div>}
              loading={loading}
              error={loadError}
              onRetry={loadLevel}
              items={curriculumSubjects}
              emptyTitle="No curriculum subjects"
              emptyDescription="Add subjects to this level before configuring specialization applicability."
              renderTitle={(row) => row.subject_name}
              renderMeta={(row) =>
                row.is_elective ? "Elective" : "Compulsory"
              }
              renderDescription={(row) =>
                specializationEnabled
                  ? `Available to: ${scopeLabel(row)}`
                  : "General — available to every class in this level."
              }
              renderStatus={(row) =>
                row.is_active === false ? "inactive" : "active"
              }
              showInspector={!applicabilityEditorOpen}
              renderActions={(row) =>
                specializationEnabled ? (
                  <Button
                    size="small"
                    variant="outline"
                    disabled={row.is_active === false || Boolean(saving)}
                    onClick={() => editApplicability(row)}
                  >
                    Edit applicability
                  </Button>
                ) : null
              }
            />
          }
        />
        <TypedConfirmationDialog
          open={Boolean(pendingDelete)}
          title="Delete unused curriculum subject"
          description={
            pendingDelete
              ? `Permanently remove ${pendingDelete.subject_name || "this subject"} from this level curriculum. This only succeeds while the curriculum subject has no teacher assignments, assignment history, or result records.`
              : ""
          }
          confirmationText="DELETE_CURRICULUM_SUBJECT"
          confirmLabel="Delete if unused"
          variant="danger"
          isLoading={saving === pendingDelete?.id}
          onConfirm={deleteCurriculumSubject}
          onCancel={() => setPendingDelete(null)}
        />
      </>
    );
  }

  const semanticsEditor = editorMode === "semantics" && semanticSubject ? (
    <WorkspacePanel
      title="Elective settings"
      description={`Set whether ${semanticSubject.subject_name || "this subject"} is compulsory or elective. Elective subjects must belong to one active group.`}
    >
      <form className="space-y-4" onSubmit={saveSemantics}>
        <fieldset disabled={Boolean(saving)} className="space-y-4">
          <label className="flex items-center gap-2 text-sm font-medium text-text">
            <input
              type="checkbox"
              checked={semanticElective}
              onChange={(event) => {
                const next = event.target.checked;
                setSemanticElective(next);
                if (!next) setSemanticGroupId("");
              }}
            />
            Elective subject
          </label>
          {semanticElective ? (
            activeElectiveGroups.length ? (
              <SelectControl
                label="Elective group"
                value={semanticGroupId}
                onChange={setSemanticGroupId}
                options={activeElectiveGroups.map((group) => ({
                  value: group.id,
                  label: `${group.name} (${group.minimum_choices}–${group.maximum_choices})`,
                }))}
                required
              />
            ) : (
              <div className="rounded-xl border border-warning/30 bg-warning-soft px-3 py-3 text-sm text-text-soft">
                Create an active elective group before making a subject elective.
              </div>
            )
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button
              type="submit"
              disabled={
                saving === "semantics" ||
                (semanticElective && !semanticGroupId)
              }
            >
              {saving === "semantics" ? "Saving…" : "Save elective settings"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setSemanticSubject(null);
                setEditorMode("");
              }}
            >
              Cancel
            </Button>
          </div>
        </fieldset>
      </form>
    </WorkspacePanel>
  ) : null;

  const editorOpen = [
    "subject",
    "copy",
    "applicability",
    "elective-groups",
    "semantics",
  ].includes(editorMode);

  return (
    <>
      <WorkspaceGrid
        editor={
          editorMode === "copy" && selectedLevel ? (
            <CurriculumCopyPanel
              key={levelId}
              levels={levels}
              target={selectedLevel}
              targetSubjects={curriculumSubjects}
              targetDepartments={levelDepartments}
              saving={Boolean(saving)}
              onCopy={copyCurriculum}
              onCancel={() => setEditorMode("")}
            />
          ) : editorMode === "elective-groups" ? (
            <ElectiveGroupManager
              levelId={levelId}
              groups={electiveGroups}
              onChanged={loadLevel}
              onCancel={() => setEditorMode("")}
            />
          ) : editorMode === "semantics" ? (
            semanticsEditor
          ) : editorMode === "applicability" ? (
            applicabilityEditor
          ) : editorOpen ? (
            <WorkspacePanel
              title="Add subjects to curriculum"
              description={
                specializationEnabled
                  ? "Select subjects, set elective status and department applicability, then review before saving."
                  : "Select subjects, set elective status, then review before saving. Subjects in this level are General."
              }
            >
              <form className="space-y-3" onSubmit={addSubject}>
                <fieldset disabled={Boolean(saving)} className="space-y-3">
                  {!reviewing ? (
                    <>
                      <Input
                        label="Search subjects"
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        autoFocus
                      />
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() =>
                          setSelectedSubjectIds((current) => [
                            ...new Set([
                              ...current,
                              ...available
                                .filter((row) =>
                                  row.name
                                    .toLowerCase()
                                    .includes(query.toLowerCase()),
                                )
                                .map((row) => row.id),
                            ]),
                          ])
                        }
                      >
                        Select all matching available subjects
                      </Button>
                      <div className="max-h-72 space-y-2 overflow-y-auto rounded-lg border border-border p-3">
                        {matchingSubjects.map((row) => (
                          <label
                            key={row.id}
                            className="flex items-center gap-2 text-sm"
                          >
                            <input
                              type="checkbox"
                              checked={selectedSubjectIds.includes(row.id)}
                              disabled={
                                attached.has(row.id) ||
                                !available.some((item) => item.id === row.id)
                              }
                              onChange={(event) =>
                                setSelectedSubjectIds((current) =>
                                  event.target.checked
                                    ? [...current, row.id]
                                    : current.filter((id) => id !== row.id),
                                )
                              }
                            />
                            {row.name}
                            {attached.has(row.id)
                              ? " - Already added"
                              : row.is_active === false || row.archived_at
                                ? " - Inactive"
                                : ""}
                          </label>
                        ))}
                        {!matchingSubjects.length ? (
                          <p>No subjects match your search.</p>
                        ) : null}
                      </div>
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={elective}
                          onChange={(event) => {
                            const next = event.target.checked;
                            setElective(next);
                            if (!next) setAddElectiveGroupId("");
                          }}
                        />{" "}
                        Elective subjects
                      </label>
                      {elective ? (
                        activeElectiveGroups.length ? (
                          <SelectControl
                            label="Elective group"
                            value={addElectiveGroupId}
                            onChange={setAddElectiveGroupId}
                            options={activeElectiveGroups.map((group) => ({
                              value: group.id,
                              label: `${group.name} (${group.minimum_choices}–${group.maximum_choices})`,
                            }))}
                            required
                          />
                        ) : (
                          <div className="space-y-2 rounded-xl border border-warning/30 bg-warning-soft px-3 py-3 text-sm text-text-soft">
                            <p>
                              This level has no active elective group. Create one before adding elective subjects.
                            </p>
                            <Button
                              type="button"
                              size="small"
                              variant="outline"
                              onClick={() => setEditorMode("elective-groups")}
                            >
                              Manage Elective Groups
                            </Button>
                          </div>
                        )
                      ) : null}
                      {specializationEnabled ? (
                        <>
                          <p className="text-sm font-semibold">
                            Department applicability
                          </p>
                          <p className="text-sm text-text-muted">
                            No departments selected means General. These
                            settings apply to every selected subject.
                          </p>
                          {levelDepartments.map((row) => (
                            <label
                              key={row.id}
                              className="flex items-center gap-2 text-sm"
                            >
                              <input
                                type="checkbox"
                                checked={addDepartmentIds.includes(row.id)}
                                onChange={(event) =>
                                  setAddDepartmentIds((current) =>
                                    event.target.checked
                                      ? [...current, row.id]
                                      : current.filter((id) => id !== row.id),
                                  )
                                }
                              />
                              {row.department_name}
                            </label>
                          ))}
                        </>
                      ) : null}
                      {selectedSubjectIds.length > 100 ? (
                        <p role="alert" className="text-sm text-error">
                          Select at most 100 subjects per batch.
                        </p>
                      ) : null}
                      <Button
                        type="button"
                        disabled={
                          !selectedSubjectIds.length ||
                          selectedSubjectIds.length > 100 ||
                          (elective && !addElectiveGroupId)
                        }
                        onClick={() => setReviewing(true)}
                      >
                        Review {selectedSubjectIds.length} subjects
                      </Button>
                    </>
                  ) : (
                    <>
                      <p className="text-sm">
                        {subjects
                          .filter((row) => selectedSubjectIds.includes(row.id))
                          .map((row) => row.name)
                          .join(", ")}
                      </p>
                      <p className="text-sm">
                        {elective
                          ? `Elective / ${
                              electiveGroupById.get(addElectiveGroupId)?.name ||
                              "Group required"
                            }`
                          : "Compulsory"} /{" "}
                        {specializationEnabled && addDepartmentIds.length
                          ? levelDepartments
                              .filter((row) =>
                                addDepartmentIds.includes(row.id),
                              )
                              .map((row) => row.department_name)
                              .join(", ")
                          : "General"}
                      </p>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => setReviewing(false)}
                      >
                        Change selection
                      </Button>
                      <FormActions
                        repeatable
                        submitting={Boolean(saving)}
                        onCancel={() => setEditorMode("")}
                      />
                    </>
                  )}
                </fieldset>
              </form>
            </WorkspacePanel>
          ) : null
        }
        content={
          <RecordList
            title={
              curriculum?.level_name
                ? `${curriculum.level_name} curriculum`
                : "Curriculum"
            }
            description="The persistent level subject set used by teacher assignments, results, CBT, and report cards."
            actions={<div className="w-full min-w-0 sm:w-72">{levelControl}</div>}
            toolbar={
              !editorOpen ? (
                <div className="mb-4 flex flex-wrap items-center gap-2 border-b border-border/70 pb-4">
                  <Button
                    type="button"
                    disabled={loading || Boolean(loadError) || !curriculum}
                    onClick={() => setEditorMode("subject")}
                  >
                    Add subjects
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={loading || Boolean(loadError) || !curriculum}
                    onClick={() => setEditorMode("copy")}
                  >
                    Copy curriculum
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={loading || Boolean(loadError) || !curriculum}
                    onClick={() => setEditorMode("elective-groups")}
                  >
                    Manage Elective Groups
                  </Button>
                </div>
              ) : null
            }
            loading={loading}
            error={loadError}
            onRetry={loadLevel}
            items={curriculumSubjects}
            emptyTitle="No curriculum subjects"
            emptyDescription="Attach a subject from the school subject pool."
            renderTitle={(row) => row.subject_name}
            renderMeta={(row) =>
              row.is_elective
                ? `Elective · ${
                    electiveGroupById.get(row.elective_group_id)?.name ||
                    "Legacy ungrouped"
                  }`
                : "Compulsory"
            }
            renderDescription={(row) => `Available to: ${scopeLabel(row)}`}
            renderStatus={(row) =>
              row.is_active === false ? "inactive" : "active"
            }
            showInspector={!editorOpen}
            renderActions={(row) => (
              <>
                {specializationEnabled ? (
                  <Button
                    size="small"
                    variant="outline"
                    disabled={row.is_active === false || Boolean(saving)}
                    onClick={() => editApplicability(row)}
                  >
                    Edit scope
                  </Button>
                ) : null}
                <Button
                  size="small"
                  variant="outline"
                  disabled={row.is_active === false || Boolean(saving)}
                  onClick={() => beginSemanticEdit(row)}
                >
                  Elective settings
                </Button>
                <Button
                  size="small"
                  variant="outline"
                  disabled={Boolean(saving)}
                  onClick={() =>
                    updateLifecycle(
                      row,
                      row.is_active === false ? "activate" : "deactivate",
                    )
                  }
                >
                  {row.is_active === false ? "Activate" : "Deactivate"}
                </Button>
                <Button
                  size="small"
                  variant="danger"
                  disabled={Boolean(saving)}
                  onClick={() => setPendingDelete(row)}
                >
                  Delete if unused
                </Button>
              </>
            )}
          />
        }
      />
      <TypedConfirmationDialog
        open={Boolean(pendingDelete)}
        title="Delete unused curriculum subject"
        description={
          pendingDelete
            ? `Permanently remove ${pendingDelete.subject_name || "this subject"} from this level curriculum. This only succeeds while the curriculum subject has no teacher assignments, assignment history, or result records.`
            : ""
        }
        confirmationText="DELETE_CURRICULUM_SUBJECT"
        confirmLabel="Delete if unused"
        variant="danger"
        isLoading={saving === pendingDelete?.id}
        onConfirm={deleteCurriculumSubject}
        onCancel={() => setPendingDelete(null)}
      />
    </>
  );
}
