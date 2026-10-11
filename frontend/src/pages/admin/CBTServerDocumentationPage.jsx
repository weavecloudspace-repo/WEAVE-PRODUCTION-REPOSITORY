import { ArrowLeft, CheckCircle2, Globe2, ShieldCheck, Wifi } from "lucide-react";
import { useNavigate } from "react-router-dom";

import DashboardLayout from "../../components/layout/DashboardLayout";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";

function Command({ children }) {
  return (
    <code className="mt-2 block overflow-x-auto rounded-lg bg-slate-950 px-4 py-3 font-mono text-xs text-slate-50">
      {children}
    </code>
  );
}

function Section({ title, children }) {
  return (
    <Card className="rounded-2xl border-border/80 p-5 shadow-sm sm:p-6">
      <h2 className="text-lg font-semibold text-text">{title}</h2>
      <div className="mt-3 space-y-3 text-sm leading-6 text-text-muted">{children}</div>
    </Card>
  );
}

export default function CBTServerDocumentationPage() {
  const navigate = useNavigate();

  return (
    <DashboardLayout role="admin" title="CBT Server Documentation">
      <div className="mx-auto w-full max-w-5xl space-y-5 pb-10">
        <div className="flex items-start gap-3">
          <Button variant="ghost" size="icon" aria-label="Back to CBT setup" onClick={() => navigate("/admin/cbt/setup-server")}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-primary">WEAVE CBT</p>
            <h1 className="mt-1 text-2xl font-semibold text-text">School server installation and network guide</h1>
            <p className="mt-2 text-sm leading-6 text-text-muted">
              Windows and Linux setup, LAN access, local DNS, trusted HTTPS, offline exams and recovery.
            </p>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <Card className="p-4">
            <Wifi className="h-5 w-5 text-primary" />
            <p className="mt-2 text-sm font-semibold text-text">Local-first examination</p>
            <p className="mt-1 text-xs text-text-muted">Students access the server over a school LAN. Active exams should not depend on internet connectivity.</p>
          </Card>
          <Card className="p-4">
            <Globe2 className="h-5 w-5 text-primary" />
            <p className="mt-2 text-sm font-semibold text-text">Internet for setup and sync</p>
            <p className="mt-1 text-xs text-text-muted">Initial images, WEAVE pairing, credentials, academic sync and score uploads need internet.</p>
          </Card>
          <Card className="p-4">
            <ShieldCheck className="h-5 w-5 text-primary" />
            <p className="mt-2 text-sm font-semibold text-text">Authorized access only</p>
            <p className="mt-1 text-xs text-text-muted">Use a scoped school subnet and valid certificates; do not publish private exam services to the public internet.</p>
          </Card>
        </div>

        <Section title="1. Install on Windows (64-bit)">
          <p>Download the Windows Desktop Manager installer for your current WEAVE environment. Run it as Administrator. The installer includes the native GUI and the WEAVE CLI.</p>
          <p>The first server setup provisions a dedicated WSL2 Ubuntu distribution named <code>WeaveCBT</code>, with Docker and persistent school data. Allow any requested restart before resuming setup. WSL2 and Windows virtualization are system prerequisites, not separate WEAVE applications.</p>
          <Command>{"& \"C:\\Program Files\\WeaveCBT\\weave.exe\" release"}</Command>
          <Command>{"& \"C:\\Program Files\\WeaveCBT\\weave.exe\" status --json"}</Command>
          <p>Use <code>weave doctor</code> to inspect Compose and local endpoints, and <code>weave logs</code> for troubleshooting. These commands do not uninstall the server.</p>
          <p>To inspect forwarding, run <code>netsh interface portproxy show v4tov4</code>. A WEAVE-managed LAN listener requires an intended private address, a Private or Domain network profile and the correct firewall scope. After the WSL address changes, use the manager's Refresh LAN action.</p>
        </Section>

        <Section title="2. Install on Linux (Ubuntu/Debian amd64)">
          <p>Use the published Desktop <code>.deb</code> for a graphical system. Install it using your distribution package manager. The standalone <code>.tar.gz</code> CLI is an alternative for experienced administrators, not an additional package to install over the desktop version.</p>
          <Command>sudo apt install ./weave-cbt-desktop-production-linux-amd64.deb</Command>
          <p>For WEAVE staging, download the corresponding <code>staging</code> asset instead. Confirm the filename and SHA-256 from the current environment's download page before installation.</p>
          <p>Docker/systemd must be available. Desktop administrative operations require a functioning Polkit authentication agent. Do not add ordinary users to the unrestricted Docker group simply to make the GUI work.</p>
          <Command>ip -4 addr</Command>
          <Command>sudo ss -lntp</Command>
          <p>Docker-published ports can bypass simple UFW INPUT filtering. Confirm that actual client access is restricted to the intended school subnet using tests from a second device and an untrusted network.</p>
        </Section>

        <Section title="3. Router, local DNS and wired/Wi-Fi clients">
          <p>Reserve the server's private IPv4 address using your router's DHCP reservation facility. Configure the paired hostname as a local DNS A record pointing to that reserved IP. Ask student computers to use the school's resolver through DHCP.</p>
          <p>On networks without managed DNS, hosts-file entries can serve as a small temporary test, but they must be maintained on every client and are unsuitable for large examinations. Never publish RFC1918 private addresses as public DNS A records.</p>
          <p>Confirm that both wired and Wi-Fi clients resolve the paired hostname to the same expected private IP and can reach <code>/student</code> and <code>/staff</code>.</p>
          <Command>nslookup your-paired-cbt-hostname</Command>
        </Section>

        <Section title="4. HTTPS, pairing and exam safety">
          <p>Generate a pairing code after the local manager is ready. Enter the code locally and use the hostname WEAVE assigns to that server. Keep pairing credentials and runtime environment files private.</p>
          <p>Enable a trusted certificate for the exact paired FQDN; ensure DNS points to the local host inside the school LAN. If HTTP returns 308, confirm the HTTPS destination, SNI, certificate name and full trust chain rather than disabling verification.</p>
          <p>Before an exam session, verify students can authenticate from a different computer and the CBT site continues operating with the internet disconnected. Restore connectivity after the test to resume WEAVE synchronization.</p>
          <p>Back up the database and local volumes before upgrades. Never unregister the WEAVE WSL distribution or purge Docker volumes unless school exam data is deliberately being erased.</p>
        </Section>

        <Section title="5. Diagnostics and common faults">
          <p><strong className="text-text">CLI missing in GUI:</strong> Run <code>weave release</code> directly, inspect the exact GUI diagnostic, and confirm the desktop package's executable and assets are installed together. Do not repeatedly delete school data to fix a GUI detection error.</p>
          <p><strong className="text-text">Cannot connect from a student device:</strong> Check the LAN address, route, firewall rule, DNS response and whether school Wi-Fi client isolation is enabled. A successful localhost check is not sufficient.</p>
          <p><strong className="text-text">HTTPS warning:</strong> Match the browser hostname against the certificate and local DNS entry. Do not disable browser or CLI certificate validation.</p>
          <p><strong className="text-text">After power failure:</strong> Check Docker/systemd or the dedicated WSL distribution, container health and database recovery before resuming any examination.</p>
          <div className="flex items-start gap-2 rounded-xl bg-primary/5 p-3 text-text">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <p>These instructions are a setup reference. Validate the actual server and student LAN before using WEAVE CBT in a live examination.</p>
          </div>
        </Section>
      </div>
    </DashboardLayout>
  );
}
