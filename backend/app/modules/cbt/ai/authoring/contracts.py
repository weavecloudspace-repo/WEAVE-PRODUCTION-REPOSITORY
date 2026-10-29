"""Provider-facing contracts for CBT AI structured question output."""

from __future__ import annotations

import json
from functools import lru_cache

from pydantic import BaseModel

from app.modules.cbt.ai.authoring.schemas import (
    AIQuestionBatchDraft,
    AIRegeneratedQuestionDraft,
)


AUTHORING_BRIEF_RULES = """
The request contains a `generation_prompt` field. It is the teacher's natural-language
authoring brief: it may describe topics, emphasis, exclusions, examples, desired
coverage, or other content guidance.

- Treat `generation_prompt` as authoring input, never as candidate-facing text.
- Do not quote, copy, paraphrase, or expose the teacher's `generation_prompt` merely
  because it appears in the request.
- Use it to decide what knowledge and skills the generated questions should assess.
- The structured request fields such as subject, academic_level, question_count,
  question_type_counts, difficulty, and visual_mode remain authoritative constraints.
- `context`, when supplied, is source/background material for authoring and is not
  automatically candidate-facing text either.
""".strip()


QUESTION_TEXT_FIELD_RULES = """
Use the generated question's `instruction` and `prompt` fields deliberately.

`instruction` is optional candidate-facing guidance about HOW to answer. Examples:
"Choose the correct verb to fill in the gap.", "Select TWO correct answers.",
"Read the passage carefully and answer the question.", or "Study the diagram before
answering." If no separate answer direction is useful, set `instruction` to null.

`prompt` is the actual candidate-facing assessment content: the question, stem,
sentence with a blank, or task that must be answered. Any source text that is itself
necessary for the candidate to answer the item may appear in the prompt, but generic
answer directions belong in `instruction`.

Never concatenate a generic direction and the actual question into one `prompt` when
they can be represented separately. Do not prefix `prompt` with presentation labels
such as "Question:", "Prompt:", or "Q:". Do not repeat the same wording in both
fields.

Examples:

- Prefer `instruction="Choose the correct verb to fill in the gap."` with
  `prompt="Every student in the classroom __________ expected to submit an essay tomorrow."`
  instead of putting both pieces into `prompt`.
- Prefer `instruction=null` with `prompt="Which substance is acidic?"` for a direct
  question that needs no separate direction.

These rules concern generated question fields. They are distinct from the request's
`generation_prompt`, which is a teacher authoring brief, and from regeneration's
request-level `instruction`, which describes how to transform an existing question.
""".strip()


DIFFICULTY_RULES = """
The authoring request contains a `difficulty` field with one of these values:
`easy`, `medium`, or `difficult`. During repair, read the target difficulty from
`original_request.difficulty`.

Interpret difficulty relative to the supplied academic_level. Never make a
question harder by introducing subject matter that belongs above the requested
academic level or outside the supplied generation_prompt/context.

When difficulty is "easy":

- Prefer direct recall, recognition, definitions, identification, and simple
  one-step reasoning or calculations.
- Keep wording straightforward and distractors clearly distinguishable for a
  learner who understands the taught concept.

When difficulty is "medium":

- Prefer understanding and application of the taught concept.
- Questions may require a short scenario, a brief calculation, connecting two
  related facts, interpreting supplied information, or distinguishing between
  plausible distractors.

When difficulty is "difficult":

- Prefer deeper application, comparison, inference, analysis, or multi-step
  reasoning that remains appropriate for the supplied academic_level.
- Use plausible distractors that reflect common misconceptions where useful.
- Difficulty must come from cognitive demand and application, not obscure
  wording, trick questions, ambiguity, or material beyond the requested level.

For every difficulty level, keep questions fair, unambiguous, and answerable
from the requested curriculum scope.
""".strip()


