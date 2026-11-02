/**
 * Initial placement is not a reassignment: it only fills an existing, classless
 * enrollment and must never change the student's academic level.
 */
export const needsInitialClassPlacement = (student) =>
  Boolean(student?.academic_level_id) && !student?.class_id;

export const canPlaceStudentInClass = (student, session) =>
  needsInitialClassPlacement(student) &&
  !student.is_archived &&
  !student.upcoming_enrollment &&
  ["active", "suspended"].includes(String(student.status || "").toLowerCase()) &&
  Boolean(session?.id) &&
  session.is_current === true &&
  String(session.status || "").toLowerCase() === "open";

export const eligibleInitialPlacementClasses = (classes, academicLevelId) =>
  (Array.isArray(classes) ? classes : []).filter(
    (item) =>
      item.academic_level_id === academicLevelId &&
      item.is_active !== false &&
      item.archived_at == null,
  );
