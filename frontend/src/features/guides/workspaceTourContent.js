const copy = {
  dashboard: [
    "Your everyday starting point",
    "Get an overview of your school day and pick up where you left off.",
    ["Your overview", "Recent activity", "Quick access"],
  ],
  analytics: [
    "See the bigger picture",
    "Explore the summaries available to your role and follow progress over time.",
    ["Clear summaries", "Progress over time", "A closer look"],
  ],
  calendar: [
    "Keep school dates close",
    "Find the term dates, school events, holidays, and closures shared with you.",
    ["School dates", "Events", "Holidays & closures"],
  ],
  academic: [
    "Give your school its structure",
    "Start with a session, term, and calendar. Return here for levels, departments, classes, and curriculum when you need them.",
    ["School year", "Classes & levels", "Curriculum"],
  ],
  tma: [
    "Create and review tutor-marked assignments",
    "Write questions, inspect answer keys, publish assignments, and follow submissions.",
    ["Question authoring", "Student preview", "Submissions"],
  ],
  "ai-usage": [
    "Manage your AI credits",
    "Review AI usage, balances, requests and secure credit purchases in one place.",
    ["Usage overview", "Credit requests", "Payment history"],
  ],
  students: [
    "Know your students",
    "Find student records and manage enrolment in your school.",
    ["Student directory", "Student records", "Enrolments"],
  ],
  teachers: [
    "Meet your teaching team",
    "Find your teachers and manage their school memberships.",
    ["Teacher directory", "Teacher records", "School memberships"],
  ],
  parents: [
    "Connect school and home",
    "Find parent records and review their links to students.",
    ["Parent directory", "Parent records", "Student links"],
  ],
  imports: [
    "Bring your records together",
    "Import supported school records in batches when you are ready to add your data.",
    ["Prepare a file", "Review records", "Import results"],
  ],
  classes: [
    "Find your classes",
    "Organise class arms and view the classes in your school.",
    ["Class arms", "Academic levels", "Class records"],
  ],
  subjects: [
    "Find your subjects",
    "Explore the subjects available in your school workspace.",
    ["Subject list", "Subject details", "Academic context"],
  ],
  attendance: [
    "Follow school attendance",
    "Review the attendance information and actions available to your role.",
    ["School days", "Attendance records", "Attendance summaries"],
  ],
  inbox: [
    "Keep up with updates",
    "Find notifications and updates that need your attention.",
    ["New updates", "Read notifications", "Open related work"],
  ],
  messages: [
    "Stay in touch",
    "Open the conversations available in your school workspace.",
    ["Conversations", "Read messages", "Replies"],
  ],
  notices: [
    "Stay informed",
    "Read school notices and open the details of an announcement.",
    ["School notices", "Notice details", "Shared information"],
  ],
  received: [
    "Find notices sent to you",
    "Read the notices shared directly with your workspace.",
    ["Received notices", "Notice details", "School updates"],
  ],
  "report-cards": [
    "Find published report cards",
    "View report cards when the school has published them.",
    ["Choose a term", "Published reports", "Print a report"],
  ],
  results: [
    "Follow academic results",
    "Review the results the school makes available for your linked children.",
    ["Linked children", "Term results", "Subject results"],
  ],
  billing: [
    "Manage your school plan",
    "Review your term plan and payment history when you need them.",
    ["Term plan", "Plan options", "Payment history"],
  ],
  cbt: [
    "Connect computer-based testing",
    "Manage the CBT server connections available to your school.",
    ["School servers", "Pairing", "Connection status"],
  ],
  usage: [
    "Understand your plan usage",
    "Check the usage information available for your school plan.",
    ["Current usage", "Plan limits", "School resources"],
  ],
  settings: [
    "Make your workspace yours",
    "Find your profile and the settings available to your role.",
    ["Profile", "Preferences", "Workspace settings"],
  ],
  branding: [
    "Make your school unmistakably yours",
    "Choose the shared school identity and colour palette now available on your plan.",
    ["School identity", "Colour palette", "Shared branding"],
  ],
  "student-linking": [
    "Connect with your children",
    "Review your student links and follow the school's linking process.",
    ["Linked students", "Linking requests", "School connections"],
  ],
  "parent-linking": [
    "Connect with your parent",
    "Review your parent links and the linking options provided by your school.",
    ["Parent links", "Linking requests", "School connections"],
  ],
  "student-comments": [
    "Support your class at report time",
    "If you are a class teacher, review academic performance and prepare student comments when results are ready.",
    ["Your class", "Student comments", "Submission status"],
  ],
  "comment-templates": [
    "Keep useful wording handy",
    "Find your saved comment templates to help with class-teacher comments.",
    ["Saved templates", "Reusable wording", "Your collection"],
  ],
  schools: [
    "Move between your schools",
    "Select a school membership to open that school's workspace.",
    ["Your memberships", "Select a school", "School workspace"],
  ],
};

