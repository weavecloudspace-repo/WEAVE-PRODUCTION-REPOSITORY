import { api } from "./api";
import {
  buildChangedPatch,
  hasPatchChanges,
  mergePatchResult,
  rememberById,
  rememberRecord,
} from "./patchPayload";
import { termOpenPreflightBlocker } from "./termOpenPreflight";

const sessionsById = new Map();
const termsById = new Map();
const gradingScalesById = new Map();
const assessmentSchemesById = new Map();
const assessmentComponentsById = new Map();

const queryString = (params = {}) => {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (key === "signal") return;
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  });
  const value = query.toString();
  return value ? `?${value}` : "";
};

const sessionPayload = (payload = {}) => ({
  ...(payload.name !== undefined ? { name: payload.name } : {}),
  ...(payload.start_date !== undefined
    ? { start_date: payload.start_date }
    : {}),
  ...(payload.end_date !== undefined ? { end_date: payload.end_date } : {}),
  ...(payload.next_academic_session_id !== undefined
    ? { next_academic_session_id: payload.next_academic_session_id }
    : {}),
});

const stripTermCreateOnlyFields = (payload = {}) => {
  const updatablePayload = { ...payload };
  delete updatablePayload.academic_session_id;
  return updatablePayload;
};

const stripGradingLifecycleFields = (payload = {}) => {
  const updatablePayload = { ...payload };
  delete updatablePayload.is_active;
  return updatablePayload;
};

const rememberAssessmentScheme = (scheme) => {
  rememberRecord(assessmentSchemesById, scheme);
  (scheme?.components || []).forEach((component) =>
    rememberRecord(assessmentComponentsById, component),
  );
  return scheme;
};

const rememberAssessmentSchemes = (response) => {
  const items = Array.isArray(response) ? response : response?.items || [];
  items.forEach(rememberAssessmentScheme);
  return response;
};

const patchRemembered = async ({ cache, id, payload, request }) => {
  const key = String(id);
  const current = cache.get(key);
  const changes = buildChangedPatch(current, payload);
  if (!hasPatchChanges(changes)) return current;

  const response = await request(changes);
  cache.set(key, mergePatchResult(current, changes, response));
  return response;
};

const buildTeacherAssignmentPayload = (payload = {}) => ({
  class_id: payload.class_id,
  curriculum_subject_id: payload.curriculum_subject_id,
  academic_term_id: payload.academic_term_id,
  teacher_membership_id: payload.teacher_membership_id || payload.teacher_id,
  ...(payload.effective_from ? { effective_from: payload.effective_from } : {}),
});

const reassignTeacherAssignment = async (assignmentId, payload) => {
  const teacherMembershipId =
    payload.teacher_membership_id || payload.teacher_id;
  return api.post(
    `/tenant-admin/academics/teacher-assignments/${assignmentId}/reassign`,
    {
      teacher_membership_id: teacherMembershipId,
      academic_term_id: payload.academic_term_id,
      reason: payload.reason,
      ...(payload.effective_from
        ? { effective_from: payload.effective_from }
        : {}),
    },
  );
};

const preflightOpenTerm = async (termId) => {
  const [dependencyPreview, currentTerms] = await Promise.all([
    api.get(`/tenant-admin/academics/terms/${termId}/dependencies`),
    api.get(`/tenant-admin/academics/terms${queryString({ is_current: true, limit: 100 })}`),
  ]);
  const blocker = termOpenPreflightBlocker({
    currentTerms,
    targetTermId: termId,
    dependencyPreview,
  });
  if (blocker) throw new Error(blocker);
};

