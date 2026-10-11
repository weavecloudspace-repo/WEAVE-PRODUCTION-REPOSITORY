from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "app" / "modules" / "student_academics" / "curriculum_v2_service.py"


class TeacherEligibleClassCoverageContractTests(unittest.TestCase):
    def test_eligible_class_contract_protects_current_and_scheduled_assignments(self):
        source = SERVICE.read_text(encoding="utf-8")
        start = source.index("async def eligible_classes_for_subject")
        end = source.index("async def teacher_assignment_subject_availability", start)
        block = source[start:end]
        self.assertIn("protected_assignments", block)
        self.assertIn("TeacherAssignment.effective_to.is_(None)", block)
        self.assertIn("TeacherAssignment.effective_to >= date.today()", block)
        self.assertNotIn("TeacherAssignment.is_active.is_(True)", block)
        self.assertIn("already_assigned=classroom.id in protected_assignments", block)

    def test_contract_still_uses_canonical_resolver_for_eligibility(self):
        source = SERVICE.read_text(encoding="utf-8")
        start = source.index("async def eligible_classes_for_subject")
        end = source.index("async def teacher_assignment_subject_availability", start)
        block = source[start:end]
        self.assertEqual(block.count("CurriculumResolutionService.resolve_classes_subjects"), 1)
        self.assertNotIn("CurriculumResolutionService.resolve_class_subjects(", block)
        self.assertIn("tenant_id=tenant_id", block)
        self.assertIn("class_ids=class_ids", block)
        self.assertIn("academic_term_id=academic_term_id", block)

    def test_subject_availability_is_batched_and_uses_the_same_coverage_rule(self):
        source = SERVICE.read_text(encoding="utf-8")
        start = source.index("async def teacher_assignment_subject_availability")
        end = source.index("async def resolved_class_subject_responses", start)
        block = source[start:end]
        self.assertEqual(block.count("CurriculumResolutionService.resolve_classes_subjects"), 1)
        self.assertNotIn("CurriculumResolutionService.resolve_class_subjects(", block)
        self.assertIn("tenant_id=tenant_id", block)
        self.assertIn("academic_term_id=academic_term_id", block)
        self.assertIn("for classroom in classes", block)
        self.assertIn("TeacherAssignment.effective_to.is_(None)", block)
        self.assertIn("TeacherAssignment.effective_to >= date.today()", block)
        self.assertIn("unassigned_class_count=len(eligible - assigned)", block)


if __name__ == "__main__":
    unittest.main()