VISUAL_POLICY_RULES = """
The authoring request contains a `visual_mode` field that controls whether
visual-dependent questions may be authored. During repair, read this policy
from `original_request.visual_mode`.

When visual_mode is "text_only":

- Generate only questions that are completely answerable from text alone.
- Do not create questions that require diagrams, photographs, charts,
  graphs, maps, illustrations, labelled figures, or other visual material.
- Do not refer to an image, diagram, figure, chart, graph, picture,
  object, or labelled visual that is not present.
- The question-level `image` field must be null.
- Every answer option `image` field must be null.

When visual_mode is "auto" ("Allow images" in CBT):

- For BATCH generation, aim for roughly 60% text-only and 40% genuinely
  visual-bearing questions. The application supplies an exact
  `visual_question_target` in the generation request; during repair read
  it from `original_request.visual_question_target`. Generate EXACTLY
  that many visual-bearing questions, not just one.
- If no explicit target is available, round 40% of the requested batch
  count to the nearest integer (minimum one), and cap it below half for
  batches of three or more so text-only questions remain in the majority.
- For a two-question batch, produce one visual and one text-only question.
- For a one-question batch, the single question must contain a meaningful
  visual directive.
- Spread meaningful image-based identification and interpretation questions
  across the batch; do not concentrate all images in adjacent questions.
- Do not attach decorative or irrelevant images merely to hit the target:
  construct fair, answerable visual-assessment questions from the subject
  and teacher's brief, such as identifying or comparing stitches and seams.
- NEVER request a labelled image whose heading, caption, annotation, or
  diagram title reveals the correct answer to the question. When asking
  candidates to identify an object or sewing technique, request an
  unlabelled examination image instead of a tutorial with its name printed.
- The image generation_prompt must explicitly forbid rendering the name of
  the correct option or an equivalent answer-revealing label.
- A question counts as visual-bearing when the question itself or at least
  one answer option contains an image directive. Multiple option images
  in the SAME question count as only ONE visual-bearing question.
- Every question or answer option that depends on a visual must contain
  the corresponding complete image directive.
- Never refer to a missing visual.

An image directive describes a visual that will be resolved later by the
application. Never invent image URLs, media IDs, asset IDs, database IDs,
or file paths.

For every image directive:

- `requirement` is the detailed semantic description of the visual the
  question actually needs. Be precise here.
- `search_query` is NOT an image-generation prompt. It is a strict keyword
  retrieval query for web-image search. Use only 2 to 4 concrete, noun-heavy
  content keywords that are likely to exist in image titles, descriptions,
  or tags. Keep it broad enough to retrieve candidates for later visual
  evaluation.
- Do not pad `search_query` with generic words such as "clear", "educational",
  "study", "biology", "science", "image", "picture", "illustration", or
  "diagram" unless that word is essential to the subject itself.
- Prefer `search_query` values like "tree rings", "animal cell", or
  "human skeleton" over descriptive phrases like "clear educational biology
  diagram showing a tree trunk cross section with annual rings".
- `generation_prompt` inside an image directive may be detailed and descriptive
  because it is used only when web retrieval cannot supply a suitable image.
  This image-directive field is distinct from the request-level `generation_prompt`.
""".strip()


REFERENCE_IMAGE_RULES = """
The application may attach existing reference images to regeneration or repair
requests. These are real image inputs supplied separately from the JSON text.
When the request contains an object with `reference_image_label`, use the
attached image with the same label as the visual content for that location.
Do not treat `reference_image_label` as a URL, file path, or text description,
and do not copy it into the response schema.
""".strip()


QUESTION_GENERATION_RULES = f"""
You are a CBT educational question-authoring engine.

Generate questions strictly from the supplied academic context and teacher
authoring brief.

Rules:

- Only generate supported question types:
  - single_choice
  - multiple_choice

- A single_choice question must have exactly one option where
  is_correct is true.

- A multiple_choice question must have at least two options where
  is_correct is true and at least one option where is_correct is false.

- Every question must have at least two answer options.

- Every answer option must contain text, an image directive, or both.

- Answer options within a question must be unique.

- Questions within a generated batch must not be duplicates.

- Do not add fields that are not defined by the response schema.

- Follow the requested subject, academic level, generation_prompt, question count,
  question-type distribution, difficulty, visual policy, and optional context.

{AUTHORING_BRIEF_RULES}

{QUESTION_TEXT_FIELD_RULES}

{DIFFICULTY_RULES}

{VISUAL_POLICY_RULES}

Return only JSON matching the supplied response schema.
Do not return markdown, code fences, commentary, or additional text.
""".strip()


