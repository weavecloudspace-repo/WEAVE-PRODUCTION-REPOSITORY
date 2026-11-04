import { useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  CheckSquare,
  ClipboardList,
  Search,
  UserCheck,
  UserRound,
  Users,
} from "lucide-react";

import DashboardLayout from "../../components/layout/DashboardLayout";
import {
  DirectorySummary,
  DirectoryTable,
  MobileDirectoryList,
  MobilePersonCard,
  PersonIdentity,
} from "../../components/people/PeopleDirectory";
import Card from "../../components/ui/Card";
import Badge from "../../components/ui/Badge";
import Input from "../../components/ui/Input";
import LoadingState from "../../components/shared/LoadingState";
import EmptyState from "../../components/shared/EmptyState";
import { SelectField } from "../../components/academic/AcademicSelectors";
import { displayClass } from "../../components/academic/academicDisplay";
import { getErrorMessage } from "../../services/api";
import { academicService } from "../../services/academicService";
import { classService } from "../../services/academicsService";
import { studentService } from "../../services/studentService";
import { loadAllItems } from "./resultsWorkspace";
import { cn } from "../../utils/cn";

const studentName = (student) =>
  [student.first_name, student.last_name].filter(Boolean).join(" ") ||
  student.admission_number ||
  "Student";
const classLabel = (item) => displayClass(item);
const assignmentLabel = (item) =>
  `${item.subject_name || "Subject"} - ${item.class_name || "Class"} ${item.class_arm || ""}`.trim();
const subjectLabel = (item) =>
  item.subject_name || item.subject_code || "Subject";

const rosterTabs = [
  {
    id: "subject",
    label: "Subject roster",
    shortLabel: "Subject",
    icon: BookOpen,
    description: "Students you teach for a selected class and subject.",
  },
  {
    id: "class",
    label: "Class teacher roster",
    shortLabel: "Class",
    icon: CheckSquare,
    description: "Full class list only when you are the class teacher.",
  },
];

