import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Bold,
  Italic,
  Underline,
  Superscript,
  List,
  ListOrdered,
  Link as LinkIcon,
  ImagePlus,
  Trash2,
  Plus,
  Eye,
  Bot,
} from "lucide-react";
import Button from "../../components/ui/Button";
import SearchableSelect from "../../components/ui/SearchableSelect";
import MathText from "./MathText.jsx";
import { formatSelection } from "./textFormatting";
import { tmaService } from "../../services/tmaService";

const tools = [
  ["bold", Bold, "Bold"],
  ["italic", Italic, "Italic"],
  ["underline", Underline, "Underline"],
  ["superscript", Superscript, "Superscript"],
  ["bullet", List, "Bulleted list"],
  ["number", ListOrdered, "Numbered list"],
  ["link", LinkIcon, "Link"],
];
export function TmaAssetImage({ assignmentId, assetId, alt, autoLoad = false }) {
  // Loading by button avoids issuing signed URLs for off-screen editor assets.
  const [url, setUrl] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!autoLoad) return;
    let active = true;
    tmaService.imageUrl(assignmentId, assetId)
      .then((result) => { if (active) setUrl(result.signed_url); })
      .catch((e) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [assignmentId, assetId, autoLoad]);
  return (
    <div>
      {url ? (
        <img
          src={url}
          alt={alt}
          className={`${autoLoad ? "max-h-96" : "max-h-48"} max-w-full rounded-xl object-contain`}
          onError={() => {
            setUrl(null);
            setError("Image expired. Load it again.");
          }}
        />
      ) : autoLoad && !error ? (
        <p role="status" className="py-3 text-sm text-text-muted">Loading illustration…</p>
      ) : (
        <button
          type="button"
          className="min-h-11 text-sm text-primary underline"
          onClick={async () => {
            try {
              const r = await tmaService.imageUrl(assignmentId, assetId);
              setUrl(r.signed_url);
              setError("");
            } catch (e) {
              setError(e.message);
            }
          }}
        >
          View attached image
        </button>
      )}
      {error && (
        <p role="alert" className="text-xs text-error">
          {error}
        </p>
      )}
    </div>
  );
}

export function TextField({
  label,
  value,
  onChange,
  rows = 6,
  compact = false,
  trailingControls = null,
}) {
  const input = useRef(null);
  const apply = (kind) => {
    const el = input.current;
    const next = formatSelection(
      value || "",
      el.selectionStart,
      el.selectionEnd,
      kind,
    );
    onChange(next.value);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(next.start, next.end);
    });
  };
  const toolbar = (
    <div
      className="tma-format-toolbar"
      aria-label={`${label} formatting`}
      role="toolbar"
    >
      {!compact &&
        tools.map(([kind, Icon, name]) => (
          <button
            key={kind}
            type="button"
            title={name}
            aria-label={`${name} in ${label}`}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => apply(kind)}
          >
            <Icon size={16} />
          </button>
        ))}
      <details className="tma-math-picker">
        <summary aria-label={`Insert maths in ${label}`}>Maths</summary>
        <div>
          {[
            "²",
            "³",
            "√",
            "π",
            "θ",
            "±",
            "×",
            "÷",
            "≤",
            "≥",
            "≠",
            "∞",
            "\\(\\frac{a}{b}\\)",
            "\\(x^{2}\\)",
            "\\(\\begin{pmatrix}a & b \\\\ c & d\\end{pmatrix}\\)",
            "\\(\\begin{bmatrix}a & b & c \\\\ d & e & f \\\\ g & h & i\\end{bmatrix}\\)",
            "\\(\\begin{vmatrix}a & b \\\\ c & d\\end{vmatrix}\\)",
          ].map((s) => (
            <button
              key={s}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={(e) => {
                apply(s);
                e.currentTarget.closest("details").open = false;
              }}
            >
              {s.includes("pmatrix")
                ? "Matrix 2 × 2"
                : s.includes("bmatrix")
                  ? "Matrix 3 × 3"
                  : s.includes("vmatrix")
                    ? "Determinant"
                    : s.includes("frac")
                      ? "Fraction"
                      : s.includes("x^")
                        ? "Power"
                        : s}
            </button>
          ))}
        </div>
      </details>
      {trailingControls}
    </div>
  );
  const textarea = (
    <textarea
      ref={input}
      aria-label={label}
      rows={rows}
      value={value || ""}
      onChange={(e) => onChange(e.target.value)}
      placeholder={compact ? "Enter answer…" : "Type your question here…"}
    />
  );
  return (
    <div
      className={`tma-text-field ${compact ? "tma-text-field--compact" : ""}`}
    >
      {compact ? textarea : toolbar}
      {compact ? toolbar : textarea}
    </div>
  );
}

