import {
  BookOpen,
  LayoutGrid,
  List,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import DashboardLayout from "../../components/layout/DashboardLayout";
import EmptyState from "../../components/shared/EmptyState";
import LoadingState from "../../components/shared/LoadingState";
import StudentElectiveSelectionPanel from "../../components/student/StudentElectiveSelectionPanel";
import StudentSubjectPerformanceCard from "../../components/student/StudentSubjectPerformanceCard";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import Input from "../../components/ui/Input";
import Modal from "../../components/ui/Modal";
import { academicService } from "../../services/academicService";
import { getErrorMessage } from "../../services/api";
import { cleanText } from "../../utils/academicDashboard";
import { cn } from "../../utils/cn";

function StudentSubjectsPage() {
  const [subjectCards, setSubjectCards] = useState([]);
  const [context, setContext] = useState(null);
  const [electiveWorkspace, setElectiveWorkspace] = useState(null);
  const [viewMode, setViewMode] = useState("grid");
  const [search, setSearch] = useState("");
  const [sortOrder, setSortOrder] = useState("asc");
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [electiveError, setElectiveError] = useState(null);
  const [refreshNotice, setRefreshNotice] = useState(null);
  const [electivesOpen, setElectivesOpen] = useState(false);
  const [electiveState, setElectiveState] = useState({
    saving: false,
    dirty: false,
  });
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  useEffect(() => {
    let mounted = true;
    async function loadSubjects() {
      const [subjects, electives] = await Promise.allSettled([
        academicService.listMySubjectCards(),
        academicService.getMyElectiveWorkspace(),
      ]);
      if (!mounted) return;
      if (subjects.status === "fulfilled") {
        setSubjectCards(subjects.value?.items || []);
        setContext(subjects.value?.context || null);
      } else {
        setLoadError(
          getErrorMessage(subjects.reason, "Failed to load subjects."),
        );
      }
      if (electives.status === "fulfilled") {
        setElectiveWorkspace(electives.value || null);
      } else {
        setElectiveError(
          getErrorMessage(
            electives.reason,
            "Elective choices could not be loaded. Please reopen this page to try again.",
          ),
        );
      }
      setIsLoading(false);
    }
    loadSubjects();
    return () => {
      mounted = false;
    };
  }, []);

  const refreshSubjects = async () => {
    const response = await academicService.listMySubjectCards();
    setSubjectCards(response?.items || []);
    setContext(response?.context || null);
    setLoadError(null);
    setRefreshNotice(null);
  };

  const handleElectiveSave = async (electiveGroupId, curriculumSubjectIds) => {
    let updatedWorkspace;
    try {
      updatedWorkspace = await academicService.updateMyElectiveSelection(
        electiveGroupId,
        curriculumSubjectIds,
      );
    } catch (error) {
      throw new Error(
        getErrorMessage(error, "Failed to save elective choices."),
        { cause: error },
      );
    }
    setElectiveWorkspace(updatedWorkspace);
    try {
      await refreshSubjects();
    } catch {
      // The write succeeded; a failed read must not report it as an unsaved choice.
      setRefreshNotice(
        "Your elective choices are saved. The subject list could not refresh; reload it to see your updated subjects.",
      );
    }
    return updatedWorkspace;
  };

  const closeElectives = () => {
    if (electiveState.saving) return;
    if (electiveState.dirty) {
      setConfirmDiscard(true);
      return;
    }
    setElectivesOpen(false);
  };

  const electiveGroups = electiveWorkspace?.groups || [];
  const electiveNames = useMemo(
    () =>
      new Map(
        (electiveWorkspace?.groups || []).flatMap((group) =>
          group.subjects
            .filter((subject) => subject.selected)
            .map((subject) => [subject.curriculum_subject_id, group.name]),
        ),
      ),
    [electiveWorkspace],
  );
  const visibleSubjects = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return subjectCards
      .filter((card) =>
        [card.subject_name, card.subject_code, card.teacher_name].some(
          (value) =>
            String(value || "")
              .toLocaleLowerCase()
              .includes(query),
        ),
      )
      .sort(
        (a, b) =>
          String(a.subject_name || "").localeCompare(
            String(b.subject_name || ""),
          ) * (sortOrder === "asc" ? 1 : -1),
      );
  }, [search, sortOrder, subjectCards]);
  const classLabel = cleanText(
    context?.class_name
      ? [context.class_name, context.class_arm].filter(Boolean).join(" ")
      : null,
    context?.class_id ? "Class" : "No class assigned",
  );
  const academicContextLabel = `${cleanText(context?.academic_session_name, "No session")} / ${cleanText(context?.academic_term_name, "No term")} / ${classLabel}`;
  const isGridView = viewMode === "grid";

  if (isLoading)
    return (
      <DashboardLayout role="student" title="Subjects">
        <LoadingState label="Loading subjects..." />
      </DashboardLayout>
    );

  return (
    <DashboardLayout
      role="student"
      title="Subjects"
      description={academicContextLabel}
      actions={
        (electiveGroups.length > 0 || electiveError) && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setConfirmDiscard(false);
              setElectivesOpen(true);
            }}
            aria-haspopup="dialog"
          >
            <SlidersHorizontal className="h-4 w-4" aria-hidden="true" /> Manage
            electives
          </Button>
        )
      }
    >
      <Card
        as="section"
        aria-label="My subjects"
        className="student-subject-page-shell space-y-4 p-3 sm:p-5"
      >
        <div className="border-b border-border/70 pb-3">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="sr-only shrink-0 text-sm font-semibold text-text sm:not-sr-only">
              My subjects{" "}
              <span className="ml-1 text-text-muted">
                ({subjectCards.length})
              </span>
            </h2>
            <div className="relative min-w-0 flex-1 basis-full sm:basis-40 lg:max-w-xs">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
                aria-hidden="true"
              />
              <Input
                type="search"
                aria-label="Search subjects"
                placeholder="Search subjects"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="min-h-11 py-2 pl-9 sm:min-h-10"
              />
            </div>
            <div className="ml-auto flex w-full items-center gap-2 sm:w-auto">
              <select
                aria-label="Sort subjects"
                className="input-base min-h-11 w-auto min-w-0 flex-1 py-2 sm:min-h-10 sm:flex-none"
                value={sortOrder}
                onChange={(event) => setSortOrder(event.target.value)}
              >
                <option value="asc">Name: A to Z</option>
                <option value="desc">Name: Z to A</option>
              </select>
              <div className="inline-flex shrink-0 rounded-xl border border-border p-1">
                <Button
                  type="button"
                  variant={isGridView ? "primary" : "ghost"}
                  size="sm"
                  onClick={() => setViewMode("grid")}
                  aria-label="Show subjects as cards"
                  aria-pressed={isGridView}
                  className="min-h-11 min-w-11 px-2 sm:min-h-9 sm:min-w-9"
                >
                  <LayoutGrid className="h-4 w-4" />
                </Button>
                <Button
                  type="button"
                  variant={!isGridView ? "primary" : "ghost"}
                  size="sm"
                  onClick={() => setViewMode("list")}
                  aria-label="Show subjects as a list"
                  aria-pressed={!isGridView}
                  className="min-h-11 min-w-11 px-2 sm:min-h-9 sm:min-w-9"
                >
                  <List className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>
        </div>
        {loadError && (
          <div
            role="alert"
            className="rounded-xl border border-error/30 bg-error-soft px-4 py-3 text-sm text-error"
          >
            {loadError}
          </div>
        )}
        {refreshNotice && (
          <div
            role="status"
            className="rounded-xl border border-border bg-surface px-4 py-3 text-sm text-text-muted"
          >
            {refreshNotice}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="ml-2"
              onClick={() =>
                refreshSubjects().catch(() =>
                  setRefreshNotice(
                    "Your choices are saved, but the subject list is still unavailable. Please try again.",
                  ),
                )
              }
            >
              Reload subjects
            </Button>
          </div>
        )}
        {!loadError && subjectCards.length === 0 && (
          <Card className="p-6">
            <EmptyState
              icon={BookOpen}
              title="No subjects available"
              description={
                context?.class_id
                  ? "Your subjects will appear here once the school assigns them. Use Manage electives to choose any available electives."
                  : "No class has been assigned to your student profile yet."
              }
            />
          </Card>
        )}
        {!loadError && subjectCards.length > 0 && (
          <>
            <p role="status" className="text-sm text-text-muted">
              {visibleSubjects.length} of {subjectCards.length} subjects
            </p>
            {visibleSubjects.length ? (
              <div
                className={cn(
                  "grid gap-4",
                  isGridView
                    ? "grid-cols-1 lg:grid-cols-3"
                    : "grid-cols-1",
                )}
              >
                {visibleSubjects.map((card) => (
                  <StudentSubjectPerformanceCard
                    key={card.id}
                    card={card}
                    classLabel={classLabel}
                    electiveGroupName={electiveNames.get(
                      card.curriculum_subject_id,
                    )}
                    compact={!isGridView}
                  />
                ))}
              </div>
            ) : (
              <Card className="p-6">
                <EmptyState
                  icon={Search}
                  title="No matching subjects"
                  description="Try a different subject name, code or teacher."
                />
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setSearch("")}
                >
                  Clear search
                </Button>
              </Card>
            )}
          </>
        )}
      </Card>
      <Modal
        open={electivesOpen}
        title="Manage electives"
        description="Choose the subjects you want to study within each group."
        onClose={closeElectives}
        closeOnOverlay={!electiveState.saving}
        showClose={!electiveState.saving}
        className="max-w-3xl"
        footer={
          confirmDiscard ? (
            <div className="space-y-3">
              <p className="text-sm text-text" role="alert">
                Discard your unsaved choices? Saved groups will stay unchanged.
              </p>
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setConfirmDiscard(false)}
                >
                  Keep editing
                </Button>
                <Button
                  type="button"
                  disabled={electiveState.saving}
                  onClick={() => {
                    setElectivesOpen(false);
                    setConfirmDiscard(false);
                  }}
                >
                  Discard changes
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-text-muted">
                {electiveState.dirty
                  ? "You have unsaved choices."
                  : "Save each group to update your subjects."}
              </p>
              <Button
                type="button"
                variant="outline"
                disabled={electiveState.saving}
                onClick={closeElectives}
              >
                Done
              </Button>
            </div>
          )
        }
      >
        {electiveError ? (
          <p role="alert" className="text-sm text-error">
            {electiveError}
          </p>
        ) : (
          electivesOpen && (
            <StudentElectiveSelectionPanel
              workspace={electiveWorkspace}
              onSave={handleElectiveSave}
              onStateChange={setElectiveState}
            />
          )
        )}
      </Modal>
    </DashboardLayout>
  );
}

export default StudentSubjectsPage;
