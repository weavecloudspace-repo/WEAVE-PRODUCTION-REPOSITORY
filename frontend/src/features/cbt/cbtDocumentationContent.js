/**
 * Curated CBT documentation. Keep commands aligned with the WEAVE CBT Typer CLI
 * and platform packaging; avoid guessing installation flags or release versions.
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
        tips: ["Select the installer from your WEAVE workspace; staging and production are different release channels.", "The Desktop package is recommended when the host has a graphical desktop."],
      },
      {
        id: "setup-flow", title: "Four steps to a ready server",
        steps: [
          ["Download", "Choose the correct Windows Desktop, Windows CLI, Linux Desktop or Linux CLI package."],
          ["Install", "Install the application on the school-controlled computer. Allow system prerequisites and a reboot if prompted."],
          ["Configure", "Confirm the CLI release and server status; configure school LAN access, DNS and trusted HTTPS."],
          ["Pair", "Return to WEAVE, generate a short-lived code and enter it in the local CBT Manager."],
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
        paragraphs:["Download the Windows Desktop installer selected for this environment. Run the installer as Administrator. It installs the Desktop Manager and the companion CLI into the same WeaveCBT application directory.", "For advanced or unattended administration, use the separate published Windows CLI setup instead of assuming a ZIP archive exists. The initial server installation provisions a dedicated WSL2 Ubuntu distribution and Docker; follow restart prompts."],
        commands:[{label:"Verify the installed Windows CLI (PowerShell)",command:'& "C:\\Program Files\\WeaveCBT\\weave.exe" release'}],
        tips:["Do not delete the dedicated WeaveCBT WSL distribution to troubleshoot a GUI-only failure. It can contain your local school examination database."],
      },
      { id:"windows-runtime", title:"Check server and logs",
        paragraphs:["After installing the server using the manager or weave install, verify both the CLI and the runtime before pairing. Use an elevated PowerShell session for operations that modify services or networking."],
        commands:[{label:"Machine-readable service status",command:'& "C:\\Program Files\\WeaveCBT\\weave.exe" status --json'},{label:"Inspect services",command:'& "C:\\Program Files\\WeaveCBT\\weave.exe" logs'}],
      },
      { id:"windows-network", title:"School LAN access",
        paragraphs:["WSL2 network address changes can invalidate Windows forwarding. Check your dedicated LAN listener and firewall scope from Windows, then use the manager to refresh forwarding if required.", "A healthy localhost portal is not enough. Test the staff and student portals from another school device on the intended Wi-Fi or Ethernet subnet."],
        commands:[{label:"Inspect Windows forwarding",command:"netsh interface portproxy show v4tov4"}],
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
       paragraphs:["For a desktop computer, download the WEAVE CBT Desktop .deb for your selected channel and install it with your distribution package manager. It includes the command-line manager.", "For a headless server, download the published CLI .tar.gz archive. Extract it into a dedicated directory, inspect the included assets, and follow the packaged instructions for installation. Avoid installing both package variants over each other."],
       commands:[{label:"Desktop package (use your downloaded filename)",command:"sudo apt install ./weave-cbt-desktop-staging-linux-amd64.deb"},{label:"Inspect a downloaded CLI archive",command:"tar -tzf weave-cbt-staging-linux-amd64.tar.gz | head"}],
       tips:["These example filenames are for staging. Download the production equivalents only from a production WEAVE workspace.", "Desktop administrative operations may require Polkit; do not grant unrestricted Docker socket permissions merely to bypass an authentication prompt."]},
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
    summary:"Commands, arguments, inspection, services and troubleshooting.",
    icon:"Terminal",
    sections:[
      {id:"cli-intro",title:"Using the WEAVE CBT command line",
       paragraphs:["The WEAVE management CLI can verify the packaged release, install or manage a local server and inspect diagnostics. On Windows, it normally lives beside the WEAVE CBT Desktop executable; on a Linux Desktop installation it is normally available as weave.", "Open PowerShell or a terminal. Use the path shown below if weave is not on your Windows PATH. Always use the package matching your workspace's staging or production environment."],
       commands:[{label:"Windows PowerShell",command:'& "C:\\Program Files\\WeaveCBT\\weave.exe" --help'},{label:"Linux / available PATH",command:"weave --help"}],
       tips:["Commands that configure, start, stop or remove the local runtime can require elevated permissions. Use read-only commands first."],
      },
      {id:"cli-verify",title:"Verify the manager and runtime",
       paragraphs:["The release command validates packaged release metadata and assets. The status command reports the installed server's state; the JSON form is useful for diagnostics and integrations."],
       commands:[{label:"Release verification",command:"weave release"},{label:"JSON server status",command:"weave status --json"}],
      },
      {id:"cli-commands",title:"Common CLI commands",
       paragraphs:["These commands are registered by the official WEAVE CBT CLI. Select a category to narrow the reference, or use the copy control next to a command."],
       commandTable:true,
      },
      {id:"cli-examples",title:"Inspect a failing service",
       paragraphs:["If the Desktop Manager reports a CLI error, first check the installed CLI directly. A successful command-line result with a failing GUI indicates a desktop discovery or subprocess problem, not necessarily an uninstalled server.", "For live service output, append --follow and interrupt with Ctrl+C when finished."],
       commands:[{label:"Verify release separately",command:"weave release"},{label:"See API logs",command:"weave logs api"},{label:"Follow live logs",command:"weave logs --follow"},{label:"Get diagnostics",command:"weave doctor"}],
      },
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
       paragraphs:["Reserve the server's private IPv4 address in the router. Verify both Ethernet and school Wi-Fi clients can reach the server, and disable client isolation if it blocks exam devices from reaching the intended server.", "Restrict inbound access to the school subnet and avoid exposing CBT services through public forwarding."]},
      {id:"dns",title:"Configure local name resolution",
       paragraphs:["Configure a local DNS A record that resolves the assigned CBT hostname to the private school server address. Use DHCP to distribute the school DNS resolver to student devices.", "Check resolution on more than one student device before beginning examinations."],
       commands:[{label:"Client-side DNS check",command:"nslookup your-paired-cbt-hostname"}]},
      {id:"https",title:"Trusted HTTPS",
       paragraphs:["Obtain a valid certificate for the exact paired hostname and verify the full chain, SNI and HTTPS redirect in a normal client browser. If HTTP redirects with status 308, inspect the HTTPS destination instead of treating the redirect as a server outage.", "Do not turn off browser or CLI certificate verification to work around a trust problem."]},
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
    summary:"Verified package channels, checksums, safe updates.",
    icon:"RefreshCcw",
    sections:[
      {id:"release-channel",title:"Release channels",
       paragraphs:["The WEAVE portal fetches official versioned downloads from the selected environment. Staging is for testing; production is for operational school examinations. Do not install assets from the other channel over an existing server without supported migration steps."]},
      {id:"integrity",title:"Verify downloaded files",
       paragraphs:["Check the published SHA-256 checksum against the downloaded installer before running it. The download page displays the hash returned by the backend's verified release catalogue."],
       commands:[{label:"PowerShell (substitute the downloaded filename)",command:"Get-FileHash .\\WEAVE-CBT-Staging-Desktop-Setup.exe -Algorithm SHA256"},{label:"Linux",command:"sha256sum weave-cbt-desktop-staging-linux-amd64.deb"}]},
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

export const CLI_COMMANDS = [
  {category:"Inspection",command:"weave --help",description:"Show supported subcommands and options."},
  {category:"Inspection",command:"weave release",description:"Validate the packaged release manifest and assets."},
  {category:"Inspection",command:"weave status --json",description:"Inspect server state as machine-readable JSON."},
  {category:"Inspection",command:"weave doctor",description:"Check runtime dependencies and local endpoints."},
  {category:"Logs",command:"weave logs",description:"Read recent logs for all CBT services."},
  {category:"Logs",command:"weave logs api",description:"Read FastAPI service logs."},
  {category:"Logs",command:"weave logs --follow",description:"Follow live service logs; Ctrl+C to stop."},
  {category:"Service",command:"weave start",description:"Start the installed CBT server."},
  {category:"Service",command:"weave stop",description:"Stop the installed CBT server."},
  {category:"Service",command:"weave restart",description:"Restart CBT services."},
  {category:"Administration",command:"weave install",description:"Provision a CBT server using the packaged assets."},
  {category:"Administration",command:"weave update --help",description:"Review supported update options before changing the server."},
  {category:"Administration",command:"weave lan --help",description:"Inspect available Windows LAN forwarding options."},
  {category:"Administration",command:"weave tls --help",description:"Review HTTPS management commands."},
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
          ...(section.commandTable ? CLI_COMMANDS.flatMap((item) => [item.command, item.description]) : []),
        ].join(" ").toLocaleLowerCase().includes(term),
      )
      .map((section) => ({topicId:topic.id, topicTitle:topic.title, sectionId:section.id, sectionTitle:section.title})),
  ).slice(0, 30);
}