function StudentsPage() {
  const [activeTab, setActiveTab] = useState("subject");
  const [classTeacherClasses, setClassTeacherClasses] = useState([]);
  const [subjectAssignments, setSubjectAssignments] = useState([]);
  const [selectedClassId, setSelectedClassId] = useState("");
  const [selectedSubjectId, setSelectedSubjectId] = useState("");
  const [selectedAssignmentId, setSelectedAssignmentId] = useState("");
  const [classStudents, setClassStudents] = useState([]);
  const [subjectStudents, setSubjectStudents] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRosterLoading, setIsRosterLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let mounted = true;
    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const [classResponse, assignmentResponse] = await Promise.all([
          classService.getClasses({ limit: 100, activeOnly: true }),
          academicService.listMyTeacherAssignments(),
        ]);
        if (!mounted) return;
        const classes = classResponse?.items || [];
        const assignments = assignmentResponse?.items || [];
        setClassTeacherClasses(classes);
        setSubjectAssignments(assignments);
        setSelectedClassId(classes[0]?.id || "");
        setSelectedSubjectId(assignments[0]?.subject_id || "");
        setSelectedAssignmentId(assignments[0]?.id || "");
      } catch (err) {
        if (mounted)
          setError(getErrorMessage(err, "Could not load teacher rosters."));
      } finally {
        if (mounted) setIsLoading(false);
      }
    }
    load();
    return () => {
      mounted = false;
    };
  }, []);

  const subjectOptions = useMemo(() => {
    const map = new Map();
    subjectAssignments.forEach((assignment) => {
      if (assignment.subject_id && !map.has(assignment.subject_id)) {
        map.set(assignment.subject_id, subjectLabel(assignment));
      }
    });
    return [...map.entries()].map(([id, label]) => ({ id, label }));
  }, [subjectAssignments]);

  const filteredAssignments = useMemo(
    () =>
      subjectAssignments.filter(
        (assignment) =>
          !selectedSubjectId || assignment.subject_id === selectedSubjectId,
      ),
    [subjectAssignments, selectedSubjectId],
  );

  useEffect(() => {
    if (
      !filteredAssignments.some(
        (assignment) => assignment.id === selectedAssignmentId,
      )
    ) {
      const timeoutId = window.setTimeout(() => {
        setSelectedAssignmentId(filteredAssignments[0]?.id || "");
      }, 0);
      return () => window.clearTimeout(timeoutId);
    }
    return undefined;
  }, [filteredAssignments, selectedAssignmentId]);

  useEffect(() => {
    let mounted = true;
    async function loadClassStudents() {
      if (!selectedClassId) {
        setClassStudents([]);
        return;
      }
      try {
        const students = await loadAllItems((params) =>
          studentService.getStudents({ classId: selectedClassId, ...params }),
        );
        if (mounted) setClassStudents(students);
      } catch (err) {
        if (mounted) setClassStudents([]);
        if (mounted)
          setError(
            getErrorMessage(err, "Could not load class-teacher students."),
          );
      }
    }
    loadClassStudents();
    return () => {
      mounted = false;
    };
  }, [selectedClassId]);

  useEffect(() => {
    let mounted = true;
    async function loadSubjectRoster() {
      if (!selectedAssignmentId) {
        setSubjectStudents([]);
        return;
      }
      setIsRosterLoading(true);
      try {
        const students = await loadAllItems((params) =>
          academicService.listMyAssignmentStudents(selectedAssignmentId, params),
        );
        if (mounted) setSubjectStudents(students);
      } catch (err) {
        if (mounted) {
          setSubjectStudents([]);
          setError(
            getErrorMessage(err, "Could not load subject-teaching roster."),
          );
        }
      } finally {
        if (mounted) setIsRosterLoading(false);
      }
    }
    loadSubjectRoster();
    return () => {
      mounted = false;
    };
  }, [selectedAssignmentId]);

  if (isLoading) {
    return (
      <DashboardLayout role="teacher" title="Teaching Rosters">
        <LoadingState label="Loading rosters..." />
      </DashboardLayout>
    );
  }

  const selectedAssignment = subjectAssignments.find(
    (item) => item.id === selectedAssignmentId,
  );
  const activeTabMeta =
    rosterTabs.find((tab) => tab.id === activeTab) || rosterTabs[0];
  const ActiveIcon = activeTabMeta.icon;

  return (
    <DashboardLayout
      role="teacher"
      title="Teaching Rosters"
      description="Switch between subject-teaching rosters and class-teacher rosters without crowding one page."
    >
      {error ? (
        <div className="rounded-xl border border-error/30 bg-error-soft px-4 py-3 text-sm font-semibold text-error">
          {error}
        </div>
      ) : null}

      <Card className="overflow-hidden p-4 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-primary-soft text-primary">
              <ActiveIcon className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h2 className="section-title">{activeTabMeta.label}</h2>
              <p className="mt-1 text-sm leading-6 text-text-muted">
                {activeTabMeta.description}
              </p>
            </div>
          </div>

          <div className="relative grid grid-cols-2 rounded-2xl border border-border/70 bg-surface-muted/35 p-1 shadow-inner lg:w-[24rem]">
            <span
              aria-hidden="true"
              className="absolute bottom-1 top-1 w-[calc(50%-0.25rem)] rounded-xl bg-surface shadow-sm transition-transform duration-300 ease-out"
              style={{
                transform:
                  activeTab === "class"
                    ? "translateX(calc(100% + 0.25rem))"
                    : "translateX(0)",
              }}
            />
            {rosterTabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    "relative z-10 flex min-h-11 items-center justify-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold transition sm:text-sm",
                    isActive
                      ? "text-primary"
                      : "text-text-muted hover:text-text",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  <span className="hidden sm:inline">{tab.label}</span>
                  <span className="sm:hidden">{tab.shortLabel}</span>
                </button>
              );
            })}
          </div>
        </div>
      </Card>

      <section className="grid gap-5">
        {activeTab === "subject" ? (
          <Card className="p-4 sm:p-5">
            {subjectAssignments.length === 0 ? (
              <EmptyState
                icon={ClipboardList}
                title="No subject-teacher assignment"
                description="When an admin assigns you to a concrete class and subject, that class roster will appear here."
              />
            ) : (
              <>
                <div className="grid gap-3 md:grid-cols-2">
                  <SelectField
                    label="Subject"
                    value={selectedSubjectId}
                    onChange={setSelectedSubjectId}
                  >
                    {subjectOptions.map((subject) => (
                      <option key={subject.id} value={subject.id}>
                        {subject.label}
                      </option>
                    ))}
                  </SelectField>
                  <SelectField
                    label="Class for that subject"
                    value={selectedAssignmentId}
                    onChange={setSelectedAssignmentId}
                  >
                    {filteredAssignments.map((assignment) => (
                      <option key={assignment.id} value={assignment.id}>
                        {assignment.class_name} {assignment.class_arm || ""}
                      </option>
                    ))}
                  </SelectField>
                </div>
                <RosterList
                  title={
                    selectedAssignment
                      ? assignmentLabel(selectedAssignment)
                      : "Subject roster"
                  }
                  students={subjectStudents}
                  isLoading={isRosterLoading}
                  empty="No students found for this teaching assignment."
                />
              </>
            )}
          </Card>
        ) : (
          <Card className="p-4 sm:p-5">
            {classTeacherClasses.length === 0 ? (
              <EmptyState
                icon={Users}
                title="No class-teacher class"
                description="You are not assigned as a class teacher, so full class oversight features are hidden."
              />
            ) : (
              <>
                <div className="max-w-xl">
                  <SelectField
                    label="Class you oversee"
                    value={selectedClassId}
                    onChange={setSelectedClassId}
                  >
                    {classTeacherClasses.map((item) => (
                      <option key={item.id} value={item.id}>
                        {classLabel(item)}
                      </option>
                    ))}
                  </SelectField>
                </div>
                <RosterList
                  title="Full class roster"
                  students={classStudents}
                  empty="No students found in this class."
                />
              </>
            )}
          </Card>
        )}
      </section>
    </DashboardLayout>
  );
}

