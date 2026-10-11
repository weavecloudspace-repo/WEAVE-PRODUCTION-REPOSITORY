import { useState } from "react";

import Button from "../../components/ui/Button";
import { useToast } from "../../hooks/useToast";
import { getErrorMessage } from "../../services/api";
import { curriculumService } from "../../services/curriculumService";
import { Input, WorkspacePanel } from "./AcademicWorkspacePrimitives";

const EMPTY_FORM = {
  name: "",
  minimum_choices: "0",
  maximum_choices: "1",
};

export default function ElectiveGroupManager({
  levelId,
  groups,
  onChanged,
  onCancel,
}) {
  const { showError, showSuccess } = useToast();
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState("");
  const [saving, setSaving] = useState("");

  const activeGroups = groups.filter((group) => group.lifecycle === "ACTIVE");
  const archivedGroups = groups.filter((group) => group.lifecycle === "ARCHIVED");

  const startEdit = (group) => {
    setEditingId(group.id);
    setForm({
      name: group.name,
      minimum_choices: String(group.minimum_choices),
      maximum_choices: String(group.maximum_choices),
    });
  };

  const resetForm = () => {
    setEditingId("");
    setForm(EMPTY_FORM);
  };

  const submit = async (event) => {
    event.preventDefault();
    if (!levelId || saving) return;
    const minimum = Number(form.minimum_choices);
    const maximum = Number(form.maximum_choices);
    if (!form.name.trim() || !Number.isInteger(minimum) || !Number.isInteger(maximum)) {
      showError("Enter a group name and whole-number choice limits.");
      return;
    }
    if (minimum < 0 || maximum < 1 || minimum > maximum) {
      showError("Choice limits must satisfy 0 ≤ minimum ≤ maximum and maximum ≥ 1.");
      return;
    }

    setSaving(editingId || "create");
    try {
      const payload = {
        name: form.name.trim(),
        minimum_choices: minimum,
        maximum_choices: maximum,
      };
      if (editingId) {
        await curriculumService.updateElectiveGroup(editingId, payload);
        showSuccess("Elective group updated.");
      } else {
        await curriculumService.createElectiveGroup(levelId, payload);
        showSuccess("Elective group created.");
      }
      resetForm();
      await onChanged();
    } catch (error) {
      showError(getErrorMessage(error, "Could not save the elective group."));
    } finally {
      setSaving("");
    }
  };

  const changeLifecycle = async (group, action) => {
    if (saving) return;
    setSaving(group.id);
    try {
      if (action === "archive") {
        await curriculumService.archiveElectiveGroup(group.id);
      } else {
        await curriculumService.restoreElectiveGroup(group.id);
      }
      showSuccess(`Elective group ${action === "archive" ? "archived" : "restored"}.`);
      await onChanged();
    } catch (error) {
      showError(
        getErrorMessage(
          error,
          `Could not ${action} the elective group.`,
        ),
      );
    } finally {
      setSaving("");
    }
  };

  return (
    <WorkspacePanel
      title="Manage elective groups"
      description="Groups define how many subjects a student must or may choose. Active elective subjects must belong to an active group."
      onBack={onCancel}
      backDisabled={Boolean(saving)}
    >
      <form className="space-y-3" onSubmit={submit}>
        <fieldset disabled={Boolean(saving)} className="space-y-3">
          <Input
            label="Group name"
            value={form.name}
            onChange={(event) =>
              setForm((current) => ({ ...current, name: event.target.value }))
            }
            placeholder="e.g. Arts electives"
            required
          />
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Minimum choices"
              type="number"
              min="0"
              step="1"
              value={form.minimum_choices}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  minimum_choices: event.target.value,
                }))
              }
              required
            />
            <Input
              label="Maximum choices"
              type="number"
              min="1"
              step="1"
              value={form.maximum_choices}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  maximum_choices: event.target.value,
                }))
              }
              required
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={Boolean(saving)}>
              {saving === (editingId || "create")
                ? "Saving…"
                : editingId
                  ? "Save group"
                  : "Create group"}
            </Button>
            {editingId ? (
              <Button type="button" variant="outline" onClick={resetForm}>
                Cancel edit
              </Button>
            ) : null}
            <Button type="button" variant="outline" onClick={onCancel}>
              Done
            </Button>
          </div>
        </fieldset>
      </form>

      <div className="mt-5 space-y-3">
        {activeGroups.map((group) => (
          <div
            key={group.id}
            className="rounded-xl border border-border bg-surface-muted/30 p-3"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-text">{group.name}</p>
                <p className="mt-1 text-xs text-text-muted">
                  Choose {group.minimum_choices}–{group.maximum_choices}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="small"
                  variant="outline"
                  disabled={Boolean(saving)}
                  onClick={() => startEdit(group)}
                >
                  Edit
                </Button>
                <Button
                  type="button"
                  size="small"
                  variant="outline"
                  disabled={Boolean(saving)}
                  onClick={() => changeLifecycle(group, "archive")}
                >
                  Archive
                </Button>
              </div>
            </div>
          </div>
        ))}
        {!activeGroups.length ? (
          <p className="text-sm text-text-muted">No active elective groups yet.</p>
        ) : null}

        {archivedGroups.length ? (
          <div className="border-t border-border pt-3">
            <p className="mb-2 text-xs font-bold uppercase tracking-wide text-text-muted">
              Archived
            </p>
            <div className="space-y-2">
              {archivedGroups.map((group) => (
                <div
                  key={group.id}
                  className="flex items-center justify-between gap-3 rounded-xl border border-border/70 px-3 py-2"
                >
                  <div>
                    <p className="text-sm font-semibold text-text">{group.name}</p>
                    <p className="text-xs text-text-muted">
                      Choose {group.minimum_choices}–{group.maximum_choices}
                    </p>
                  </div>
                  <Button
                    type="button"
                    size="small"
                    variant="outline"
                    disabled={Boolean(saving)}
                    onClick={() => changeLifecycle(group, "restore")}
                  >
                    Restore
                  </Button>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </WorkspacePanel>
  );
}
