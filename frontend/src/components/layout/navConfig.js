import {
  Activity,
  BarChart3,
  BookOpen,
  Building2,
  Cpu,
  CalendarDays,
  CheckSquare,
  ClipboardList,
  CreditCard,
  Database,
  FileText,
  GraduationCap,
  Home,
  Inbox,
  Library,
  Link2,
  Mail,
  Settings,
  Shield,
  UploadCloud,
  Users,
} from "lucide-react";

import { FEATURE_CODES } from "../../features/subscriptions/subscriptionConfig";

export const roleLabels = {
  admin: "Administrator",
  teacher: "Teacher",
  student: "Student",
  parent: "Parent",
  superadmin: "Platform admin",
};

export const workspaceSearchRoles = new Set(["admin", "teacher"]);
export const tenantNameFallbackRoles = new Set([
  "admin",
  "teacher",
  "student",
  "parent",
]);

export const inboxPaths = {
  admin: "/admin/inbox",
  teacher: "/teacher/inbox",
  student: "/student/inbox",
  parent: "/parent/inbox",
  superadmin: "/superadmin/inbox",
};

export const onboardingModalCopy = {
  admin: {
    onboardingTitle: "Complete School Profile",
    editTitle: "Edit School Profile",
    onboardingDescription:
      "Finish the school profile fields required for onboarding. School-managed settings stay here, not in a personal profile form.",
    editDescription: "Update your school profile details.",
  },
  teacher: {
    onboardingTitle: "Complete Teacher Profile",
    editTitle: "Edit Teacher Profile",
    onboardingDescription:
      "Complete the teacher profile fields required by the backend before continuing.",
    editDescription: "Update your teacher profile details.",
  },
  parent: {
    onboardingTitle: "Complete Parent Profile",
    editTitle: "Edit Parent Profile",
    onboardingDescription:
      "Complete the parent profile fields required by the backend before continuing.",
    editDescription: "Update your parent profile details.",
  },
  student: {
    onboardingTitle: "Complete Student Profile",
    editTitle: "Edit Student Profile",
    onboardingDescription:
      "Complete the student profile fields required by the backend before continuing.",
    editDescription: "Update your student profile details.",
  },
};

