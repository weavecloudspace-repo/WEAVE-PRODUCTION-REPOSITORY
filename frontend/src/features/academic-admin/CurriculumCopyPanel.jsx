import { useEffect, useState } from "react";
import Button from "../../components/ui/Button";
import { curriculumService } from "../../services/curriculumService";
import { getErrorMessage } from "../../services/api";
import { SelectControl, WorkspacePanel } from "./AcademicWorkspacePrimitives";
import { curriculumCopyPreview, curriculumCopySources } from "./curriculumCopy";

export default function CurriculumCopyPanel({ levels, target, targetSubjects, targetDepartments, saving, onCopy, onCancel }) {
  const [sourceId, setSourceId] = useState("");
  const [source, setSource] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const sources = curriculumCopySources(levels, target);
  const preview = curriculumCopyPreview(source?.subjects || [], targetSubjects, targetDepartments);

  useEffect(() => {
    let cancelled = false;
    setSource(null);
    setError("");
    setLoading(Boolean(sourceId));
    if (sourceId) {
      curriculumService.getCurriculum(sourceId).then((data) => {
        if (!cancelled) setSource(data);
      }).catch((err) => {
        if (!cancelled) setError(getErrorMessage(err, "Could not load the source curriculum."));
      }).finally(() => {
        if (!cancelled) setLoading(false);
      });
    }
    return () => { cancelled = true; };
  }, [sourceId, retry]);

  return (
    <WorkspacePanel
      title="Copy curriculum"
      description={`Add subjects to ${target.name} from another level in the same category.`}
      onBack={onCancel}
      backDisabled={saving}
    >
      <form className="space-y-4" onSubmit={(event) => {
        event.preventDefault();
        if (!loading && source && preview.missing.length && !preview.unavailableDepartments.length) onCopy(event, sourceId);
      }}>
        <fieldset disabled={saving} className="space-y-4">
          <SelectControl label="Copy from" value={sourceId} onChange={(value) => {
            setSource(null);
            setSourceId(value);
          }} options={sources.map((level) => ({ value: level.id, label: level.name }))} placeholder="Choose a level" required />
          {!sources.length ? <p className="text-sm text-text-muted">Activate another level in this category to copy its curriculum.</p> : null}
          <p className="text-sm leading-6 text-text-muted">Only active subjects are copied, including compulsory/elective status and department applicability. Existing subjects stay unchanged. Teacher assignments are not copied.</p>
          {loading ? <p role="status" className="text-sm text-text-muted">Loading curriculum preview…</p> : null}
          {error ? <div role="alert" className="space-y-2 text-sm text-error">{error}<Button type="button" variant="outline" onClick={() => setRetry((value) => value + 1)}>Retry</Button></div> : null}
          {source && !loading ? (
            <div className="space-y-3">
              <p className="text-sm font-semibold text-text">{preview.missing.length} subjects to add · {preview.existingCount} already present</p>
              {preview.missing.length ? (
                <ul className="max-h-64 divide-y divide-border overflow-y-auto rounded-xl border border-border px-3">
                  {preview.missing.map((row) => <li key={row.id} className="py-3 text-sm">
                    <p className="font-medium text-text">{row.subject_name}</p>
                    <p className="mt-1 text-xs text-text-muted">{row.is_elective ? "Elective" : "Compulsory"} · {(row.departments || []).map((department) => department.department_name).join(", ") || "General"}</p>
                  </li>)}
                </ul>
              ) : <p className="text-sm text-text-muted">No new active curriculum subjects to copy.</p>}
              {preview.unavailableDepartments.length ? <p role="alert" className="text-sm text-warning">Enable these departments on {target.name} before copying: {preview.unavailableDepartments.join(", ")}. No subjects will be copied until this is resolved.</p> : null}
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={loading || !source || !preview.missing.length || Boolean(preview.unavailableDepartments.length)}>{saving ? "Copying…" : "Copy curriculum"}</Button>
            <Button type="button" variant="outline" onClick={onCancel}>Cancel</Button>
          </div>
        </fieldset>
      </form>
    </WorkspacePanel>
  );
}
