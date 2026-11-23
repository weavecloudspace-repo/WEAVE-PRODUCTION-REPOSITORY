import { api } from "./api";
import {
  buildChangedPatch,
  hasPatchChanges,
  mergePatchResult,
  rememberById,
  rememberRecord,
} from "./patchPayload";

const clampLimit = (limit) => Math.min(Math.max(Number(limit) || 50, 1), 100);

const adminStudentsById = new Map();
const studentSelfById = new Map();
const parentLinksById = new Map();

const buildStudentQuery = ({
  skip = 0,
  limit = 50,
  search,
  classId,
  academicLevelId,
  unassignedClass = false,
  status,
  includeArchived = false,
} = {}) => {
  const params = new URLSearchParams();
  params.set("skip", String(Math.max(Number(skip) || 0, 0)));
  params.set("limit", String(clampLimit(limit)));
  if (search) params.set("search", search);
  if (classId) params.set("class_id", classId);
  if (academicLevelId) params.set("academic_level_id", academicLevelId);
  if (unassignedClass) params.set("unassigned_class", "true");
  if (status) params.set("status", status);
  if (includeArchived) params.set("include_archived", "true");
  return params.toString();
};

const patchAdminStudent = async (studentId, payload) => {
  const key = String(studentId);
  const current = adminStudentsById.get(key);
  const changes = buildChangedPatch(current, payload);
  if (!hasPatchChanges(changes)) return current;

  const response = await api.patch(
    `/tenant-admin/students/${studentId}/profile`,
    changes,
  );
  adminStudentsById.set(key, mergePatchResult(current, changes, response));
  return response;
};

const mergeAcademicContext = (student, context) => {
  if (!student || !context) return student;
  const classArmWithDepartment = [context.class_arm, context.department_name]
    .filter(Boolean)
    .join(" · ");

  return {
    ...student,
    academic_context: context,
    academic_level_id: context.academic_level_id ?? student.academic_level_id,
    academic_level_name: context.academic_level_name ?? student.academic_level_name,
    class_id: context.class_id ?? student.class_id,
    class_name: context.class_name ?? student.class_name,
    class_arm: classArmWithDepartment || context.class_arm || student.class_arm,
    department_id: context.department_id ?? null,
    department_name: context.department_name ?? null,
    current_academic_session_id:
      context.academic_session_id ?? student.current_academic_session_id,
    current_academic_session_name:
      context.academic_session_name ?? student.current_academic_session_name,
    current_academic_term_id:
      context.academic_term_id ?? student.current_academic_term_id,
    current_academic_term_name:
      context.academic_term_name ?? student.current_academic_term_name,
  };
};