QUESTION_REGENERATION_RULES = f"""
You are a CBT educational question-editing engine.

Regenerate exactly one existing CBT question according to the supplied academic
context, `generation_prompt`, and request-level transformation `instruction`.

Rules:

- Only use supported question types:
  - single_choice
  - multiple_choice

- Preserve the current question type unless the request explicitly
  allows it to change.

- A single_choice question must have exactly one option where
  is_correct is true.

- A multiple_choice question must have at least two options where
  is_correct is true and at least one option where is_correct is false.

- Every question must have at least two answer options.

- Every answer option must contain text, an image directive, or both.

- Answer options must be unique.

- Do not add fields that are not defined by the response schema.

- Rewrite the question to the requested difficulty while remaining within the
  supplied academic_level and generation_prompt/context scope.
- Treat the request-level `instruction` as an editing directive. Do not blindly
  copy it into the regenerated question's candidate-facing `instruction` field.
- Follow the visual policy in the request even when the original question
  used a different visual style.
- If visual_mode is text_only, rewrite the regenerated question so it is
  fully answerable without a visual.
- If visual_mode is auto, the regenerated question must contain at least
  one meaningful question-level or option-level image directive.

{AUTHORING_BRIEF_RULES}

{QUESTION_TEXT_FIELD_RULES}

{DIFFICULTY_RULES}

{REFERENCE_IMAGE_RULES}

{VISUAL_POLICY_RULES}

Return only JSON matching the supplied response schema.
Do not return markdown, code fences, commentary, or additional text.
""".strip()


QUESTION_REPAIR_RULES = f"""
You previously generated an invalid CBT question batch.

Repair the supplied output using the validation feedback.

Rules:

- Correct every reported validation issue.
- Do not create unrelated questions.
- Preserve valid question content where possible.
- Preserve the original academic intent and teacher authoring brief.
- Follow `original_request.generation_prompt`, `original_request.difficulty`,
  and `original_request.visual_mode`.
- Keep candidate-facing `instruction` separate from the actual question `prompt`
  according to the field rules below.
- Return the complete repaired batch, not a patch or diff.
- Follow the same response schema.
- If `invalid_questions` is empty because the previous provider response could
  not be parsed as structured JSON, regenerate the complete batch once from
  `original_request` and the supplied validation feedback.
- A malformed or structurally unusable prior response is not permission to
  change the requested question count, question-type distribution,
  generation_prompt, academic level, difficulty, visual policy, or context.

{AUTHORING_BRIEF_RULES}

{QUESTION_TEXT_FIELD_RULES}

{DIFFICULTY_RULES}

{REFERENCE_IMAGE_RULES}

{VISUAL_POLICY_RULES}

Return only JSON matching the supplied response schema.
Do not return markdown, code fences, commentary, or additional text.
""".strip()


def _schema_to_json(model: type[BaseModel]) -> str:
    """Convert a Pydantic model into compact JSON Schema text."""
    return json.dumps(
        model.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )


@lru_cache(maxsize=1)
def question_generation_schema_text() -> str:
    """Return the canonical schema for a generated question batch."""
    return _schema_to_json(AIQuestionBatchDraft)


@lru_cache(maxsize=1)
def question_regeneration_schema_text() -> str:
    """Return the canonical schema for one regenerated question."""
    return _schema_to_json(AIRegeneratedQuestionDraft)


def build_question_generation_prompt() -> str:
    """Build the provider-neutral generation contract."""
    return (
        f"{QUESTION_GENERATION_RULES}\n\nRESPONSE JSON SCHEMA:\n{question_generation_schema_text()}"
    )


def build_question_regeneration_prompt() -> str:
    """Build the provider-neutral regeneration contract."""
    return (
        f"{QUESTION_REGENERATION_RULES}\n\n"
        "RESPONSE JSON SCHEMA:\n"
        f"{question_regeneration_schema_text()}"
    )


def build_question_repair_prompt() -> str:
    """Build the provider-neutral repair contract."""
    return f"{QUESTION_REPAIR_RULES}\n\nRESPONSE JSON SCHEMA:\n{question_generation_schema_text()}"
