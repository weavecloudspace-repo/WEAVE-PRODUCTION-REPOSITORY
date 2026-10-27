const sameSubjectScope = (result, assignment) => {
  if (result?.curriculum_subject_id && assignment?.curriculum_subject_id) {
    return result.curriculum_subject_id === assignment.curriculum_subject_id;
  }
  return Boolean(result?.subject_id && result.subject_id === assignment?.subject_id);
};

export const resultForAssignment = (results, assignment) =>
  (results || []).find((result) => sameSubjectScope(result, assignment)) || null;

export const resultHasAllComponentScores = (result) => {
  const components = Array.isArray(result?.components) ? result.components : [];
  // Hybrid scores can be non-null while a CBT or theory lane remains incomplete.
  return components.length > 0 && components.every((component) => component.is_complete === true);
};

export const assignmentsAvailableForEntry = (assignments, results, classId) =>
  (assignments || []).filter(
    (assignment) =>
      (!classId || assignment.class_id === classId) &&
      !resultHasAllComponentScores(resultForAssignment(results, assignment)),
  );

export const componentScoresForAssignment = (results, assignment) => {
  const result = resultForAssignment(results, assignment);
  return Object.fromEntries(
    (result?.components || []).map((component) => [
      component.assessment_component_id,
      component.score ?? "",
    ]),
  );
};

export const loadClassTeacherAssignments = async (fetchPage, classId) => {
  if (!classId) return [];
  const limit = 100;
  let skip = 0;
  const assignments = [];
  while (true) {
    const response = await fetchPage({
      class_id: classId,
      status: "current",
      skip,
      limit,
    });
    const page = Array.isArray(response?.items) ? response.items : [];
    assignments.push(...page);
    const total = Number(response?.total ?? assignments.length);
    if (!page.length || assignments.length >= total) return assignments;
    skip += page.length;
  }
};

export const buildResultSubjectOptions = (classSubjects, recordedSubjects) => {
  const byId = new Map();
  for (const subject of [...(classSubjects || []), ...(recordedSubjects || [])]) {
    const id = subject?.subject_id || subject?.id;
    if (!id) continue;
    const name = subject.subject_name || subject.name;
    const code = subject.subject_code || subject.code;
    byId.set(id, {
      value: id,
      label: [name, code].filter(Boolean).join(" · ") || "Subject",
    });
  }
  return [...byId.values()].sort((a, b) => a.label.localeCompare(b.label));
};