export const studentService = {
  getStudents: (options = {}) =>
    api.get(`/students?${buildStudentQuery(options)}`),

  getAdminStudents: async (options = {}) => {
    const response = await api.get(
      `/tenant-admin/students?${buildStudentQuery(options)}`,
    );
    return rememberById(adminStudentsById, response);
  },

  createStudent: (payload) => api.post("/tenant-admin/students", payload),

  resetStudentAccessCode: (studentId) =>
    api.post(`/tenant-admin/students/${studentId}/access-codes`, {
      purpose: "password_reset",
    }),

  getMyStudent: async (requestOptions) => {
    const [profile, academicContext] = await Promise.all([
      api.get("/students/me", requestOptions),
      api.get("/students/me/academic-context", requestOptions),
    ]);
    const response = mergeAcademicContext(profile, academicContext);
    return rememberRecord(studentSelfById, response);
  },
  getMyAcademicContext: (requestOptions) =>
    api.get("/students/me/academic-context", requestOptions),

  updateMyStudentProfile: async (payload) => {
    const current = [...studentSelfById.values()][0] || null;
    const changes = buildChangedPatch(current, payload);
    if (!hasPatchChanges(changes)) return current;

    const response = await api.patch("/students/me/profile", changes);
    if (response?.id) {
      studentSelfById.set(
        String(response.id),
        mergePatchResult(current, changes, response),
      );
    }
    return response;
  },

  changeMyPassword: (payload) =>
    api.post("/students/me/change-password", payload),

  getMyParentLinkRequests: (requestOptions) =>
    api.get("/students/me/parent-link-requests", requestOptions),

  respondToParentLinkRequest: (requestId, payload) =>
    api.post(
      `/students/me/parent-link-requests/${requestId}/decision`,
      payload,
    ),

  getMyParentLinks: async (requestOptions) => {
    const response = await api.get("/students/me/parent-links", requestOptions);
    return rememberById(parentLinksById, response);
  },

  getStudent: (studentId) => api.get(`/students/${studentId}`),

  getAdminStudent: async (studentId) => {
    const response = await api.get(`/tenant-admin/students/${studentId}`);
    return rememberRecord(adminStudentsById, response);
  },

  updateAdminStudent: patchAdminStudent,

  getPlacementHistory: (studentId) =>
    api.get(`/tenant-admin/students/${studentId}/placement-history`),

  placeStudents: (payload) =>
    api.post("/tenant-admin/students/class-placement", payload),

  previewPlacementImpact: (studentId, payload) =>
    api.post(
      `/tenant-admin/students/${studentId}/placement-impact-preview`,
      payload,
    ),

  reconcileExistingResults: (studentId, payload) =>
    api.post(`/tenant-admin/students/${studentId}/reconcile-existing-results`, payload),

  reassignStudentClass: (studentId, payload) =>
    api.post(`/tenant-admin/students/${studentId}/reassign-class`, payload),

  reassignStudentAcademicLevel: (studentId, payload) =>
    api.post(
      `/tenant-admin/students/${studentId}/reassign-academic-level`,
      payload,
    ),

  updateUpcomingEnrollment: (studentId, enrollmentId, payload) =>
    api.patch(
      `/tenant-admin/students/${studentId}/upcoming-enrollments/${enrollmentId}`,
      payload,
    ),

  cancelUpcomingEnrollment: (studentId, enrollmentId, payload) =>
    api.post(
      `/tenant-admin/students/${studentId}/upcoming-enrollments/${enrollmentId}/cancel`,
      payload,
    ),

  suspendStudent: (studentId, payload) =>
    api.post(`/tenant-admin/students/${studentId}/suspend`, payload),

  reinstateStudent: (studentId, payload) =>
    api.post(`/tenant-admin/students/${studentId}/reinstate`, payload),

  reinstateExpelledStudent: (studentId, payload) =>
    api.post(`/tenant-admin/students/${studentId}/reinstate-expelled`, payload),

  readmitStudent: (studentId, payload) =>
    api.post(`/tenant-admin/students/${studentId}/readmit`, payload),

  reenrolGraduatedStudent: (studentId, payload) =>
    api.post(`/tenant-admin/students/${studentId}/re-enrol-graduate`, payload),

  undoWithdrawal: (studentId, payload) =>
    api.post(`/tenant-admin/students/${studentId}/undo-withdrawal`, payload),

  undoExpulsion: (studentId, payload) =>
    api.post(`/tenant-admin/students/${studentId}/undo-expulsion`, payload),

  undoGraduation: (studentId, payload) =>
    api.post(`/tenant-admin/students/${studentId}/undo-graduation`, payload),

  withdrawStudent: (studentId, payload) =>
    api.post(`/tenant-admin/students/${studentId}/withdraw`, payload),

  expelStudent: (studentId, payload) =>
    api.post(`/tenant-admin/students/${studentId}/expel`, payload),

  graduateStudent: (studentId, payload) =>
    api.post(`/tenant-admin/students/${studentId}/graduate`, payload),

  archiveStudent: (studentId, payload) =>
    api.post(`/tenant-admin/students/${studentId}/archive`, payload),

  restoreStudent: (studentId, payload) =>
    api.post(`/tenant-admin/students/${studentId}/restore`, payload),

  getHardDeleteEligibility: (studentId) =>
    api.get(`/tenant-admin/students/${studentId}/hard-delete-eligibility`),

  hardDeleteStudent: (studentId, payload) =>
    api.post(`/tenant-admin/students/${studentId}/hard-delete`, payload),

  completeStudentProfile: patchAdminStudent,

  updateParentLink: async (linkId, payload) => {
    const key = String(linkId);
    const current = parentLinksById.get(key);
    const changes = buildChangedPatch(current, payload);
    if (!hasPatchChanges(changes)) return current;

    const response = await api.patch(
      `/tenant-admin/student-parent-links/${linkId}`,
      changes,
    );
    parentLinksById.set(key, mergePatchResult(current, changes, response));
    return response;
  },
};
