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
        paragraphs: ["Choose a dedicated Windows 64-bit or supported Ubuntu/Debian amd64 computer to host WEAVE CBT. The server runs its own PostgreSQL, Redis and examination services and retains exam data locally, including when internet access is unavailable during an examination. WEAVE CBT V1 supports one standalone examination installation per school; capacity scales with the server hardware, not by combining separate installations.", "Initial installation, image downloads, pairing and synchronization require internet access. Keep sufficient free disk space and prepare a backup plan."],
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
          ["DNS", "Default when router/DHCP DNS cannot be configured: add the paired hostname and server LAN IP to each student computer’s hosts file; Windows users flush DNS afterward. CoreDNS remains optional."],
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
        paragraphs:["Download and run the official Windows Desktop installer. The installed Desktop Manager requests native Windows UAC administrator approval immediately when launched; declining closes the manager before any server operation begins.", "The installer places weave.exe next to the Desktop Manager executable. The GUI launches the CLI by that verified absolute path, so its first run does not depend on the machine PATH having refreshed. To type weave directly in PowerShell, open a new terminal after setup.", "For advanced or unattended administration, use the separate published Windows CLI setup instead of assuming a ZIP archive exists. Server installation provisions a dedicated WSL2 Ubuntu distribution and Docker; follow restart prompts."],
        commands:[{label:"Verify the installed Windows CLI (PowerShell)",command:'& "C:\\Program Files\\WeaveCBT\\weave.exe" release'}],
        tips:["Do not delete the dedicated WeaveCBT WSL distribution to troubleshoot a GUI-only failure. It can contain your local school examination database."],
      },
      { id:"windows-runtime", title:"Check server and logs",
        paragraphs:["After installing the server using the manager or weave install, verify both the CLI and the runtime before pairing. Use an elevated PowerShell session for operations that modify services or networking."],
        commands:[{label:"Machine-readable service status",command:'& "C:\\Program Files\\WeaveCBT\\weave.exe" status --json'},{label:"Inspect services",command:'& "C:\\Program Files\\WeaveCBT\\weave.exe" logs'}],
      },
      { id:"windows-hosts", title:"Manual DNS: Windows student computers (default)",
        paragraphs:["A server can have a valid HTTPS certificate but still be unreachable by name. DNS normally translates the paired CBT hostname into its private school LAN IP. If the router cannot distribute a local DNS server through DHCP, add a hosts-file entry on EVERY Windows student computer (and any staff device that opens the CBT URL). Editing the CBT server's hosts file alone does not configure the other devices.", "First run weave network url on the CBT server to identify the actual paired hostname, and weave network status to identify its reachable school LAN IPv4 address. The address and hostname below are examples: replace BOTH with your school's actual values. Do not use the WSL/Docker internal IP.", "On each Windows client, open PowerShell as Administrator and use the first command to open the hosts file in Notepad. At the end of the file add the example mapping with your real values, then save the existing file as hosts WITHOUT a .txt extension. If the hostname already has an entry, update it instead of adding a duplicate.", "Run ipconfig /flushdns on that same client to refresh cached DNS answers. Check the hostname resolution and open the exact HTTPS student URL in the browser; the IP in ping output should be the CBT server LAN IP even if the server blocks ICMP replies."],
        commands:[
          {label:"On each Windows client: open hosts file as Administrator",command:"notepad C:\\Windows\\System32\\drivers\\etc\\hosts"},
          {label:"Example line to add inside hosts file — NOT a PowerShell command",command:"192.168.1.12 test-server1.testschool1.cbt.weavecloudspace.com"},
          {label:"Flush Windows DNS cache after saving",command:"ipconfig /flushdns"},
          {label:"Check which IP this hostname resolves to (replace hostname)",command:"ping test-server1.testschool1.cbt.weavecloudspace.com"},
          {label:"Check HTTPS using the hostname (replace hostname)",command:"curl.exe -I https://test-server1.testschool1.cbt.weavecloudspace.com"},
        ],
        tips:["Manual hosts-file mappings apply only to the device you edit. Repeat on every student laptop; keep the CBT server IP stable using a router DHCP reservation if possible.", "Do not ignore browser certificate warnings or use the raw IP for HTTPS. The certificate must match the exact paired hostname, and the server must be reachable over the school LAN on TCP/443."],
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
       paragraphs:["Native Linux Docker runs directly on the server; Windows WSL2 forwarding is not needed. Reserve a private server IP in the school's router and inspect it with weave network status. The current weave network setup command on Linux confirms that Windows forwarding is unnecessary; it does not change Linux firewall policies.", "Docker-published ports can bypass ordinary UFW INPUT rules. Validate firewall policies and access from a different device and from outside the allowed subnet. Check wired and Wi-Fi routes separately."],
       commands:[{label:"Check school network",command:"sudo weave network status"},{label:"Review network setup",command:"sudo weave network setup"}],
       tips:["Never treat an accessible localhost endpoint as proof the exam portal is safely accessible throughout the school."],
      },
      {id:"linux-hosts",title:"Manual DNS: Linux student computers (default)",
       paragraphs:["If router DHCP DNS setup is not available, edit /etc/hosts on EACH Linux client that must open the CBT student URL. The hosts file supplies a direct hostname-to-IP mapping; it does not issue a TLS certificate or modify the school's router. Use the actual paired hostname from weave network url and the server's school LAN IPv4 address, not an internal Docker/WSL address.", "Open /etc/hosts with sudo nano (or another privileged text editor). Add the example line using your own server IP and hostname. If an entry for that hostname exists, update it instead of introducing conflicting duplicates. Save with Ctrl+O, Enter, then exit with Ctrl+X.", "Most Linux systems read /etc/hosts without a DNS cache flush. If systemd-resolved is installed, sudo resolvectl flush-caches can clear its cache; skip it if resolvectl is unavailable. Verify with getent hosts because it follows the system hostname lookup configuration, then test the exact HTTPS URL."],
       commands:[
         {label:"On each Linux client: edit hosts file",command:"sudo nano /etc/hosts"},
         {label:"Example line to add inside hosts file — NOT a shell command",command:"192.168.1.12 test-server1.testschool1.cbt.weavecloudspace.com"},
         {label:"Optional cache flush when resolvectl is available",command:"sudo resolvectl flush-caches"},
         {label:"Confirm client-side hostname resolution (replace hostname)",command:"getent hosts test-server1.testschool1.cbt.weavecloudspace.com"},
         {label:"Verify HTTPS using the hostname (replace hostname)",command:"curl -I https://test-server1.testschool1.cbt.weavecloudspace.com"},
       ],
       tips:["Repeat the entry on each student device. If the CBT server changes IP or is paired under a new hostname, update those client entries.", "Manual DNS is the default documented approach today. WEAVE's Linux CoreDNS service and its commands remain available as an optional, more centralized alternative."],
      },
      {id:"linux-dns",title:"CoreDNS on native Linux (optional)",
       paragraphs:["Install WEAVE CBT and pair with WEAVE Cloud first. Activate trusted HTTPS using sudo weave tls. The new Linux integration runs CoreDNS as the dedicated weave-cbt-coredns.service under systemd and starts it automatically after reboot. No separate wizard, DHCP server or router automation is installed.", "Run sudo weave network dns setup. If multiple eligible private adapters exist, specify --interface eth0 (substitute your school adapter). Setup checks the downloaded CoreDNS Linux amd64 archive against its pinned SHA-256 checksum and publishes the paired HTTPS hostname at the server's private IP.", "Inspect the Linux host firewall before changing router DHCP DNS. Only the intended school subnet should reach DNS over UDP and TCP port 53. Verify the DNS answer over both protocols from a separate student laptop and verify that ordinary internet names resolve while online. Then set the router DHCP DNS address to the server IP and reconnect a test student device.", "To remove CoreDNS, restore the router's previous DHCP DNS configuration first, then run sudo weave network dns remove. WEAVE deletes only its managed systemd unit and DNS files, leaving examination data and unrelated resolvers untouched."],
       commands:[{label:"Enable HTTPS after pairing",command:"sudo weave tls"},{label:"Install headless CoreDNS",command:"sudo weave network dns setup"},{label:"Select an Ethernet interface",command:"sudo weave network dns setup --interface eth0"},{label:"Read CoreDNS status",command:"sudo weave network dns status"},{label:"Check managed systemd service",command:"sudo systemctl status weave-cbt-coredns.service"},{label:"Test local DNS from a student laptop (replace hostname)",command:"nslookup your-paired-cbt-hostname 192.168.1.12"}],
       tips:["WEAVE DNS setup never changes the router or the firewall automatically. Check other DNS services already listening on port 53 before attempting setup.","School exam delivery can continue without internet after initial pairing and synchronization, provided local DNS and HTTPS remain functional."],
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
       paragraphs:["Use the exact hostname assigned to your paired server. If router/DHCP-managed DNS is unavailable, map that hostname to the server's reachable school LAN IPv4 address in the hosts file on every student computer; follow the Windows or Linux manual DNS sections.", "Provision and verify HTTPS with a certificate valid for that hostname. Editing a hosts file does not create or renew certificates.", "Never make local server database credentials or pairing secrets publicly accessible."]},
    ],
  },
  {
    id:"networking",title:"Networking and HTTPS",
    summary:"Router setup, DNS, firewall, LAN and browser trust.",
    icon:"Network",
    sections:[
      {id:"lan",title:"Plan the school LAN",
       paragraphs:["Reserve the server IP on the school router. Run weave network setup; when a school-owned Wi-Fi is marked Public in Windows, approve only that connection with weave network trust.", "Test both Ethernet and Wi-Fi clients from the school network. Disable client isolation only if it blocks exam devices from reaching the server. Never expose CBT to the public internet."]},
      {id:"dns",title:"How student computers resolve the CBT hostname",
       paragraphs:["Your CBT server has two different identifiers: its private LAN IP (the address student computers reach on the school network) and its assigned HTTPS hostname (the name that matches its browser-trusted certificate). Every student computer must resolve that exact hostname to the server's LAN IP; a certificate alone does not make DNS resolution work.", "CURRENT DEFAULT when you cannot configure the router or DHCP DNS settings: edit the hosts file on EACH Windows or Linux student computer. Windows: open C:\\Windows\\System32\\drivers\\etc\\hosts in Administrator Notepad, add the server-IP/hostname line, save, then run ipconfig /flushdns. Linux: edit /etc/hosts with sudo, add the same mapping, and use getent hosts to verify. Windows and Linux instructions above contain copyable commands.", "The example mapping uses 192.168.1.12 and test-server1.testschool1.cbt.weavecloudspace.com. These are NOT universal server details. Get the actual hostname with weave network url and the school LAN IP with weave network status; never copy an example unchanged.", "OPTIONAL alternative: WEAVE CoreDNS and router/DHCP configuration are still available. Windows uses an optional CoreDNS service, Linux uses an optional systemd CoreDNS service. Only after verifying DNS from a student computer should administrators configure router DHCP DNS; this is not automated by WEAVE."],
       commands:[
         {label:"On the CBT server: find your paired student URL",command:"weave network url"},
         {label:"On the CBT server: identify its school LAN IP",command:"weave network status"},
         {label:"Windows student computer: open hosts file as Administrator",command:"notepad C:\\Windows\\System32\\drivers\\etc\\hosts"},
         {label:"Example hosts-file entry (replace both values; NOT a terminal command)",command:"192.168.1.12 test-server1.testschool1.cbt.weavecloudspace.com"},
         {label:"Windows student computer: flush resolver cache",command:"ipconfig /flushdns"},
         {label:"Linux student computer: edit hosts file",command:"sudo nano /etc/hosts"},
         {label:"Linux student computer: check system hostname resolution",command:"getent hosts test-server1.testschool1.cbt.weavecloudspace.com"},
         {label:"Optional CoreDNS service setup (advanced)",command:"weave network dns setup"},
         {label:"Inspect optional CoreDNS status",command:"weave network dns status"},
       ],
       tips:["Client hosts-file edits are not propagated from the CBT server to student devices. Repeat on each device; if the LAN IP or pairing hostname changes, update every mapping.", "Do not confuse the WSL or Docker internal address with the school LAN IP, publish private CBT services to the public internet, or disable certificate validation."]},
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