const upgradeCopy = {
  imports: [
    "Bulk import is now available",
    "Your plan now includes bulk import, so admins can bring supported school records into Weave with review before anything is saved.",
    ["New on this plan", "Review before import", "Faster setup work"],
  ],
  cbt: [
    "CBT pairing is now available",
    "Your plan now includes CBT server pairing, so admins can connect computer-based testing to this school workspace when the server is ready.",
    ["New on this plan", "Server pairing", "Connection status"],
  ],
  branding: [
    "School branding is now available",
    "Your plan now includes school branding, so admins can apply the school's shared identity and colour palette across the workspace.",
    ["New on this plan", "School identity", "Shared palette"],
  ],
};

export function tourContentForItem(
  role,
  item,
  { dedicated = false, dedicatedKind = null } = {},
) {
  const segment = item.to.split("/").filter(Boolean).at(-1);
  let entry = dedicated
    ? upgradeCopy[segment] || [
        `${item.label} is now available`,
        `Your plan now includes ${String(item.label || "this feature").toLowerCase()}. This update points out where admins can find it in the workspace.`,
        ["New on this plan", "Available now", "Admin workspace"],
      ]
    : copy[segment] || copy.dashboard;
  if (dedicatedKind === "class-duties" && role === "teacher") {
    const classDutyCopy = {
      classes: [
        "Your class is now available",
        "Review the class placed under your care without mixing it with the subject rosters you teach.",
        ["Your assigned class", "Class roster", "Clear responsibility"],
      ],
      "student-comments": [
        "Complete student comments",
        "Review finalized performance and prepare the class-teacher comment used on each student's report card.",
        ["Comment readiness", "Draft and review", "Final submission"],
      ],
      "comment-templates": [
        "Save reusable comment wording",
        "Prepare personal comment templates for performance ranges, then review the wording before applying it to a student.",
        ["Performance ranges", "Saved wording", "Your defaults"],
      ],
    };
    entry = classDutyCopy[segment] || entry;
  }
  if (!dedicated && role === "teacher" && segment === "students")
    entry = [
      "Meet the students you teach",
      "Find the students in your teaching rosters and their class context.",
      ["Teaching rosters", "Your students", "Class context"],
    ];
  if (!dedicated && role === "teacher" && segment === "subjects")
    entry = [
      "See your teaching assignments",
      "Find the subjects assigned to you and open the teaching work available for each one.",
      ["Assigned subjects", "Class assignments", "Teaching work"],
    ];
  if (!dedicated && role === "teacher" && segment === "classes")
    entry = [
      "Your class-teacher workspace",
      "If you are assigned as a class teacher, find your class and the duties available to you here.",
      ["Your assigned class", "Class roster", "Class-teacher duties"],
    ];
  if (!dedicated && role === "admin" && segment === "report-cards")
    entry = [
      "Bring term reports together",
      "Review your school's report-card workflow when you are ready to work with results.",
      ["Term reports", "Report review", "Publication"],
    ];
  return { ...item, title: entry[0], description: entry[1], preview: entry[2] };
}
