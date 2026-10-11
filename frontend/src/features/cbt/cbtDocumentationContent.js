import { CLI_COMMANDS, CLI_GROUPS } from "./cbtCliReference.js";

export { CLI_COMMANDS, CLI_GROUPS };

/**
 * Curated CBT documentation. Keep commands aligned with the WEAVE CBT Typer CLI
 * and platform packaging; avoid guessing installation flags or release versions.
 * Reader-facing documentation must not expose deployment environment types or channels.
 */
export const CBT_DOCS = [
  {
    id: "quick-start",
    title: "Quick start",
    summary: "From download to your first school LAN connection.",
    icon: "Rocket",
    sections: [
      {
        id: "overview", title: "Before you begin",
        paragraphs: ["Choose a dedicated Windows 64-bit or supported Ubuntu/Debian amd64 computer to host WEAVE CBT. The server retains exam data locally, including when internet access is unavailable during an examination.", "Initial installation, image downloads, pairing and synchronization require internet access. Keep sufficient free disk space and prepare a backup plan."],
        tips: ["Download the official installer from your WEAVE workspace.", "The Desktop package is recommended when the host has a graphical desktop."],
      },
      {
        id: "setup-flow", title: "Six steps to a ready server",
        steps: [
          ["Download", "Choose the correct Windows Desktop, Windows CLI, Linux Desktop or Linux CLI package."],
          ["Install", "Install the application on the school-controlled computer. Allow system prerequisites and a reboot if prompted."],
          ["Network", "Approve the school Wi-Fi or Ethernet and run weave network setup (or use the Desktop Manager)."],
          ["Pair", "Return to WEAVE, generate a short-lived code and enter it in the local CBT Manager."],
          ["HTTPS", "After pairing, run weave tls to activate the assigned student hostname."],
          ["DNS", "Optionally run weave network dns setup, then configure router DHCP DNS and verify access from a student laptop."],
        ],
      },
      { id: "verify", title: "Verify your installation",
        paragraphs: ["Open PowerShell on Windows or a terminal on Linux. These commands inspect the release and installed server, respectively."],
        commands: [{label:"Version and deployment assets",command:"weave release"},{label:"Installed server status",command:"weave status --json"}],
        tips: ["A successful release check proves the CLI package's metadata and deployment assets are present. It does not prove that the CBT server is installed or healthy."],
      },
    ],
  },
  {
    id: "windows",
    title: "Windows setup",
    summary: "Desktop Manager, standalone CLI and WSL2 prerequisites.",
    icon: "Monitor",
    sections: [
      { id:"windows-install", title:"Install the Windows package",
        paragraphs:["Download the Windows Desktop installer from your WEAVE workspace. Run the installer as Administrator. It installs the Desktop Manager and the companion CLI into the same WeaveCBT application directory.", "For advanced or unattended administration, use the separate published Windows CLI setup instead of assuming a ZIP archive exists. The initial server installation provisions a dedicated WSL2 Ubuntu distribution and Docker; follow restart prompts."],
        commands:[{label:"Verify the installed Windows CLI (PowerShell)",command:'& "C:\\Program Files\\WeaveCBT\\weave.exe" release'}],
        tips:["Do not delete the dedicated WeaveCBT WSL distribution to troubleshoot a GUI-only failure. It can contain your local school examination database."],
      },
      { id:"windows-runtime", title:"Check server and logs",
        paragraphs:["After installing the server using the manager or weave install, verify both the CLI and the runtime before pairing. Use an elevated PowerShell session for operations that modify services or networking."],
        commands:[{label:"Machine-readable service status",command:'& "C:\\Program Files\\WeaveCBT\\weave.exe" status --json'},{label:"Inspect services",command:'& "C:\\Program Files\\WeaveCBT\\weave.exe" logs'}],
      },
      { id:"windows-network", title:"School LAN access",
        paragraphs:["WSL2 network address changes can invalidate Windows forwarding. Check your dedicated LAN listener and firewall scope from Windows, then use the manager to refresh forwarding if required.", "A healthy localhost portal is not enough. Test the staff and student portals from another school device on the intended Wi-Fi or Ethernet subnet."],
        commands:[{label:"Inspect the school network",command:"weave network status"},{label:"Configure approved school LAN",command:"weave network setup --auto"},{label:"Check network health",command:"weave network doctor"}],
        tips:["Restrict client access to your intended private school network; never publish exam ports directly to the internet."],
      },
    ],
  },
  {
    id:"linux", title:"Linux setup",
    summary:"Ubuntu/Debian desktop .deb or advanced standalone CLI .tar.gz.",
    icon:"Laptop",
    sections:[
      {id:"linux-install",title:"Choose your Linux installation",
       paragraphs:["For a desktop computer, download the WEAVE CBT Desktop .deb from your WEAVE workspace and install it with your distribution package manager. It includes the command-line manager.", "For a headless server, download the published CLI .tar.gz archive. Extract it into a dedicated directory, inspect the included assets, and follow the packaged instructions for installation. Avoid installing both package variants over each other."],
       commands:[{label:"Desktop package (use your downloaded filename)",command:"sudo apt install ./your-downloaded-desktop.deb"},{label:"Inspect a downloaded CLI archive",command:"tar -tzf your-downloaded-cli.tar.gz | head"}],
       tips:["Replace the sample filenames with the exact names of your downloaded packages.", "Desktop administrative operations may require Polkit; do not grant unrestricted Docker socket permissions merely to bypass an authentication prompt."]},
      {id:"linux-verify",title:"Verify services and permissions",
       paragraphs:["Confirm that Docker and systemd are available and that the CLI has the correct privileges for service operations. A read-only inspection should not require permanently adding every school staff member to the Docker group."],
       commands:[{label:"Release assets",command:"weave release"},{label:"Runtime diagnostics",command:"weave doctor"},{label:"Listening ports",command:"sudo ss -lntp"}],
      },
      {id:"linux-network",title:"Firewall and school LAN",
       paragraphs:["Docker-published ports can bypass ordinary UFW INPUT rules. Validate firewall policies and access from a different device and from outside the allowed subnet. Check wired and Wi-Fi routes separately."],
       tips:["Never treat an accessible localhost endpoint as proof the exam portal is safely accessible throughout the school."],
      },
    ],
  },
  {
    id:"cli", title:"CLI reference",
    summary:"Everyday commands grouped by task, with options and practical examples.",
    icon:"Terminal",
    sections:[
      {id:"cli-intro",title:"Using the WEAVE CBT command line",
       paragraphs:["The WEAVE management CLI can verify the packaged release, install or manage a local server and inspect diagnostics. On Windows, it normally lives beside the WEAVE CBT Desktop executable; on a Linux Desktop installation it is normally available as weave.", "Examples use weave as the command name. On Windows, replace weave with & \"C:\\Program Files\\WeaveCBT\\weave.exe\" if the command is not on PATH. On Linux, use sudo for commands marked Administrator / root."],
       tips:["Commands that configure, start, stop or remove the local runtime can require elevated permissions. Use read-only commands first."],
      },
      ...CLI_GROUPS.map((group) => ({
        id: "cli-" + group.id,
        title: group.title,
        paragraphs: [group.description],
        commandGroupId: group.id,
        commandTable: true,
      })),
    ],
  },
  {
    id:"pairing",title:"Pairing with WEAVE",
    summary:"Connect the local school server to your WEAVE workspace.",
    icon:"Link2",
    sections:[
      {id:"pairing-ready",title:"Before generating a code",
       paragraphs:["Install the server first and confirm it runs locally. Sign in to the WEAVE admin workspace, open Set up a local exam server and select Continue to pairing.", "Generate the short-lived pairing code only when the local CBT Manager is ready. Enter the code in the local application; do not send it to other people."],
       tips:["Pairing and syncing require internet access. Exam delivery is designed to continue on the school LAN even when internet access is interrupted."]},
      {id:"pairing-hostname",title:"Assigned hostname and certificate",
       paragraphs:["Use the hostname assigned to your paired server. Map it to the reserved private IPv4 address through school-controlled LAN DNS, and provision HTTPS with a certificate valid for the exact hostname.", "Never make local server database credentials or pairing secrets publicly accessible."]},
    ],
  },
  {
    id:"networking",title:"Networking and HTTPS",
    summary:"Router setup, DNS, firewall, LAN and browser trust.",
    icon:"Network",
    sections:[
      {id:"lan",title:"Plan the school LAN",
       paragraphs:["Reserve the server IP on the school router. Run weave network setup; when a school-owned Wi-Fi is marked Public in Windows, approve only that connection with weave network trust.", "Test both Ethernet and Wi-Fi clients from the school network. Disable client isolation only if it blocks exam devices from reaching the server. Never expose CBT to the public internet."]},
      {id:"dns",title:"Configure local name resolution",
       paragraphs:["After successful pairing and HTTPS activation, WEAVE can optionally install headless CoreDNS on a Windows CBT server. CoreDNS tells student devices the server IP, while the router tells students which DNS server to ask.", "Reserve the server IP. Test CoreDNS from another computer on UDP and TCP 53 before changing the router DHCP DNS setting. An incorrect DHCP DNS server can interrupt ordinary internet name lookups.", "When setup is verified, configure the router DHCP DNS server to advertise the WEAVE host IP. There is no individual hosts-file editing for normally configured student computers. Reconnecting may be needed for existing DHCP leases."],
       commands:[{label:"Install optional local DNS",command:"weave network dns setup"},{label:"Inspect DNS status",command:"weave network dns status"},{label:"Test from student laptop (replace hostname)",command:"nslookup your-paired-cbt-hostname 192.168.1.12"}]},
      {id:"https",title:"Trusted HTTPS",
       paragraphs:["Run weave tls only after pairing to activate the certificate for the assigned hostname. Use weave network url to copy the HTTPS student link rather than the old HTTP LAN address.", "Verify certificate trust in a real student browser. If HTTP redirects with status 308, inspect the HTTPS destination rather than assuming the service is unavailable. Do not disable certificate checks."]},
      {id:"offline",title:"Offline examination test",
       paragraphs:["After syncing exam content and student credentials, test an examination from a second computer while the school internet link is disconnected. Restore internet afterward to continue synchronization.", "Record the test result before running a live examination."]},
    ],
  },
  {
    id:"troubleshooting",title:"Troubleshooting",
    summary:"Diagnose CLI, Docker, LAN, HTTPS and startup issues.",
    icon:"Wrench",
    sections:[
      {id:"cli-unavailable",title:"GUI says CLI unavailable",
       paragraphs:["Run the installed CLI directly before reinstalling anything. If it returns valid release metadata, inspect the Desktop Manager's diagnostic details and executable discovery path.", "A working CLI with a failing GUI is not proof that WSL2, PostgreSQL or Docker are broken. Preserve the school server and its data."],
       commands:[{label:"Windows PowerShell",command:'& "C:\\Program Files\\WeaveCBT\\weave.exe" release'}]},
      {id:"runtime-stopped",title:"Server or Docker is unavailable",
       paragraphs:["Check installed status, run the read-only doctor check and inspect recent logs. Confirm system prerequisites and service permissions rather than repeatedly resetting the installation."],
       commands:[{label:"Runtime status",command:"weave status --json"},{label:"Diagnostics",command:"weave doctor"},{label:"Logs",command:"weave logs"}]},
      {id:"client-access",title:"A student computer cannot connect",
       paragraphs:["Inspect the private IP, school subnet, local DNS response, firewall rules and Wi-Fi client isolation. A successful server-side localhost test does not establish LAN reachability."]},
      {id:"data-safety",title:"Updates, power loss and backups",
       paragraphs:["Back up the local database and Docker volumes before making infrastructure changes. Confirm the app's database and exam attempts are intact after any power failure.", "Do not run WSL unregister, remove the CBT data directory or delete Docker volumes as a general troubleshooting step."]},
    ],
  },
  {
    id:"updates",title:"Updates and releases",
    summary:"Official packages, checksums, and safe updates.",
    icon:"RefreshCcw",
    sections:[
      {id:"official-packages",title:"Official packages",
       paragraphs:["Download manager and CLI packages from your WEAVE workspace. Check the installed manager with weave release and follow the update guide before changing an existing server."]},
      {id:"integrity",title:"Verify downloaded files",
       paragraphs:["Check the published SHA-256 checksum against the downloaded installer before running it. The download page displays the hash returned by the backend's verified release catalogue."],
       commands:[{label:"PowerShell (substitute the downloaded filename)",command:"Get-FileHash .\\your-downloaded-installer.exe -Algorithm SHA256"},{label:"Linux",command:"sha256sum your-downloaded-desktop.deb"}]},
      {id:"backup",title:"Before updating",
       paragraphs:["Verify backups, avoid updating during an examination, and record the current application image and manager version. Follow the official package's update and rollback commands; never delete school data as part of a routine version update."]},
    ],
  },
  {
    id:"faq",title:"Frequently asked questions",
    summary:"Answers for school administrators getting started.",
    icon:"CircleHelp",
    sections:[
      {id:"internet",title:"Do students need internet during exams?",
       paragraphs:["Active examinations are designed to be served locally over the school LAN. Installation, initial setup, pairing, credential/content synchronization and subsequent result uploads require internet. Test offline operation before a live session."]},
      {id:"which-package",title:"Which installer should I download?",
       paragraphs:["Choose Windows Desktop or Linux Desktop for a machine with a graphical desktop. Use the platform's standalone CLI package for advanced/headless management. The Windows Desktop installer already includes its companion CLI."]},
      {id:"install-versus-pair",title:"Why is pairing a separate step?",
       paragraphs:["Pairing connects an already configured local CBT server to your WEAVE tenant. Generating a code before the local manager is ready can waste its short validity window."]},
      {id:"server-backup",title:"Where is school data stored?",
       paragraphs:["The exam database and runtime data are kept on the school-controlled server. Treat the CBT data directory, WSL distribution and Docker volumes as valuable school records. Back them up; never erase them as a routine repair."]},
    ],
  },
];

export function searchCbtDocs(query) {
  const term = String(query || "").trim().toLocaleLowerCase();
  if (!term) return [];
  return CBT_DOCS.flatMap((topic) =>
    topic.sections
      .filter((section) =>
        [
          topic.title, topic.summary, section.title, section.description || "",
          ...(section.paragraphs || []),
          ...(section.tips || []),
          ...(section.commands || []).flatMap((item) => [item.command, item.label]),
          ...(section.steps || []).flat(),
          ...(section.commandTable ? CLI_COMMANDS
            .filter((item) => item.groupId === section.commandGroupId)
            .flatMap((item) => [item.command, item.description, item.usage, item.explanation, item.outcome, item.note || "",
              ...item.options.flatMap((option) => [option.flag, option.description]),
              ...item.examples.flatMap((example) => [example.command, example.label])]) : []),
        ].join(" ").toLocaleLowerCase().includes(term),
      )
      .map((section) => ({topicId:topic.id, topicTitle:topic.title, sectionId:section.id, sectionTitle:section.title, groupId:section.commandGroupId})),
  ).slice(0, 30);
}
