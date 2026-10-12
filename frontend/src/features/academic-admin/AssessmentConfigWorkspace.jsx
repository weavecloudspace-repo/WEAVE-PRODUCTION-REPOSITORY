import { ArrowDown, ArrowUp, CheckCircle2, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import { useToast } from "../../hooks/useToast";
import { academicService } from "../../services/academicService";
import { getErrorMessage } from "../../services/api";
import { Input, WorkspacePanel } from "./AcademicWorkspacePrimitives";
import TypedConfirmationDialog from "./TypedConfirmationDialog";

const blankComponent = (position) => ({
  name: "",
  code: "",
  maximum_score: "",
  position,
  is_examinable: true,
});
const newDraft = () => ({ id: null, name: "", components: [blankComponent(0)] });

function AssessmentConfigWorkspace() {
  const [schemes, setSchemes] = useState([]);
  const [draft, setDraft] = useState(newDraft);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const { showSuccess, showError, showWarning } = useToast();

  const loadSchemes = useCallback(async () => {
    setLoading(true);
    try {
      const response = await academicService.listAssessmentSchemes();
      setSchemes(response?.items || []);
    } catch (error) {
      showError(getErrorMessage(error, "Could not load assessment schemes."));
    } finally {
      setLoading(false);
    }
  }, [showError]);

  useEffect(() => void loadSchemes(), [loadSchemes]);

  const active = schemes.find((item) => item.status === "active");
  const total = useMemo(
    () => draft.components.reduce((sum, item) => sum + (Number(item.maximum_score) || 0), 0),
    [draft.components],
  );

  const selectScheme = (scheme) => {
    setEditorOpen(true);
    setDraft({
      id: scheme.id,
      name: scheme.name,
      components: scheme.components.map((item, position) => ({
        ...item,
        position,
        is_examinable: item.is_examinable !== false,
      })),
    });
  };

  const updateComponent = (index, field, value) => {
    setDraft((current) => ({
      ...current,
      components: current.components.map((item, itemIndex) =>
        itemIndex === index ? { ...item, [field]: value } : item,
      ),
    }));
  };

  const moveComponent = (index, direction) => {
    const target = index + direction;
    if (target < 0 || target >= draft.components.length) return;
    setDraft((current) => {
      const components = [...current.components];
      [components[index], components[target]] = [components[target], components[index]];
      return { ...current, components: components.map((item, position) => ({ ...item, position })) };
    });
  };

  const validate = ({ requireTotal = false } = {}) => {
    if (!draft.name.trim()) return showWarning("Enter a scheme name."), false;
    if (!draft.components.length) return showWarning("Add at least one component."), false;
    if (draft.components.some((item) => !item.name.trim() || Number(item.maximum_score) <= 0)) {
      return showWarning("Every component needs a name and a maximum above zero."), false;
    }
    if (requireTotal && total !== 100) {
      return showWarning("Component maximums must total 100 before activation."), false;
    }
    return true;
  };

  const saveDraft = async () => {
    if (!validate()) return null;
    setSaving(true);
    try {
      let saved;
      if (!draft.id) {
        saved = await academicService.createAssessmentScheme({
          name: draft.name.trim(),
          components: draft.components.map((item, position) => ({
            name: item.name.trim(),
            code: item.code?.trim() || null,
            maximum_score: Number(item.maximum_score),
            position,
            is_examinable: item.is_examinable !== false,
          })),
        });
      } else {
        const original = schemes.find((item) => item.id === draft.id);
        saved = await academicService.updateAssessmentScheme(draft.id, { name: draft.name.trim() });
        const draftIds = new Set(draft.components.map((item) => item.id).filter(Boolean));
        for (const item of original?.components || []) {
          if (!draftIds.has(item.id)) {
            saved = await academicService.removeAssessmentComponent(draft.id, item.id);
          }
        }
        const orderedIds = [];
        for (let position = 0; position < draft.components.length; position += 1) {
          const item = draft.components[position];
          if (item.id) {
            saved = await academicService.updateAssessmentComponent(draft.id, item.id, {
              name: item.name.trim(),
              code: item.code?.trim() || null,
              maximum_score: Number(item.maximum_score),
              is_examinable: item.is_examinable !== false,
            });
            orderedIds.push(item.id);
          } else {
            saved = await academicService.addAssessmentComponent(draft.id, {
              name: item.name.trim(),
              code: item.code?.trim() || null,
              maximum_score: Number(item.maximum_score),
              position: 1000 + position,
              is_examinable: item.is_examinable !== false,
            });
            const created = saved.components.find((component) =>
              component.name === item.name.trim() && !orderedIds.includes(component.id));
            if (created) orderedIds.push(created.id);
          }
        }
        saved = await academicService.reorderAssessmentComponents(draft.id, orderedIds);
      }
      showSuccess("Assessment scheme saved as a draft.");
      await loadSchemes();
      selectScheme(saved);
      return saved;
    } catch (error) {
      showError(getErrorMessage(error, "Could not save the assessment scheme."));
      return null;
    } finally {
      setSaving(false);
    }
  };

  const activate = async () => {
    const saved = await saveDraft();
    if (!saved) return;
    setSaving(true);
    try {
      await academicService.activateAssessmentScheme(saved.id);
      setConfirming(false);
      setDraft(newDraft());
      setEditorOpen(false);
      await loadSchemes();
      showSuccess("Assessment scheme activated.");
    } catch (error) {
      showError(getErrorMessage(error, "Could not activate the assessment scheme."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <WorkspacePanel
        title="Active assessment scheme"
        description="The component order and maximums used throughout result entry and report cards. Only examinable components are projected to CBT."
        actions={!editorOpen ? (
          <Button type="button" disabled={loading || saving} onClick={() => { setDraft(newDraft()); setEditorOpen(true); }}>
            Create assessment scheme
          </Button>
        ) : null}
      >
        {loading ? <p className="text-sm text-text-muted">Loading assessment schemes...</p> : active ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3"><p className="font-semibold text-text">{active.name}</p><Badge variant="success">Active</Badge></div>
            <ComponentSummary components={active.components} />
          </div>
        ) : <p className="text-sm text-text-muted">No assessment scheme is active yet.</p>}
      </WorkspacePanel>

      {editorOpen ? <WorkspacePanel
        title={draft.id ? "Edit draft scheme" : "Create assessment scheme"}
        description="Build the scoring structure in its persisted order. Examinable components sync to CBT; manual components remain in Weave for teacher/admin score entry. Activation requires a total of 100."
        onBack={() => { setEditorOpen(false); setDraft(newDraft()); }}
        backDisabled={saving}
      >
        <fieldset disabled={saving} className="space-y-4">
          <Input label="Scheme name" value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} />
          <div className="space-y-2">
            {draft.components.map((item, index) => (
              <div key={item.id || `new-${index}`} className="grid gap-2 rounded-xl border border-border p-3 sm:grid-cols-[minmax(0,1fr)_8rem_7rem_9rem_auto] sm:items-end">
                <Input label="Component" value={item.name} onChange={(event) => updateComponent(index, "name", event.target.value)} />
                <Input label="Code" value={item.code || ""} onChange={(event) => updateComponent(index, "code", event.target.value)} />
                <Input label="Maximum" type="number" min="0.01" max="100" step="0.01" value={item.maximum_score} onChange={(event) => updateComponent(index, "maximum_score", event.target.value)} />
                <label className="flex h-10 items-center gap-2 rounded-lg border border-border bg-surface px-3 text-sm text-text">
                  <input
                    type="checkbox"
                    checked={item.is_examinable !== false}
                    onChange={(event) => updateComponent(index, "is_examinable", event.target.checked)}
                    className="h-4 w-4 rounded border-border"
                  />
                  Examinable
                </label>
                <div className="flex gap-1">
                  <Button type="button" variant="ghost" aria-label="Move up" onClick={() => moveComponent(index, -1)}><ArrowUp className="h-4 w-4" /></Button>
                  <Button type="button" variant="ghost" aria-label="Move down" onClick={() => moveComponent(index, 1)}><ArrowDown className="h-4 w-4" /></Button>
                  <Button type="button" variant="ghost" aria-label="Remove component" onClick={() => setDraft((current) => ({ ...current, components: current.components.filter((_, itemIndex) => itemIndex !== index).map((component, position) => ({ ...component, position })) }))}><Trash2 className="h-4 w-4" /></Button>
                </div>
              </div>
            ))}
          </div>
          <p className="text-xs text-text-muted">Examinable components are CBT/admin-managed. Turn this off for teacher-entered components such as note marks, classwork, or other manual assessments.</p>
          <div className={`rounded-xl border px-4 py-3 text-sm ${total === 100 ? "border-success/30 bg-success/5 text-success" : "border-error/30 bg-error/5 text-error"}`}>Configured total: <strong>{total} / 100</strong></div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={() => setDraft((current) => ({ ...current, components: [...current.components, blankComponent(current.components.length)] }))}><Plus className="mr-2 h-4 w-4" />Add component</Button>
            <Button type="button" disabled={saving} onClick={saveDraft}>Save draft</Button>
            <Button type="button" variant="outline" disabled={saving || total !== 100} onClick={() => validate({ requireTotal: true }) && setConfirming(true)}><CheckCircle2 className="mr-2 h-4 w-4" />Activate</Button>
            <Button type="button" variant="ghost" onClick={() => setDraft(newDraft())}>New scheme</Button>
          </div>
        </fieldset>
      </WorkspacePanel> : null}

      {schemes.some((item) => item.status === "draft") ? <WorkspacePanel title="Saved drafts" description="Continue a mutable draft or activate it when its components total 100."><div className="flex flex-wrap gap-2">{schemes.filter((item) => item.status === "draft").map((item) => <Button key={item.id} type="button" variant="outline" disabled={saving} onClick={() => selectScheme(item)}>{item.name} · {item.total_maximum_score}/100</Button>)}</div></WorkspacePanel> : null}

      {schemes.some((item) => item.status === "archived") ? <WorkspacePanel title="Archived schemes" description="Historical schemes remain immutable because academic records may reference their component IDs."><div className="space-y-2">{schemes.filter((item) => item.status === "archived").map((item) => <div key={item.id} className="flex items-center justify-between gap-3 rounded-xl border border-border/70 px-4 py-3"><span className="font-medium text-text">{item.name}</span><Badge variant="default">{item.components.length} components</Badge></div>)}</div></WorkspacePanel> : null}

      <TypedConfirmationDialog open={confirming} title="Activate assessment scheme" description="This scheme will become authoritative for new result entry. An active scheme already used in the current open term cannot be replaced." confirmationText="ACTIVATE_ASSESSMENT_SCHEME" confirmLabel="Activate scheme" isLoading={saving} onConfirm={activate} onCancel={() => setConfirming(false)} />
    </div>
  );
}

function ComponentSummary({ components = [] }) {
  return <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{components.map((item) => <div key={item.id} className="rounded-xl bg-surface-muted/40 px-4 py-3"><div className="flex items-start justify-between gap-2"><p className="text-xs uppercase tracking-wide text-text-muted">{item.name}</p><Badge variant={item.is_examinable === false ? "default" : "info"}>{item.is_examinable === false ? "Manual" : "CBT"}</Badge></div><p className="mt-1 text-xl font-semibold text-text">{item.maximum_score}</p></div>)}</div>;
}

export default AssessmentConfigWorkspace;