export default function TmaQuestionEditor({
  draft,
  setDraft,
  assets,
  assignmentId,
  busy,
  onSave,
  onDelete,
  onClose,
  onAI,
  onUpload,
}) {
  const [preview, setPreview] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const valid = Boolean(
    (draft.question_text?.trim() || draft.image_asset_id) &&
    draft.options.length >= 4 &&
    draft.options.filter((o) => o.is_correct).length === 1 &&
    draft.options.every((o) => o.option_text?.trim() || o.image_asset_id),
  );
  const patchOption = (i, patch) =>
    setDraft((current) => ({
      ...current,
      options: current.options.map((o, j) =>
        j === i ? { ...o, ...patch } : o,
      ),
    }));
  const imageField = (value, change, label) => (
    <details className="tma-editor-media-panel">
      <summary><ImagePlus size={16} />{value ? "Manage attached image" : "Attach an image"}</summary>
    <div className="tma-editor-media">
      <label>
        <ImagePlus size={16} />
        Upload image
        <input
          type="file"
          aria-label={`Upload ${label.toLowerCase()}`}
          accept="image/jpeg,image/png,image/webp"
          disabled={uploading || busy}
          onChange={async (e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (!file) return;
            if (file.size > 5 * 1024 * 1024) {
              setError("Images must be no larger than 5 MB.");
              return;
            }
            setUploading(true);
            setError("");
            try {
              const asset = await onUpload(file);
              change(asset.id);
            } catch (e) {
              setError(e.message);
            } finally {
              setUploading(false);
            }
          }}
        />
      </label>
      <SearchableSelect
        label={label}
        disabled={busy || uploading}
        value={value || ""}
        onChange={(value) => change(value || null)}
        placeholder="No image attached"
        clearable
        options={assets.map((a, i) => ({
          value: String(a.id),
          label: `Assignment image ${i + 1}`,
        }))}
      />
      {value && (
        <TmaAssetImage
          key={value}
          assignmentId={assignmentId}
          assetId={value}
          alt={label}
        />
      )}
    </div>
    </details>
  );
  return (
    <fieldset className="tma-question-builder min-w-0" disabled={busy}>
      <div className="tma-builder-intro">
        <span className="tma-eyebrow">TMA · Question authoring</span>
        <h1 className="text-lg font-semibold">{draft.id ? "Edit question" : "Create a question"}</h1>
        <p className="text-xs text-text-muted">
          Single choice · Four or more options · Select one correct answer.
        </p>
      </div>
      <header className="tma-builder-toolbar">
        <Button variant="ghost" disabled={busy || uploading} onClick={onClose}>
          <ArrowLeft size={16} />
          Questions
        </Button>
        <div className="tma-builder-save">
          <Button variant="outline" onClick={() => setPreview(!preview)}>
            <Eye size={16} />
            {preview ? "Edit" : "Preview"}
          </Button>
          <Button
            disabled={!valid || busy || uploading}
            onClick={() => onSave(false)}
          >
            {busy ? "Saving…" : "Save question"}
          </Button>
          {!draft.id && (
            <Button
              variant="outline"
              disabled={!valid || busy || uploading}
              onClick={() => onSave(true)}
            >
              Save & add another
            </Button>
          )}
          <Button
            variant="outline"
            disabled={uploading}
            onClick={onAI}
            aria-label="Open AI assistant"
          >
            <Bot size={17} />
            Generate with AI
          </Button>
        </div>
      </header>
      {error && (
        <p role="alert" className="text-sm text-error">
          {error}
        </p>
      )}
      {uploading && (
        <p role="status" className="text-sm text-text-muted">
          Uploading image…
        </p>
      )}
      {preview ? (
        <section
          className="tma-builder-section space-y-5"
          aria-label="Student question preview"
        >
          <span className="tma-eyebrow">Student view · Unsaved preview</span>
          <MathText>{draft.question_text}</MathText>
          {draft.image_asset_id && (
            <TmaAssetImage
              key={draft.image_asset_id}
              assignmentId={assignmentId}
              assetId={draft.image_asset_id}
              alt="Question illustration"
            />
          )}
          <div className="space-y-3">
            {draft.options.map((o, i) => (
              <div
                key={i}
                className="flex gap-3 rounded-xl border border-border p-4"
              >
                <span className="tma-option-letter">
                  {String.fromCharCode(65 + i)}
                </span>
                <div className="min-w-0">
                  <MathText>{o.option_text}</MathText>
                  {o.image_asset_id && (
                    <TmaAssetImage
                      key={o.image_asset_id}
                      assignmentId={assignmentId}
                      assetId={o.image_asset_id}
                      alt={`Option ${i + 1}`}
                    />
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : (
        <div className="tma-builder-grid">
          <section className="tma-builder-section">
            <div className="tma-section-heading">
              <span>01</span>
              <div>
                <h2>Question content</h2>
                <p>Write the prompt and attach any supporting illustration.</p>
              </div>
            </div>
            <TextField
              label="Question prompt"
              rows={4}
              value={draft.question_text}
              onChange={(v) => setDraft({ ...draft, question_text: v })}
            />
            {imageField(
              draft.image_asset_id,
              (id) =>
                setDraft((current) => ({ ...current, image_asset_id: id })),
              "Question image",
            )}
          </section>
          <section className="tma-builder-section tma-manual-options">
            <div className="tma-section-heading">
              <span>02</span>
              <div>
                <h2>Answer options</h2>
                <p>Single choice · mark exactly one correct answer.</p>
              </div>
            </div>
            <div className="tma-answer-grid">
              {draft.options.map((o, i) => (
                <article
                  key={i}
                  className={`tma-answer-row ${o.is_correct ? "is-correct" : ""}`}
                >
                  <div className="tma-answer-heading">
                    <span className="tma-option-letter">
                      {String.fromCharCode(65 + i)}
                    </span>
                    <label className="tma-answer-choice">
                      <input
                        type="radio"
                        name="correct-answer"
                        aria-label={`Mark option ${String.fromCharCode(65 + i)} correct`}
                        checked={o.is_correct}
                        onChange={() =>
                          setDraft({
                            ...draft,
                            options: draft.options.map((item, j) => ({
                              ...item,
                              is_correct: j === i,
                            })),
                          })
                        }
                      />
                      <span>
                        {o.is_correct ? "Correct answer" : "Mark correct"}
                      </span>
                    </label>
                    <button
                      type="button"
                      aria-label={`Remove option ${String.fromCharCode(65 + i)}`}
                      disabled={draft.options.length <= 4}
                      onClick={() =>
                        setDraft({
                          ...draft,
                          options: draft.options.filter((_, j) => j !== i),
                        })
                      }
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                  <TextField
                    compact
                    label={`Option ${String.fromCharCode(65 + i)}`}
                    rows={2}
                    value={o.option_text}
                    onChange={(v) => patchOption(i, { option_text: v })}
                    trailingControls={imageField(
                      o.image_asset_id,
                      (id) => patchOption(i, { image_asset_id: id }),
                      `Option ${String.fromCharCode(65 + i)} image`,
                    )}
                  />
                </article>
              ))}
            </div>
            <div className="tma-options-footer">
              <p className="text-xs text-text-muted">
                {draft.options.filter((o) => o.option_text?.trim() || o.image_asset_id).length} of {draft.options.length} options filled
                {" · "}{draft.options.some((o) => o.is_correct)
                  ? `Correct answer: ${String.fromCharCode(65 + draft.options.findIndex((o) => o.is_correct))}`
                  : "Select a correct answer"}
              </p>
              <button
                type="button"
                className="tma-add-option"
                onClick={() =>
                  setDraft({
                    ...draft,
                    options: [
                      ...draft.options,
                      {
                        option_text: "",
                        is_correct: false,
                        image_asset_id: null,
                      },
                    ],
                  })
                }
              >
                <Plus size={17} />
                Add option
              </button>
            </div>
          </section>
        </div>
      )}
      {draft.id && (
        <div className="flex justify-end">
          <Button
            variant="outline"
            disabled={busy || uploading}
            onClick={onDelete}
          >
            <Trash2 size={16} />
            Delete question
          </Button>
        </div>
      )}
    </fieldset>
  );
}