export const navGroups = {
  admin: [
    {
      label: "Overview",
      items: [
        { label: "Dashboard", to: "/admin/dashboard", icon: Home },
        { label: "Analytics", to: "/admin/analytics", icon: BarChart3 },
        { label: "Calendar", to: "/admin/calendar", icon: CalendarDays },
      ],
    },
    {
      label: "Academics",
      items: [
        { label: "Academic Hub", to: "/admin/academic", icon: ClipboardList },
        { label: "TMA", to: "/admin/tma", icon: FileText },
        { label: "AI Usage", to: "/admin/ai-usage", icon: BarChart3 },
        { label: "Students", to: "/admin/students", icon: GraduationCap },
        { label: "Teachers", to: "/admin/teachers", icon: Users },
        { label: "Parents", to: "/admin/parents", icon: Users },
        {
          label: "Bulk Imports",
          to: "/admin/imports",
          icon: UploadCloud,
          featureCode: FEATURE_CODES.BULK_IMPORT,
        },
        { label: "Classes", to: "/admin/academic/classes", icon: Library },
        { label: "Subjects", to: "/admin/academic/subjects", icon: BookOpen },
        {
          label: "Attendance",
          to: "/admin/attendance",
          icon: CheckSquare,
          runtimeFeature: "attendance",
        },
      ],
    },
    {
      label: "Communication",
      items: [
        { label: "Inbox", to: "/admin/inbox", icon: Inbox },
        {
          label: "Messages",
          to: "/admin/messages",
          icon: Mail,
          runtimeFeature: "messaging",
        },
        { label: "Notices", to: "/admin/notices", icon: FileText },
        {
          label: "Received Notices",
          to: "/admin/notices/received",
          icon: FileText,
        },
      ],
    },
    {
      label: "Operations",
      items: [
        {
          label: "Reports",
          to: "/admin/academic/report-cards",
          icon: BarChart3,
        },
        { label: "Billing", to: "/admin/billing", icon: CreditCard },
        {
          label: "CBT Servers",
          to: "/admin/cbt",
          icon: Cpu,
          featureCode: FEATURE_CODES.CBT_PAIRING,
          allowHistoricalAccess: true,
        },
        { label: "Usage", to: "/admin/usage", icon: Activity },
        { label: "Settings", to: "/admin/settings", icon: Settings },
      ],
    },
  ],
  teacher: [
    {
      label: "Teaching workspace",
      items: [
        { label: "Dashboard", to: "/teacher/dashboard", icon: Home },
        { label: "Analytics", to: "/teacher/analytics", icon: BarChart3 },
        {
          label: "Teaching Rosters",
          to: "/teacher/students",
          icon: GraduationCap,
        },
        { label: "Assigned Subjects", to: "/teacher/subjects", icon: BookOpen },
        { label: "TMA", to: "/teacher/tma", icon: FileText },
        { label: "AI Usage", to: "/teacher/ai-usage", icon: BarChart3 },
        { label: "Results", to: "/teacher/results", icon: ClipboardList },
        { label: "Calendar", to: "/teacher/calendar", icon: CalendarDays },
        {
          label: "Attendance",
          to: "/teacher/attendance",
          icon: CheckSquare,
          runtimeFeature: "attendance",
        },
        { label: "Inbox", to: "/teacher/inbox", icon: Inbox },
        {
          label: "Messages",
          to: "/teacher/messages",
          icon: Mail,
          runtimeFeature: "messaging",
        },
        { label: "Notices", to: "/teacher/notices", icon: FileText },
        {
          label: "Received Notices",
          to: "/teacher/notices/received",
          icon: FileText,
        },
        {
          label: "Switch School",
          to: "/teacher/schools",
          icon: Building2,
          accountScope: true,
        },
        { label: "Settings", to: "/teacher/settings", icon: Settings },
      ],
    },
    {
      label: "Class teacher duties",
      items: [
        {
          label: "My Class",
          to: "/teacher/classes",
          icon: Library,
          requiresClassTeacher: true,
        },
        {
          label: "Student Comments",
          to: "/teacher/student-comments",
          icon: ClipboardList,
          requiresClassTeacher: true,
        },
        {
          label: "My Comment Templates",
          to: "/teacher/comment-templates",
          icon: FileText,
          requiresClassTeacher: true,
        },
      ],
    },
  ],
  student: [
    {
      label: "Learning",
      items: [
        { label: "Dashboard", to: "/student/dashboard", icon: Home },
        { label: "Performance", to: "/student/analytics", icon: BarChart3 },
        { label: "Subjects", to: "/student/subjects", icon: BookOpen },
        { label: "Parent Linking", to: "/student/parent-linking", icon: Link2 },
        { label: "Report Cards", to: "/student/report-cards", icon: FileText },
        { label: "Calendar", to: "/student/calendar", icon: CalendarDays },
        { label: "Inbox", to: "/student/inbox", icon: Inbox },
        {
          label: "Messages",
          to: "/student/messages",
          icon: Mail,
          runtimeFeature: "messaging",
        },
        { label: "Notices", to: "/student/notices", icon: FileText },
        { label: "Settings", to: "/student/settings", icon: Settings },
      ],
    },
  ],
  parent: [
    {
      label: "Family",
      items: [
        { label: "Dashboard", to: "/parent/dashboard", icon: Home },
        { label: "Family Insights", to: "/parent/analytics", icon: BarChart3 },
        {
          label: "Student Linking",
          to: "/parent/student-linking",
          icon: Link2,
        },
        { label: "Report Cards", to: "/parent/report-cards", icon: FileText },
        { label: "Results", to: "/parent/results", icon: BarChart3 },
        {
          label: "Attendance",
          to: "/parent/attendance",
          icon: CheckSquare,
          runtimeFeature: "attendance",
        },
        { label: "Calendar", to: "/parent/calendar", icon: CalendarDays },
        { label: "Inbox", to: "/parent/inbox", icon: Inbox },
        {
          label: "Messages",
          to: "/parent/messages",
          icon: Mail,
          runtimeFeature: "messaging",
        },
        { label: "Notices", to: "/parent/notices", icon: FileText },
        {
          label: "Switch School",
          to: "/parent/schools",
          icon: Building2,
          accountScope: true,
        },
        { label: "Settings", to: "/parent/settings", icon: Settings },
      ],
    },
  ],
  superadmin: [
    {
      label: "Command",
      items: [
        { label: "Dashboard", to: "/superadmin/dashboard", icon: Home },
        {
          label: "Security Analytics",
          to: "/superadmin/analytics",
          icon: BarChart3,
        },
        {
          label: "Control Center",
          to: "/superadmin/control-center",
          icon: Shield,
        },
        { label: "Tenant Usage", to: "/superadmin/usage", icon: Database },
        { label: "Traffic Monitor", to: "/superadmin/traffic", icon: Activity },
        {
          label: "CBT Result Operations",
          to: "/superadmin/cbt-results",
          icon: ClipboardList,
        },
        {
          label: "Simulation Lab",
          to: "/superadmin/simulations",
          icon: Activity,
          runtimeFeature: "simulations",
        },
      ],
    },
    {
      label: "Platform",
      items: [
        { label: "Inbox", to: "/superadmin/inbox", icon: Inbox },
        {
          label: "Messages",
          to: "/superadmin/messages",
          icon: Mail,
          runtimeFeature: "messaging",
        },
        {
          label: "Notices",
          to: "/superadmin/notices",
          icon: FileText,
        },
        { label: "Settings", to: "/superadmin/settings", icon: Settings },
      ],
    },
  ],
};
