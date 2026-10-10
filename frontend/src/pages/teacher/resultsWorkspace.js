export async function loadAllItems(fetchPage, signal) {
  const items = [];
  const limit = 100;
  while (!signal?.aborted) {
    const response = await fetchPage({ skip: items.length, limit });
    if (signal?.aborted) return [];
    const page = response?.items || [];
    items.push(...page);
    if (!page.length || items.length >= (response?.total ?? items.length)) break;
  }
  return items;
}

export function currentAcademicContext(sessions, terms) {
  const session = sessions.find((item) => item.is_current) || null;
  const term = session
    ? terms.find((item) => item.is_current && item.academic_session_id === session.id) || null
    : null;
  return { session, term };
}

export function buildManualScores(studentId, components, drafts) {
  return components.filter((component) => component.is_examinable === false).map((component) => {
    const raw = drafts[`${studentId}:${component.id}`];
    const score = raw === "" || raw == null ? null : Number(raw);
    if (score !== null && (!Number.isFinite(score) || score < 0 || score > Number(component.maximum_score))) {
      throw new Error(`${component.name} must be between 0 and ${component.maximum_score}.`);
    }
    return { assessment_component_id: component.id, score };
  });
}

export function resultReadiness(components, result) {
  const scores = new Map((result?.components || []).map((item) => [item.assessment_component_id, item.score]));
  const manual = components.filter((component) => component.is_examinable === false);
  const exam = components.filter((component) => component.is_examinable !== false);
  const hasScore = (component) => scores.get(component.id) != null;
  const manualEntered = manual.filter(hasScore).length;
  const examEntered = exam.filter(hasScore).length;
  return {
    manualEntered,
    manualRequired: manual.length,
    examEntered,
    examRequired: exam.length,
    ready: components.length > 0 && manualEntered === manual.length && examEntered === exam.length,
  };
}