export const academicService = {
  getSetupReadiness: () => api.get("/tenant-admin/academics/setup-readiness"),
  listSessions: async (params) => {
    const response = await api.get(
      `/tenant-admin/academics/sessions${queryString(params)}`,
    );
    return rememberById(sessionsById, response);
  },
  createSession: async (payload) => {
    const response = await api.post(
      "/tenant-admin/academics/sessions",
      sessionPayload(payload),
    );
    return rememberRecord(sessionsById, response);
  },
  updateSession: (sessionId, payload) =>
    patchRemembered({
      cache: sessionsById,
      id: sessionId,
      payload: sessionPayload(payload),
      request: (changes) =>
        api.patch(`/tenant-admin/academics/sessions/${sessionId}`, changes),
    }),
  openSession: (sessionId) =>
    api.post(`/tenant-admin/academics/sessions/${sessionId}/open`, {
      confirmation: "OPEN_ACADEMIC_SESSION",
    }),
  getSessionDependencies: (sessionId) =>
    api.get(`/tenant-admin/academics/sessions/${sessionId}/dependencies`),
  deleteSession: (sessionId) =>
    api.delete(`/tenant-admin/academics/sessions/${sessionId}`, {
      body: JSON.stringify({
        confirmation: "DELETE_ACADEMIC_SESSION",
      }),
      headers: { "Content-Type": "application/json" },
    }),
  listTeacherSessions: (params) =>
    api.get(`/teachers/academics/sessions${queryString(params)}`),

  listTerms: async (params) => {
    const response = await api.get(
      `/tenant-admin/academics/terms${queryString(params)}`,
    );
    return rememberById(termsById, response);
  },
  createTerm: async (payload) => {
    const response = await api.post("/tenant-admin/academics/terms", payload);
    return rememberRecord(termsById, response);
  },
  updateTerm: (termId, payload) =>
    patchRemembered({
      cache: termsById,
      id: termId,
      payload: stripTermCreateOnlyFields(payload),
      request: (changes) =>
        api.patch(`/tenant-admin/academics/terms/${termId}`, changes),
    }),
  openTerm: async (termId) => {
    await preflightOpenTerm(termId);
    return api.post(`/tenant-admin/academics/terms/${termId}/open`, {
      confirmation: "OPEN_ACADEMIC_TERM",
    });
  },
  getTermDependencies: (termId) =>
    api.get(`/tenant-admin/academics/terms/${termId}/dependencies`),
  startTermClosing: (termId) =>
    api.post(`/tenant-admin/academics/terms/${termId}/start-closing`, {
      confirmation: "START_TERM_CLOSING",
    }),
  finalizeTermClose: (termId) =>
    api.post(`/tenant-admin/academics/terms/${termId}/finalize-close`, {
      confirmation: "FINALIZE_TERM_CLOSE",
    }),
  cancelTermClosure: (termId, reason) =>
    api.post(`/tenant-admin/academics/terms/${termId}/cancel-closure`, {
      confirmation: "CANCEL_TERM_CLOSURE",
      reason,
    }),
  deleteTerm: (termId) =>
    api.delete(`/tenant-admin/academics/terms/${termId}`, {
      body: JSON.stringify({ confirmation: "DELETE_ACADEMIC_TERM" }),
      headers: { "Content-Type": "application/json" },
    }),
  listTeacherTerms: (params) =>
    api.get(`/teachers/academics/terms${queryString(params)}`),

  listAssessmentSchemes: async () => {
    const response = await api.get(
      "/tenant-admin/academics/assessment-schemes",
    );
    return rememberAssessmentSchemes(response);
  },
  getActiveAssessmentScheme: async () => {
    const response = await api.get(
      "/tenant-admin/academics/assessment-schemes/active",
    );
    return rememberAssessmentScheme(response);
  },
  createAssessmentScheme: async (payload) => {
    const response = await api.post(
      "/tenant-admin/academics/assessment-schemes",
      payload,
    );
    return rememberAssessmentScheme(response);
  },
  updateAssessmentScheme: (schemeId, payload) =>
    patchRemembered({
      cache: assessmentSchemesById,
      id: schemeId,
      payload,
      request: (changes) =>
        api.patch(
          `/tenant-admin/academics/assessment-schemes/${schemeId}`,
          changes,
        ),
    }),
  addAssessmentComponent: async (schemeId, payload) => {
    const response = await api.post(
      `/tenant-admin/academics/assessment-schemes/${schemeId}/components`,
      payload,
    );
    return rememberRecord(assessmentComponentsById, response);
  },
  updateAssessmentComponent: (schemeId, componentId, payload) =>
    patchRemembered({
      cache: assessmentComponentsById,
      id: componentId,
      payload,
      request: (changes) =>
        api.patch(
          `/tenant-admin/academics/assessment-schemes/${schemeId}/components/${componentId}`,
          changes,
        ),
    }),
  removeAssessmentComponent: (schemeId, componentId) =>
    api.delete(
      `/tenant-admin/academics/assessment-schemes/${schemeId}/components/${componentId}`,
    ),
  reorderAssessmentComponents: (schemeId, componentIds) =>
    api.put(
      `/tenant-admin/academics/assessment-schemes/${schemeId}/component-order`,
      { component_ids: componentIds },
    ),
  activateAssessmentScheme: (schemeId) =>
    api.post(
      `/tenant-admin/academics/assessment-schemes/${schemeId}/activate`,
      {},
    ),
  getTeacherAssessmentScheme: () =>
    api.get("/teachers/academics/assessment-scheme"),
  getStudentAssessmentScheme: () =>
    api.get("/students/academics/assessment-scheme"),

  listGradingScales: async (params) => {
    const response = await api.get(
      `/tenant-admin/academics/grading-scales${queryString(params)}`,
    );
    return rememberById(gradingScalesById, response);
  },
  createGradingScale: async (payload) => {
    const response = await api.post(
      "/tenant-admin/academics/grading-scales",
      payload,
    );
    return rememberRecord(gradingScalesById, response);
  },
  updateGradingScale: (scaleId, payload) =>
    patchRemembered({
      cache: gradingScalesById,
      id: scaleId,
      payload: stripGradingLifecycleFields(payload),
      request: (changes) =>
        api.patch(
          `/tenant-admin/academics/grading-scales/${scaleId}`,
          changes,
        ),
    }),
  activateGradingScale: (scaleId) =>
    api.post(`/tenant-admin/academics/grading-scales/${scaleId}/activate`, {}),
  deactivateGradingScale: (scaleId) =>
    api.post(
      `/tenant-admin/academics/grading-scales/${scaleId}/deactivate`,
      {},
    ),
  getGradingScaleDependencies: (scaleId) =>
    api.get(`/tenant-admin/academics/grading-scales/${scaleId}/dependencies`),
  deleteGradingScale: (scaleId) =>
    api.delete(`/tenant-admin/academics/grading-scales/${scaleId}`, {
      body: JSON.stringify({ confirmation: "DELETE_GRADING_SCALE" }),
      headers: { "Content-Type": "application/json" },
    }),
  getGradingReadiness: () =>
    api.get("/tenant-admin/academics/grading-scales/readiness-preview"),

  listTeacherAssignments: (params, options) =>
    api.get(
      `/tenant-admin/academics/teacher-assignments${queryString(params)}`,
      options,
    ),
  getTeacherAssignmentDependencies: (assignmentId) =>
    api.get(
      `/tenant-admin/academics/teacher-assignments/${assignmentId}/dependencies`,
    ),
  createTeacherAssignment: (payload) =>
    api.post(
      "/tenant-admin/academics/teacher-assignments",
      buildTeacherAssignmentPayload(payload),
    ),
  endTeacherAssignment: (assignmentId, payload) =>
    api.post(
      `/tenant-admin/academics/teacher-assignments/${assignmentId}/end`,
      payload,
    ),
  reassignTeacherAssignment,
  updateScheduledTeacherAssignment: (assignmentId, payload) =>
    api.patch(
      `/tenant-admin/academics/teacher-assignments/${assignmentId}/schedule`,
      payload,
    ),
  cancelScheduledTeacherAssignment: (assignmentId, payload) =>
    api.post(
      `/tenant-admin/academics/teacher-assignments/${assignmentId}/schedule/cancel`,
      payload,
    ),

  listAdminResults: (params, requestOptions) =>
    api.get(
      `/tenant-admin/academics/results${queryString(params)}`,
      requestOptions,
    ),
  saveAdminResult: (payload) =>
    api.post("/tenant-admin/academics/results", payload),
  updateResultStatus: (resultId, payload) =>
    api.patch(`/tenant-admin/academics/results/${resultId}/status`, payload),
  reopenResult: (resultId, payload) =>
    api.post(`/tenant-admin/academics/results/${resultId}/reopen`, payload),

  listMyTeacherAssignments: (requestOptions) =>
    api.get("/teachers/academics/assignments", requestOptions),
  listMyAssignmentStudents: (assignmentId, params, requestOptions) =>
    api.get(
      `/teachers/academics/assignments/${assignmentId}/students${queryString(params)}`,
      requestOptions,
    ),
  listTeacherResults: (params, requestOptions) =>
    api.get(
      `/teachers/academics/results${queryString(params)}`,
      requestOptions,
    ),
  saveTeacherResult: (payload) =>
    api.post("/teachers/academics/results", payload),

  listMyResults: (requestOptions) =>
    api.get("/students/academics/results", requestOptions),
  listMySubjectCards: (requestOptions) =>
    api.get("/students/academics/subjects", requestOptions),
  getMyElectiveWorkspace: (requestOptions) =>
    api.get("/students/academics/electives", requestOptions),
  updateMyElectiveSelection: (electiveGroupId, curriculumSubjectIds) =>
    api.put(`/students/academics/electives/${electiveGroupId}`, {
      curriculum_subject_ids: curriculumSubjectIds,
    }),
  listChildResults: (studentId, requestOptions) =>
    api.get(`/parents/academics/students/${studentId}/results`, requestOptions),
  listChildSubjectCards: (studentId, requestOptions) =>
    api.get(
      `/parents/academics/students/${studentId}/subjects`,
      requestOptions,
    ),
};

export default academicService;
