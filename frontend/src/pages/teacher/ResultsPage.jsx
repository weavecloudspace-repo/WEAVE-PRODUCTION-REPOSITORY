import { LockKeyhole, Save, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import DashboardLayout from "../../components/layout/DashboardLayout";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import Table from "../../components/ui/Table";
import EmptyState from "../../components/shared/EmptyState";
import LoadingState from "../../components/shared/LoadingState";
import { SelectField } from "../../components/academic/AcademicSelectors";
import { useToast } from "../../hooks/useToast";
import { academicService } from "../../services/academicService";
import { getErrorMessage } from "../../services/api";
import { buildManualScores, currentAcademicContext, loadAllItems, resultReadiness } from "./resultsWorkspace";

const assignmentLabel = (assignment) =>
  `${assignment.subject_name || "Subject"} · ${assignment.class_name || "Class"} ${assignment.class_arm || ""}`.trim();

const studentName = (student) =>
  [student.first_name, student.last_name].filter(Boolean).join(" ") ||
  student.student_name ||
  student.admission_number ||
  "Student";

const scoreKey = (studentId, componentId) => `${studentId}:${componentId}`;

function ResultsPage() {
  const [assignments, setAssignments] = useState([]);
  const [scheme, setScheme] = useState(null);
  const [session, setSession] = useState(null);
  const [term, setTerm] = useState(null);
  const [selectedAssignmentId, setSelectedAssignmentId] = useState("");
  const [students, setStudents] = useState([]);
  const [resultsByStudent, setResultsByStudent] = useState({});
  const [draftScores, setDraftScores] = useState({});
  const [savingStudentId, setSavingStudentId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [rosterLoading, setRosterLoading] = useState(false);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const requestGeneration = useRef(0);
  const { showSuccess, showError } = useToast();

  useEffect(() => {
    let mounted = true;

    async function loadContext() {
      setLoading(true);
      setError(null);
      try {
        const [assignmentResponse, assessmentScheme, sessionResponse, termResponse] =
          await Promise.all([
            academicService.listMyTeacherAssignments(),
            academicService.getTeacherAssessmentScheme(),
            loadAllItems((params) => academicService.listTeacherSessions(params)),
            loadAllItems((params) => academicService.listTeacherTerms(params)),
          ]);
        if (!mounted) return;

        const nextAssignments = assignmentResponse?.items || [];
        setAssignments(nextAssignments);
        setSelectedAssignmentId(nextAssignments[0]?.id || "");
        setScheme(assessmentScheme || null);
        const context = currentAcademicContext(sessionResponse, termResponse);
        setSession(context.session);
        setTerm(context.term);
      } catch (err) {
        if (mounted) {
          setError(getErrorMessage(err, "Could not load the teacher grading workspace."));
        }
      } finally {
        if (mounted) setLoading(false);
      }
    }

    loadContext();
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const generation = ++requestGeneration.current;
    const isCurrent = () => !controller.signal.aborted && generation === requestGeneration.current;
    async function loadAssignment() {
      if (!selectedAssignmentId || !session?.id || !term?.id) {
        setStudents([]);
        setResultsByStudent({});
        setDraftScores({});
        setRosterLoading(false);
        return;
      }

      setRosterLoading(true);
      setError(null);
      try {
        const [rosterResponse, resultsResponse] = await Promise.all([
          loadAllItems(
            (params) => academicService.listMyAssignmentStudents(
              selectedAssignmentId, params, { signal: controller.signal },
            ),
            controller.signal,
          ),
          loadAllItems(
            (params) => academicService.listTeacherResults({
              ...params,
              teacher_assignment_id: selectedAssignmentId,
              academic_session_id: session.id,
              academic_term_id: term.id,
            }, { signal: controller.signal }),
            controller.signal,
          ),
        ]);
        if (!isCurrent()) return;
        const nextStudents = rosterResponse;
        const results = resultsResponse;
        const nextResults = Object.fromEntries(results.map((result) => [result.student_id, result]));
        const nextDrafts = {};

        results.forEach((result) => {
          (result.components || []).forEach((component) => {
            nextDrafts[scoreKey(result.student_id, component.assessment_component_id)] =
              component.score ?? "";
          });
        });

        setStudents(nextStudents);
        setResultsByStudent(nextResults);
        setDraftScores(nextDrafts);
      } catch (err) {
        if (!isCurrent()) return;
        setStudents([]);
        setResultsByStudent({});
        setDraftScores({});
        setError(getErrorMessage(err, "Could not load students and scores."));
      } finally {
        if (isCurrent()) setRosterLoading(false);
      }
    }
    void loadAssignment();
    return () => controller.abort();
  }, [selectedAssignmentId, session, term]);

  const components = useMemo(
    () => [...(scheme?.components || [])].sort((a, b) => a.position - b.position),
    [scheme],
  );
  const manualComponents = useMemo(
    () => components.filter((component) => component.is_examinable === false),
    [components],
  );
  const selectedAssignment = assignments.find(
    (assignment) => assignment.id === selectedAssignmentId,
  );
  const filteredStudents = useMemo(() => {
    const query = search.trim().toLowerCase();
    return students.filter((student) => !query ||
      `${studentName(student)} ${student.admission_number || ""}`.toLowerCase().includes(query));
  }, [students, search]);
  const pageSize = 25;
  const visibleStudents = filteredStudents.slice(page * pageSize, (page + 1) * pageSize);

  const changeAssignment = (id) => {
    if (id === selectedAssignmentId) return;
    requestGeneration.current += 1;
    setStudents([]);
    setResultsByStudent({});
    setDraftScores({});
    setError(null);
    setPage(0);
    setSearch("");
    setRosterLoading(true);
    setSelectedAssignmentId(id);
  };

  const updateScore = (studentId, componentId, value) => {
    setDraftScores((current) => ({
      ...current,
      [scoreKey(studentId, componentId)]: value,
    }));
  };

  const saveStudent = async (student) => {
    if (!selectedAssignment || !session?.id || !term?.id || !manualComponents.length || savingStudentId || rosterLoading) return;
    if (resultsByStudent[student.id] && resultsByStudent[student.id].status !== "draft") return;

    setSavingStudentId(student.id);
    try {
      const componentScores = buildManualScores(student.id, components, draftScores);

      const saved = await academicService.saveTeacherResult({
        student_id: student.id,
        teacher_assignment_id: selectedAssignment.id,
        academic_session_id: session.id,
        academic_term_id: term.id,
        component_scores: componentScores,
        status: "draft",
      });

      setResultsByStudent((current) => ({ ...current, [student.id]: saved }));
      setDraftScores((current) => {
        const next = { ...current };
        (saved.components || []).forEach((component) => {
          next[scoreKey(student.id, component.assessment_component_id)] = component.score ?? "";
        });
        return next;
      });
      showSuccess(`${studentName(student)} scores saved.`);
    } catch (err) {
      showError(getErrorMessage(err, "Could not save the student's manual scores."));
    } finally {
      setSavingStudentId(null);
    }
  };

  const columns = [
    {
      key: "student",
      label: "Student",
      render: (student) => (
        <span className="block min-w-40">
          <span className="block font-semibold text-text">{studentName(student)}</span>
          <span className="block text-xs text-text-muted">{student.admission_number || "No admission number"}</span>
        </span>
      ),
    },
    ...components.map((component) => ({
      key: component.id,
      label: `${component.name} / ${component.maximum_score}`,
      render: (student) => {
        const result = resultsByStudent[student.id];
        const storedScore = result?.components?.find((item) => item.assessment_component_id === component.id)?.score;
        const examinable = component.is_examinable !== false;
        const locked = Boolean(result && result.status !== "draft");
        if (examinable) {
          return (
            <span className="inline-flex items-center gap-2 text-text-muted">
              <LockKeyhole aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
              <span>{storedScore ?? "Awaiting score"}</span>
            </span>
          );
        }
        return (
          <input
            aria-label={`${studentName(student)} ${component.name} score, maximum ${component.maximum_score}`}
            type="number"
            min="0"
            max={component.maximum_score}
            step="0.01"
            value={draftScores[scoreKey(student.id, component.id)] ?? storedScore ?? ""}
            disabled={locked || savingStudentId === student.id}
            placeholder="Score"
            onChange={(event) => updateScore(student.id, component.id, event.target.value)}
            className="h-9 w-full min-w-20 rounded-lg border border-border bg-background px-3 text-sm text-text outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-muted md:w-24"
          />
        );
      },
    })),
    {
      key: "status",
      label: "Status",
      render: (student) => {
        const result = resultsByStudent[student.id];
        const status = result?.status || "draft";
        const readiness = resultReadiness(components, result);
        return (
          <span className="block space-y-1">
            <Badge variant={status === "draft" ? "info" : "default"}>{status}</Badge>
            {status === "draft" ? (
              <span className="block text-xs text-text-muted">
                {readiness.ready ? "Ready for admin review" : `Manual ${readiness.manualEntered}/${readiness.manualRequired} · Exam ${readiness.examEntered}/${readiness.examRequired}`}
              </span>
            ) : null}
          </span>
        );
      },
    },
    {
      key: "actions",
      label: "Action",
      render: (student) => {
        const result = resultsByStudent[student.id];
        const locked = Boolean(result && result.status !== "draft");
        return locked || !manualComponents.length ? (
          <span className="text-xs text-text-muted">{locked ? "Read only" : "CBT managed"}</span>
        ) : (
          <Button
            size="sm"
            variant="outline"
            className="whitespace-nowrap"
            disabled={Boolean(savingStudentId)}
            aria-label={`Save scores for ${studentName(student)}`}
            onClick={() => saveStudent(student)}
          >
            <Save aria-hidden="true" className="mr-1.5 h-3.5 w-3.5" />
            {savingStudentId === student.id ? "Saving..." : "Save"}
          </Button>
        );
      },
    },
  ];

  if (loading) {
    return (
      <DashboardLayout role="teacher" title="Results">
        <LoadingState label="Loading grading workspace..." />
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout
      role="teacher"
      title="Results"
      description="Record teacher-managed assessment scores. Examinable components are locked because CBT or an administrator owns those scores."
    >
      <div className="space-y-4">
        {error ? (
          <div className="rounded-xl border border-error/30 bg-error-soft px-4 py-3 text-sm font-semibold text-error">
            {error}
          </div>
        ) : null}

        <Card className="p-4">
          <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
            <SelectField
              label="Class and subject"
              value={selectedAssignmentId}
              onChange={changeAssignment}
              disabled={Boolean(savingStudentId) || !assignments.length}
            >
              {assignments.map((assignment) => (
                <option key={assignment.id} value={assignment.id}>
                  {assignmentLabel(assignment)}
                </option>
              ))}
            </SelectField>
            <div className="flex flex-wrap gap-2 text-xs">
              {session ? <Badge variant="default">{session.name}</Badge> : null}
              {term ? <Badge variant="default">{term.name.replace(/_/g, " ")}</Badge> : null}
              {scheme ? <Badge variant="info">{scheme.name}</Badge> : null}
            </div>
          </div>
        </Card>

        {components.length ? (
          <div className="flex flex-wrap gap-2">
            {components.map((component) => (
              <Badge
                key={component.id}
                variant={component.is_examinable === false ? "success" : "default"}
              >
                {component.name} · {component.maximum_score} · {component.is_examinable === false ? "Manual" : "CBT locked"}
              </Badge>
            ))}
          </div>
        ) : null}

        {rosterLoading ? (
          <LoadingState label="Loading student scores..." />
        ) : !selectedAssignmentId ? (
          <EmptyState title="No subject assignment" description="You do not currently have a subject assignment available for result entry." />
        ) : !session || !term ? (
          <EmptyState title="No current academic context" description="A current session and term are required before recording scores." />
        ) : !components.length ? (
          <EmptyState title="No assessment components" description="An active assessment scheme with components is required to record scores." />
        ) : !students.length ? (
          <EmptyState title="No students" description="No students are available in this assignment roster." />
        ) : (
          <div className="space-y-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <label className="relative block w-full sm:max-w-sm">
                <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
                <input
                  type="search"
                  aria-label="Search students by name or admission number"
                  placeholder="Search students or admission number"
                  value={search}
                  onChange={(event) => { setSearch(event.target.value); setPage(0); }}
                  className="input-base h-10 pl-9"
                />
              </label>
              <p className="text-sm text-text-muted">{filteredStudents.length} student{filteredStudents.length === 1 ? "" : "s"}</p>
            </div>
            <Table columns={columns} rows={visibleStudents} emptyText="No students match your search." />
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-text-muted">
                {manualComponents.length ? "Save each student's manual scores. CBT scores are read only." : "All scores are managed by CBT or an administrator."}
              </p>
              {filteredStudents.length > pageSize ? (
                <div className="flex items-center gap-3">
                  <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage((current) => current - 1)}>Previous</Button>
                  <span className="text-xs text-text-muted">Page {page + 1} of {Math.ceil(filteredStudents.length / pageSize)}</span>
                  <Button variant="outline" size="sm" disabled={(page + 1) * pageSize >= filteredStudents.length} onClick={() => setPage((current) => current + 1)}>Next</Button>
                </div>
              ) : null}
            </div>
          </div>
        )}
      </div>
    </DashboardLayout>
  );
}

export default ResultsPage;
