"""Assessment-safe image evaluation context for WEAVE CBT.

Question text and answer keys must be available to the vision reviewer,
otherwise a relevant reference photograph may literally spell out the answer.
No question text is added to DDGS search queries.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.cbt.ai.authoring.schemas import AIQuestionDraft


def assessment_context(question: AIQuestionDraft) -> str:
    correct = [option.text for option in question.options if option.is_correct and option.text]
    options = [option.text for option in question.options if option.text]
    return json.dumps(
        {
            "question": question.prompt[:1600],
            "instruction": (question.instruction or "")[:500],
            "answer_options": [option[:200] for option in options[:12]],
            "correct_answer_text": [answer[:200] for answer in correct[:8]],
        },
        ensure_ascii=False,
    )


def assessment_review_requirement(requirement: str, context: str | None) -> str:
    if not context:
        return requirement
    return (
        f"{requirement}\n\nASSESSMENT-INTEGRITY GATE (mandatory): "
        "The image is being selected for a student examination question. "
        "Review it for factual relevance AND whether visible text reveals the "
        "correct choice. The JSON below gives the full question and the correct "
        "answer(s) strictly for evaluation, NOT for display to students. "
        "REJECT every image containing a heading, label, diagram title, legend, "
        "annotation or caption that spells out, paraphrases, or unmistakably "
        "identifies the correct answer. For example, a figure titled "
        "'Flat Felled Seams' is invalid when the answer is 'Flat-felled seam'. "
        "A visually relevant but answer-revealing image MUST receive "
        "decision='generate_image', never 'use_candidate'. "
        "Other text may be permitted only if needed to interpret the question "
        "without exposing its answer. Do not let images supply the answer "
        "through unrequested captions.\nEXAM_CONTEXT_JSON:\n"
        f"{context}"
    )


EXAM_IMAGE_GENERATION_POLICY = """
You create a single accurate educational image for a secondary-school
examination. The image itself MUST be visually correct, not just attractive.

ACCURACY:
- Follow the visual specification precisely. Preserve scientifically correct
  anatomy, physical relationships, geometry, proportions, orientation,
  processes, apparatus arrangements, and structures where applicable.
- Render a clean, legible, uncluttered illustration; avoid irrelevant parts,
  invented structures, extra organs, misleading arrows, or ambiguous details.
- If a photograph was requested, use a realistic photo style; if a technical
  diagram was requested, use a precise instructional-illustration style.
- The visual should contain only the evidence required to solve the question.
  Do not pre-solve it or visually highlight the correct option.

EXAM INTEGRITY — NON-NEGOTIABLE:
- Do NOT write the correct answer anywhere in the image.
- Render NO written answers, answer option text, organ/technique names,
  definitions, captions, titles, headings, watermarks, annotations, logos,
  or explanatory labels identifying the correct response.
- Do not copy question text or the examiner-only answer key onto the image.
- Unless the visual specification explicitly requires reference markers,
  do not render any text or letters at all.
- If neutral reference markers (A, B, C, D or numbers) are indispensable,
  include ONLY those markers, at their described locations, without
  descriptive words or an answer-revealing legend.
- Treat examination context and correct answers as hidden instructions for
  drawing correctly, NEVER as content to print in the image.

OUTPUT: One accurate, examination-ready image with no borders containing
embedded explanatory text. Follow the required visual specification below.
""".strip()


def assessment_safe_generation_prompt(prompt: str, context: str | None) -> str:
    """Construct the provider-ready image prompt with mandatory exam rules.

    The image API exposes one prompt string rather than a role-separated
    system message. These policy instructions therefore prefix every prompt.
    """
    if not prompt.strip():
        raise ValueError("Image visual specification cannot be empty.")
    # Legacy non-examination resolvers may call this without an assessment.
    # The dedicated Qwen resolver ALWAYS supplies an examination context.
    if context is None:
        return prompt.strip()
    exam_context = (
        "\\n\\nPRIVATE EXAMINER CONTEXT (NEVER PRINT THIS TEXT):\\n" + context if context else ""
    )
    return (
        EXAM_IMAGE_GENERATION_POLICY
        + "\\n\\nVISUAL SPECIFICATION:\\n"
        + prompt.strip()
        + exam_context
    )
