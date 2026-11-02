from __future__ import annotations

from app.modules.cbt.ai.authoring.contracts import (
    build_question_generation_prompt,
    build_question_regeneration_prompt,
    build_question_repair_prompt,
    question_generation_schema_text,
)


def test_dynamic_response_schema_describes_prompt_and_instruction_semantics() -> None:
    schema = question_generation_schema_text()

    assert "The actual candidate-facing question, stem, or task to answer" in schema
    assert "generic directions about how to answer out of this field" in schema
    assert "Optional candidate-facing direction explaining how to answer" in schema
    assert "Do not repeat or embed the actual question in this field" in schema


def test_generation_contract_separates_teacher_brief_from_candidate_fields() -> None:
    prompt = build_question_generation_prompt()

    assert "teacher's natural-language\nauthoring brief" in prompt
    assert "Treat `generation_prompt` as authoring input, never as candidate-facing text" in prompt
    assert (
        "Never concatenate a generic direction and the actual question into one `prompt`" in prompt
    )
    assert 'instruction="Choose the correct verb to fill in the gap."' in prompt
    assert (
        'prompt="Every student in the classroom __________ expected to submit an essay tomorrow."'
        in prompt
    )


def test_regeneration_contract_distinguishes_editing_instruction_from_candidate_instruction() -> (
    None
):
    prompt = build_question_regeneration_prompt()

    assert "request-level transformation `instruction`" in prompt
    assert "Treat the request-level `instruction` as an editing directive" in prompt
    assert "candidate-facing `instruction` field" in prompt


def test_repair_contract_preserves_natural_language_authoring_brief() -> None:
    prompt = build_question_repair_prompt()

    assert "original_request.generation_prompt" in prompt
    assert "generation_prompt, academic level, difficulty, visual policy, or context" in prompt
    assert (
        "Keep candidate-facing `instruction` separate from the actual question `prompt`" in prompt
    )


def test_allow_images_prompt_uses_40_percent_visual_target_and_repair_contract() -> None:
    generation = build_question_generation_prompt()
    repair = build_question_repair_prompt()
    assert "roughly 60% text-only and 40%" in generation
    assert "visual_question_target" in generation
    assert "EXACTLY" in generation
    assert "original_request.visual_question_target" in repair
    assert 'When visual_mode is "text_only"' in generation
