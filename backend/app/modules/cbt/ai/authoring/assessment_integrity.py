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


def assessment_safe_generation_prompt(prompt: str, context: str | None) -> str:
    if not context:
        return prompt
    return (
        f"{prompt}\n\nCRITICAL EXAM IMAGE RULE: Draw only the visual evidence "
        "students need to reason about the question. Do NOT write the correct "
        "answer anywhere inside the image. Avoid titles, captions, headings, "
        "names of the depicted technique/object, or labels that reveal its identity. "
        "Keep required non-answer information (for example neutral step numbers) "
        "only if essential. The examiner's correct-answer field is context for "
        "avoiding leakage, not text to render.\nEXAM_CONTEXT_JSON:\n"
        f"{context}"
    )
