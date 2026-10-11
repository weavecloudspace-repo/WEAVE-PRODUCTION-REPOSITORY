import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Download,
  HardDrive,
  MonitorDown,
  RefreshCw,
  Server,
  ShieldCheck,
  Wifi,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import DashboardLayout from "../../components/layout/DashboardLayout";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import { useToast } from "../../hooks/useToast";
import { parseApiError } from "../../services/api";
import { cbtService } from "../../services/cbtService";

const CHANNEL_LABELS = {
  production: "Production",
  staging: "Staging",
};

function PackageDetail({ label, value }) {
  return (
    <div className="min-w-0">
      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-muted">
        {label}
      </p>
      <p className="mt-1 break-words text-sm font-semibold text-text">{value}</p>
    </div>
  );
}

function SetupStep({ number, title, children }) {
  return (
    <div className="flex gap-3">
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary/10 text-sm font-bold text-primary">
        {number}
      </div>
      <div className="min-w-0 pt-0.5">
        <p className="text-sm font-semibold text-text">{title}</p>
        <p className="mt-1 text-sm leading-6 text-text-muted">{children}</p>
      </div>
    </div>
  );
}

export default function CBTServerSetupPage() {
  const navigate = useNavigate();
  const { showError, showSuccess } = useToast();
  const [release, setRelease] = useState(null);
  const [loadingRelease, setLoadingRelease] = useState(true);
  const [releaseError, setReleaseError] = useState("");
  const [creatingPairingCode, setCreatingPairingCode] = useState(false);

  const loadRelease = useCallback(async () => {
    setLoadingRelease(true);
    setReleaseError("");
    try {
      const response = await cbtService.getLatestRelease();
      setRelease(response);
    } catch (error) {
      const parsed = parseApiError(
        error,
        "The WEAVE CBT installer is temporarily unavailable.",
      );
      setRelease(null);
      setReleaseError(parsed.message);
    } finally {
      setLoadingRelease(false);
    }
  }, []);

  useEffect(() => {
    loadRelease();
  }, [loadRelease]);

  const packageName = useMemo(
    () => release?.installer_asset || "WEAVE CBT Windows installer",
    [release?.installer_asset],
  );

  const windowsCli = (release?.packages || []).find(
    (packageItem) =>
      packageItem.platform === "windows" && packageItem.kind === "cli",
  );
  const linuxPackages = (release?.packages || []).filter(
    (packageItem) => packageItem.platform === "linux",
  );

  const startDownload = (packageItem = null) => {
    if (!release?.installer_url) return;

    const downloadLink = document.createElement("a");
    if (packageItem) {
      downloadLink.href = packageItem.url;
      downloadLink.download = packageItem.asset;
    } else {
      downloadLink.href = release.installer_url;
      downloadLink.download = packageName;
    }
    downloadLink.rel = "noopener noreferrer";
    downloadLink.style.display = "none";
    document.body.appendChild(downloadLink);
    downloadLink.click();
    downloadLink.remove();
  };

  const continueToPairing = async () => {
    setCreatingPairingCode(true);
    try {
      const response = await cbtService.createPairingCode();
      showSuccess("Pairing code generated. Enter it in WEAVE CBT Manager.");
      navigate("/admin/cbt/pairing-code", {
        state: { pairingCode: response },
      });
    } catch (error) {
      showError(
        parseApiError(error, "Could not create a pairing code.").message,
      );
    } finally {
      setCreatingPairingCode(false);
    }
  };

  const channelLabel = CHANNEL_LABELS[release?.channel] || "Current environment";

  return (
    <DashboardLayout role="admin" title="Set up CBT Server">
      <div className="mx-auto w-full max-w-6xl space-y-5 pb-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Back to CBT servers"
              onClick={() => navigate("/admin/cbt")}
            >
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">
                WEAVE CBT
              </p>
              <h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-[1.75rem]">
                Set up a local exam server
              </h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-text-muted">
                Download the installer for this WEAVE environment, complete the
                local setup on the computer that will host exams, then return
                here to generate a short-lived pairing code.
              </p>
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            className="shrink-0 justify-center"
            onClick={() => navigate("/admin/cbt/documentation")}
          >
            <BookOpen className="h-4 w-4" />
            Documentation
          </Button>
        </div>

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(320px,0.75fr)]">
          <Card className="overflow-hidden rounded-2xl border-border/80 p-0 shadow-sm">
            <div className="border-b border-border/70 bg-gradient-to-br from-primary/10 via-surface to-surface px-5 py-6 sm:px-7">
              <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex min-w-0 items-start gap-4">
                  <div className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-primary text-primary-foreground shadow-sm shadow-primary/20">
                    <MonitorDown className="h-7 w-7" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-lg font-semibold text-text">
                        WEAVE CBT for Windows
                      </h2>
                      {release ? (
                        <span className="rounded-full border border-primary/15 bg-primary/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-primary">
                          {channelLabel}
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-1 text-sm leading-6 text-text-muted">
                      Native desktop installer for 64-bit Windows. Includes WEAVE CBT Manager and the management CLI.
                    </p>
                  </div>
                </div>

                <Button
                  type="button"
                  className="shrink-0 justify-center"
                  disabled={!release?.installer_url || loadingRelease}
                  onClick={() => startDownload()}
                >
                  <Download className="h-4 w-4" />
                  Download installer
                </Button>
              </div>
            </div>

            <div className="px-5 py-6 sm:px-7">
              {loadingRelease ? (
                <div className="flex min-h-32 items-center justify-center rounded-xl border border-dashed border-border bg-surface-muted/30 px-4 text-center">
                  <div>
                    <RefreshCw className="mx-auto h-5 w-5 animate-spin text-primary" />
                    <p className="mt-3 text-sm font-medium text-text">
                      Checking the installer for this environment...
                    </p>
                  </div>
                </div>
              ) : releaseError ? (
                <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-4">
                  <div className="flex items-start gap-3">
                    <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold text-amber-900">
                        Installer metadata could not be loaded
                      </p>
                      <p className="mt-1 text-sm leading-6 text-amber-800">
                        {releaseError}
                      </p>
                      <Button
                        type="button"
                        variant="outline"
                        size="small"
                        className="mt-3"
                        onClick={loadRelease}
                      >
                        <RefreshCw className="h-4 w-4" />
                        Try again
                      </Button>
                    </div>
                  </div>
                </div>
              ) : (
                <>
                  <div className="grid gap-4 rounded-xl border border-border/70 bg-surface-muted/25 p-4 sm:grid-cols-2">
                    <PackageDetail
                      label="Installer"
                      value={packageName}
                    />
                    <PackageDetail
                      label="Manager version"
                      value={release?.manager_version || "--"}
                    />
                    <PackageDetail
                      label="CBT version"
                      value={release?.cbt_version || "--"}
                    />
                    <PackageDetail
                      label="Release channel"
                      value={channelLabel}
                    />
                  </div>

                  <div className="mt-4 flex items-start gap-3 rounded-xl border border-emerald-200/80 bg-emerald-50/60 p-4">
                    <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-emerald-700" />
                    <div>
                      <p className="text-sm font-semibold text-emerald-900">
                        Environment matched automatically
                      </p>
                      <p className="mt-1 text-sm leading-6 text-emerald-800">
                        WEAVE selected the {channelLabel.toLowerCase()} package
                        for this workspace. Do not install a package copied from
                        a different WEAVE environment.
                      </p>
                    </div>
                  </div>

                  {release?.installer_sha256 ? (
                    <div className="mt-4 rounded-xl border border-border/70 bg-surface-muted/25 p-4">
                      <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Windows desktop SHA-256</p>
                      <p className="mt-1 break-all font-mono text-xs text-text">{release.installer_sha256}</p>
                    </div>
                  ) : null}

                  {windowsCli ? (
                    <div className="mt-4 flex flex-col gap-3 rounded-xl border border-border/70 p-4 sm:flex-row sm:items-center sm:justify-between">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-text">Windows standalone CLI</p>
                        <p className="mt-1 break-all text-xs text-text-muted">{windowsCli.asset}</p>
                        <p className="mt-2 break-all font-mono text-xs text-text-muted">SHA-256: {windowsCli.sha256}</p>
                      </div>
                      <Button type="button" variant="outline" className="shrink-0 justify-center" onClick={() => startDownload(windowsCli)}>
                        <Download className="h-4 w-4" />
                        Download CLI
                      </Button>
                    </div>
                  ) : null}

                  {release?.release_notes ? (
                    <div className="mt-5">
                      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-text-muted">
                        Release notes
                      </p>
                      <p className="mt-2 text-sm leading-6 text-text-muted">
                        {release.release_notes}
                      </p>
                    </div>
                  ) : null}
                </>
              )}
            </div>

            <div className="border-t border-border/70 px-5 py-6 sm:px-7">
              <div className="flex items-start gap-3">
                <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
                  <Server className="h-5 w-5" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-text">WEAVE CBT for Linux</h2>
                  <p className="mt-1 text-sm leading-6 text-text-muted">
                    Ubuntu/Debian amd64 desktop package and an advanced standalone CLI archive.
                  </p>
                </div>
              </div>
              {release && linuxPackages.length ? (
                <div className="mt-4 space-y-3">
                  {linuxPackages.map((packageItem) => (
                    <div key={packageItem.asset} className="rounded-xl border border-border/70 p-4">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-text">
                            {packageItem.kind === "desktop" ? "Linux Desktop (.deb)" : "Linux CLI (.tar.gz)"}
                          </p>
                          <p className="mt-1 break-all text-xs text-text-muted">{packageItem.asset}</p>
                        </div>
                        <Button type="button" variant="outline" className="shrink-0 justify-center" onClick={() => startDownload(packageItem)}>
                          <Download className="h-4 w-4" />
                          Download
                        </Button>
                      </div>
                      <p className="mt-3 text-xs font-semibold text-text-muted">SHA-256</p>
                      <p className="mt-1 break-all font-mono text-xs text-text">{packageItem.sha256}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-3 text-sm text-text-muted">
                  {loadingRelease ? "Checking official Linux packages..." : "Linux downloads require a fully verified release."}
                </p>
              )}
              {release?.checksums_url ? (
                <a href={release.checksums_url} className="mt-4 inline-flex text-sm font-medium text-primary underline underline-offset-2" target="_blank" rel="noopener noreferrer">
                  View official SHA256SUMS
                </a>
              ) : null}
            </div>
          </Card>

          <Card className="rounded-2xl border-border/80 p-5 shadow-sm sm:p-6">
            <div className="flex items-center gap-3">
              <div className="grid h-10 w-10 place-items-center rounded-xl bg-secondary/10 text-secondary">
                <Server className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-base font-semibold text-text">
                  Before you pair
                </h2>
                <p className="mt-0.5 text-xs text-text-muted">
                  Complete setup on the server computer first.
                </p>
              </div>
            </div>

            <div className="mt-6 space-y-5">
              <SetupStep number="1" title="Choose a dedicated 64-bit exam server">
                Select a Windows or supported Ubuntu/Debian computer with sufficient storage for the local exam database and exam assets.
              </SetupStep>
              <SetupStep number="2" title="Install the correct desktop package">
                Run the Windows desktop setup as administrator, or install the Linux .deb through your OS package manager. The Linux .tar.gz archive is intended for experienced administrators.
              </SetupStep>
              <SetupStep number="3" title="Complete platform setup and any required reboot">
                On Windows, enable WSL2 and restart when prompted. On Linux, verify systemd, Docker, and your desktop authentication agent are available before administering services.
              </SetupStep>
              <SetupStep number="4" title="Wait until the Manager reports ready">
                The first setup needs internet access to prepare the runtime and
                pull the pinned CBT application image. Normal exam execution is
                designed to run on the school LAN.
              </SetupStep>
              <SetupStep number="5" title="Generate the pairing code last">
                Pairing codes are short-lived. Create one only after the local
                Manager is ready to accept it.
              </SetupStep>
            </div>
          </Card>
        </div>

        <Card className="rounded-2xl border-border/80 p-5 shadow-sm sm:p-6">
          <div className="grid gap-5 md:grid-cols-3">
            <div className="flex gap-3">
              <HardDrive className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
              <div>
                <p className="text-sm font-semibold text-text">Local data stays local</p>
                <p className="mt-1 text-sm leading-6 text-text-muted">
                  Exam content, attempts and the CBT database remain on the
                  school-controlled server.
                </p>
              </div>
            </div>
            <div className="flex gap-3">
              <Wifi className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
              <div>
                <p className="text-sm font-semibold text-text">Internet for setup and sync</p>
                <p className="mt-1 text-sm leading-6 text-text-muted">
                  Initial installation and WEAVE synchronization require internet
                  access; active exams are served locally over the LAN.
                </p>
              </div>
            </div>
            <div className="flex gap-3">
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
              <div>
                <p className="text-sm font-semibold text-text">One environment per install</p>
                <p className="mt-1 text-sm leading-6 text-text-muted">
                  Production and staging installers use separate identities so a
                  test installation cannot silently replace production.
                </p>
              </div>
            </div>
          </div>
        </Card>

        <Card className="rounded-2xl border-border/80 p-5 shadow-sm sm:p-6">
          <h2 className="text-base font-semibold text-text">School network and security checklist</h2>
          <div className="mt-4 grid gap-4 text-sm leading-6 text-text-muted md:grid-cols-2">
            <div>
              <p className="font-semibold text-text">LAN and DNS</p>
              Reserve the server IP on the school router and configure its local DNS name to resolve to that private IP.
              Test the staff and student portals from another wired or Wi-Fi device, not just localhost.
              Use school-network firewall restrictions and verify actual access from an untrusted network.
            </div>
            <div>
              <p className="font-semibold text-text">HTTPS and offline exams</p>
              Configure trusted HTTPS with the correct hostname and certificate, then test in a normal student browser.
              Never disable certificate verification. Internet is required for setup and WEAVE sync;
              verify exam operation with the internet disconnected before a live examination.
            </div>
            <div>
              <p className="font-semibold text-text">Windows setup</p>
              Windows CBT uses WSL2. Configure the intended LAN forwarding and Windows Firewall policy,
              refresh forwarding after address changes, and test access from a separate computer.
            </div>
            <div>
              <p className="font-semibold text-text">Linux setup</p>
              Install the desktop .deb using the system package manager. Administrative actions may require Polkit.
              Published Docker ports can bypass ordinary UFW INPUT rules; confirm filtering from another device.
              Preserve volumes and back up school data before updates or removals.
            </div>
          </div>
        </Card>

        <div className="flex flex-col gap-3 rounded-2xl border border-primary/15 bg-primary/5 p-5 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm font-semibold text-text">
              Server installation complete?
            </p>
            <p className="mt-1 text-sm leading-6 text-text-muted">
              Continue only when WEAVE CBT Manager is open and ready for a pairing code.
            </p>
          </div>
          <Button
            type="button"
            className="shrink-0 justify-center"
            disabled={creatingPairingCode}
            onClick={continueToPairing}
          >
            {creatingPairingCode ? (
              <RefreshCw className="h-4 w-4 animate-spin" />
            ) : (
              <ArrowRight className="h-4 w-4" />
            )}
            {creatingPairingCode ? "Generating code..." : "Continue to pairing"}
          </Button>
        </div>
      </div>
    </DashboardLayout>
  );
}
