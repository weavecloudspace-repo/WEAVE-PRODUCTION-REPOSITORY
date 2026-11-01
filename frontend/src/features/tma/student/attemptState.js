export function subjectAssignments(assignments, subject) {
  if (!subject?.curriculum_subject_id || !subject?.academic_term_id) return [];
  return assignments.filter(
    (item) =>
      item.curriculum_subject_id === subject.curriculum_subject_id &&
      item.academic_term_id === subject.academic_term_id,
  );
}

export function savedSelections(payload) {
  const valid = new Map(
    payload.questions.map((q) => [q.id, new Set(q.options.map((o) => o.id))]),
  );
  return Object.fromEntries(
    payload.saved_answers
      .filter((a) => valid.get(a.question_id)?.has(a.selected_option_id))
      .map((a) => [a.question_id, a.selected_option_id]),
  );
}

export function answeredCount(questions, answers) {
  return questions.filter((q) => q.options.some((o) => o.id === answers[q.id]))
    .length;
}