function RosterList({ title, students, empty, isLoading = false }) {
  const [search, setSearch] = useState("");
  const visibleStudents = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return students;
    return students.filter((student) =>
      [
        studentName(student),
        student.admission_number,
        student.class_name,
        student.class_arm,
      ].some((value) => String(value || "").toLowerCase().includes(term)),
    );
  }, [search, students]);
  const activeCount = visibleStudents.filter(
    (student) => String(student.status).toLowerCase() === "active",
  ).length;
  const maleCount = visibleStudents.filter(
    (student) => String(student.gender).toLowerCase() === "male",
  ).length;
  const femaleCount = visibleStudents.filter(
    (student) => String(student.gender).toLowerCase() === "female",
  ).length;

  return (
    <div className="mt-5 space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-sm font-semibold text-text">{title}</p>
          <p className="mt-1 text-xs text-text-muted">
            Search and scan the students available in this roster.
          </p>
        </div>
        <div className="relative w-full lg:max-w-sm">
          <Search className="pointer-events-none absolute left-4 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-text-muted" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search name or admission number"
            className="pl-11"
            aria-label="Search roster"
          />
        </div>
      </div>
      {isLoading ? <LoadingState label="Loading students..." /> : null}
      {!isLoading && students.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface-muted/20 px-4 py-5 text-sm text-text-muted">
          {empty}
        </div>
      ) : null}
      {!isLoading && students.length > 0 ? (
        <>
          <DirectorySummary
            items={[
              {
                label: "Visible students",
                value: visibleStudents.length,
                detail: search ? `of ${students.length}` : "in roster",
                icon: Users,
                tone: "primary",
              },
              {
                label: "Active",
                value: activeCount,
                detail: "visible",
                icon: UserCheck,
                tone: "success",
              },
              {
                label: "Male",
                value: maleCount,
                detail: "visible",
                icon: UserRound,
              },
              {
                label: "Female",
                value: femaleCount,
                detail: "visible",
                icon: UserRound,
              },
            ]}
          />

          {visibleStudents.length === 0 ? (
            <div className="rounded-xl border border-border bg-surface-muted/20 px-4 py-5 text-sm text-text-muted">
              No students match your search.
            </div>
          ) : (
            <>
              <DirectoryTable
                label={`${title} students`}
                columns={[
                  { key: "student", label: "Student" },
                  { key: "class", label: "Class" },
                  { key: "gender", label: "Gender" },
                  { key: "status", label: "Status" },
                ]}
              >
                {visibleStudents.map((student) => (
                  <tr
                    key={student.id}
                    className="transition hover:bg-surface-muted/25"
                  >
                    <td className="px-4 py-3.5 align-middle">
                      <PersonIdentity
                        name={studentName(student)}
                        meta={student.admission_number || "No admission number"}
                      />
                    </td>
                    <td className="px-4 py-3.5 text-sm text-text-soft">
                      {[student.class_name, student.class_arm]
                        .filter(Boolean)
                        .join(" ") || "Current roster"}
                    </td>
                    <td className="px-4 py-3.5 text-sm capitalize text-text-soft">
                      {student.gender || "Not set"}
                    </td>
                    <td className="px-4 py-3.5">
                      <Badge
                        variant={
                          student.status === "active" ? "success" : "warning"
                        }
                      >
                        {student.status || "Student"}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </DirectoryTable>

              <MobileDirectoryList label={`${title} students`}>
                {visibleStudents.map((student) => (
                  <MobilePersonCard key={student.id}>
                    <div className="flex items-start justify-between gap-3">
                      <PersonIdentity
                        name={studentName(student)}
                        meta={student.admission_number || "No admission number"}
                      />
                      <Badge
                        variant={
                          student.status === "active" ? "success" : "warning"
                        }
                      >
                        {student.status || "Student"}
                      </Badge>
                    </div>
                    <div className="mt-3 flex items-center justify-between rounded-xl bg-surface-muted/35 px-3 py-2 text-xs text-text-muted">
                      <span>
                        {[student.class_name, student.class_arm]
                          .filter(Boolean)
                          .join(" ") || "Current roster"}
                      </span>
                      <span className="capitalize">
                        {student.gender || "Gender not set"}
                      </span>
                    </div>
                  </MobilePersonCard>
                ))}
              </MobileDirectoryList>
            </>
          )}
        </>
      ) : null}
    </div>
  );
}

export default StudentsPage;
