import { Check, CheckCircle2, LockKeyhole } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import Button from "../ui/Button";

const selectedFromGroup = (group) =>
  (group?.subjects || [])
    .filter((subject) => subject.selected)
    .map((subject) => subject.curriculum_subject_id);

export default function StudentElectiveSelectionPanel({
  workspace,
  onSave,
  onStateChange,
}) {
  const groups = useMemo(() => workspace?.groups || [], [workspace]);
  // This panel mounts when the manager opens. Keep other groups' drafts when a save refreshes the workspace.
  const [selectedByGroup, setSelectedByGroup] = useState(() =>
    Object.fromEntries(
      groups.map((group) => [
        group.elective_group_id,
        selectedFromGroup(group),
      ]),
    ),
  );
  const [savingGroupId, setSavingGroupId] = useState("");
  const [errorByGroup, setErrorByGroup] = useState({});
  const [savedGroupId, setSavedGroupId] = useState("");
  const originalByGroup = useMemo(
    () =>
      Object.fromEntries(
        groups.map((group) => [
          group.elective_group_id,
          selectedFromGroup(group),
        ]),
      ),
    [groups],
  );
  const dirty = groups.some((group) => {
    const selected = selectedByGroup[group.elective_group_id] || [];
    const original = originalByGroup[group.elective_group_id] || [];
    return (
      selected.length !== original.length ||
      selected.some((id) => !original.includes(id))
    );
  });
  const saving = Boolean(savingGroupId);
  useEffect(() => {
    onStateChange?.({ saving, dirty });
  }, [onStateChange, saving, dirty]);

  const toggleSubject = (group, subjectId) => {
    if (group.locked || savingGroupId) return;
    setSelectedByGroup((current) => {
      const selected = new Set(current[group.elective_group_id] || []);
      if (selected.has(subjectId)) selected.delete(subjectId);
      else {
        if (selected.size >= group.maximum_choices) return current;
        selected.add(subjectId);
      }
      return { ...current, [group.elective_group_id]: [...selected] };
    });
    setSavedGroupId("");
    setErrorByGroup((current) => ({
      ...current,
      [group.elective_group_id]: "",
    }));
  };

  const saveGroup = async (group) => {
    if (group.locked || savingGroupId) return;
    const selected = selectedByGroup[group.elective_group_id] || [];
    if (
      selected.length < group.minimum_choices ||
      selected.length > group.maximum_choices
    ) {
      setErrorByGroup((current) => ({
        ...current,
        [group.elective_group_id]: `Choose between ${group.minimum_choices} and ${group.maximum_choices} subjects.`,
      }));
      return;
    }
    setSavingGroupId(group.elective_group_id);
    setSavedGroupId("");
    setErrorByGroup((current) => ({
      ...current,
      [group.elective_group_id]: "",
    }));
    try {
      const updatedWorkspace = await onSave(group.elective_group_id, selected);
      const updatedGroup = updatedWorkspace?.groups?.find(
        (item) => item.elective_group_id === group.elective_group_id,
      );
      setSelectedByGroup((current) => ({
        ...current,
        [group.elective_group_id]: updatedGroup
          ? selectedFromGroup(updatedGroup)
          : selected,
      }));
      setSavedGroupId(group.elective_group_id);
    } catch (error) {
      setErrorByGroup((current) => ({
        ...current,
        [group.elective_group_id]:
          error?.message || "We could not save your elective choices.",
      }));
    } finally {
      setSavingGroupId("");
    }
  };

  return (
    <div className="space-y-5">
      <p className="rounded-xl bg-surface-muted/50 px-4 py-3 text-sm leading-6 text-text-muted">
        Your choices carry across terms. A group becomes locked once a score is
        recorded for one of its subjects in the current term.
      </p>
      {groups.map((group) => {
        const selected = selectedByGroup[group.elective_group_id] || [];
        const original = originalByGroup[group.elective_group_id] || [];
        const changed =
          selected.length !== original.length ||
          selected.some((id) => !original.includes(id));
        const groupSaving = savingGroupId === group.elective_group_id;
        const atLimit = selected.length >= group.maximum_choices;
        const rangeLabel =
          group.minimum_choices === group.maximum_choices
            ? `Choose ${group.maximum_choices}`
            : `Choose ${group.minimum_choices} to ${group.maximum_choices}`;
        return (
          <section
            key={group.elective_group_id}
            aria-label={group.name}
            className="overflow-hidden rounded-2xl border border-border"
          >
            <div className="border-b border-border bg-surface-muted/20 px-4 py-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <h3 className="text-base font-semibold text-text">
                  {group.name}
                </h3>
                {group.locked && (
                  <span className="inline-flex items-center gap-1 text-xs font-semibold text-text-muted">
                    <LockKeyhole className="h-3.5 w-3.5" aria-hidden="true" />{" "}
                    Locked
                  </span>
                )}
              </div>
              <p className="mt-1 text-sm text-text-muted">
                {rangeLabel} / {selected.length} selected
              </p>
            </div>
            <div className="space-y-3 p-4">
              {group.locked && (
                <p className="text-sm leading-6 text-text-muted">
                  {group.locked_reason ||
                    "Your school has locked this group for the current term."}
                </p>
              )}
              <div className="grid gap-2 sm:grid-cols-2">
                {(group.subjects || []).map((subject) => {
                  const checked = selected.includes(
                    subject.curriculum_subject_id,
                  );
                  return (
                    <button
                      key={subject.curriculum_subject_id}
                      type="button"
                      aria-pressed={checked}
                      disabled={group.locked || saving || (!checked && atLimit)}
                      onClick={() =>
                        toggleSubject(group, subject.curriculum_subject_id)
                      }
                      className={`flex min-h-16 items-center gap-3 rounded-xl border px-3 py-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${checked ? "border-primary/50 bg-primary-soft/40" : "border-border bg-surface hover:border-primary/30"} disabled:cursor-not-allowed disabled:opacity-70`}
                    >
                      <span
                        className={`grid h-6 w-6 shrink-0 place-items-center rounded-md border ${checked ? "border-primary bg-primary text-white" : "border-border bg-surface"}`}
                        aria-hidden="true"
                      >
                        {checked && <Check className="h-4 w-4" />}
                      </span>
                      <span className="min-w-0">
                        <span className="block break-words text-sm font-semibold text-text">
                          {subject.subject_name}
                        </span>
                        {subject.subject_code && (
                          <span className="mt-1 block text-xs text-text-muted">
                            {subject.subject_code}
                          </span>
                        )}
                      </span>
                    </button>
                  );
                })}
              </div>
              {!group.locked && atLimit && (
                <p className="text-xs leading-5 text-text-muted">
                  All choices filled. Deselect a subject to choose a different
                  one.
                </p>
              )}
              {errorByGroup[group.elective_group_id] && (
                <p role="alert" className="text-sm font-medium text-error">
                  {errorByGroup[group.elective_group_id]}
                </p>
              )}
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/70 pt-3">
                <span
                  role="status"
                  className="inline-flex items-center gap-1.5 text-xs text-text-muted"
                >
                  {savedGroupId === group.elective_group_id ? (
                    <>
                      <CheckCircle2
                        className="h-4 w-4 text-primary"
                        aria-hidden="true"
                      />{" "}
                      Choices saved
                    </>
                  ) : changed ? (
                    "Unsaved changes"
                  ) : (
                    `${original.length} saved choices`
                  )}
                </span>
                {!group.locked && (
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => saveGroup(group)}
                    disabled={!changed || saving}
                    aria-label={`Save choices for ${group.name}`}
                  >
                    {groupSaving ? "Saving..." : "Save choices"}
                  </Button>
                )}
              </div>
            </div>
          </section>
        );
      })}
    </div>
  );
}
