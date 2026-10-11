import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Download,
  ExternalLink,
  FileArchive,
  HardDrive,
  Info,
  Laptop,
  Link2,
  MonitorDown,
  RefreshCw,
  Server,
  ShieldCheck,
  Terminal,
  Wifi,
  Wrench,
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

const DOWNLOAD_PLATFORMS = [
  {
    id: "windows-desktop",
    platform: "windows",
    kind: "desktop",
    title: "Windows Desktop",
    subtitle: "Recommended for a Windows 64-bit exam server",
    type: "Windows installer",
    Icon: MonitorDown,
    topic: "windows",
  },
  {
    id: "windows-cli",
    platform: "windows",
    kind: "cli",
    title: "Windows CLI",
    subtitle: "Command-line setup for advanced administrators",
    type: "Windows setup",
    Icon: Terminal,
    topic: "cli",
  },
  {
    id: "linux-desktop",
    platform: "linux",
    kind: "desktop",
    title: "Linux Desktop (.deb)",
    subtitle: "Graphical manager for Ubuntu / Debian amd64",
    type: ".deb package",
    Icon: Laptop,
    topic: "linux",
  },
  {
    id: "linux-cli",
    platform: "linux",
    kind: "cli",
    title: "Linux CLI (.tar.gz)",
    subtitle: "Standalone command line for experienced users",
    type: ".tar.gz archive",
    Icon: FileArchive,
    topic: "linux",
  },
];

const SETUP_STEPS = [
  {
    label: "Download",
    description: "Choose the package for your server computer and WEAVE environment.",
    Icon: Download,
  },
  {
    label: "Install",
    description: "Install locally, grant required permissions and restart if prompted.",
    Icon: HardDrive,
  },
  {
    label: "Configure",
    description: "Verify services, school LAN access, DNS and trusted HTTPS.",
    Icon: Wifi,
  },
  {
    label: "Pair with WEAVE",
    description: "Generate a code here after the local CBT Manager is ready.",
    Icon: Link2,
  },
];

const SUPPORT_LINKS = [
  {
    title: "Need the CLI?",
    description: "Terminal commands for inspecting, starting and managing CBT.",
    topic: "cli",
    Icon: Terminal,
    label: "CLI reference",
  },
  {
    title: "Troubleshooting",
    description: "Resolve missing CLI, Docker, connectivity and HTTPS errors.",
    topic: "troubleshooting",
    Icon: Wrench,
    label: "Explore solutions",
  },
  {
    title: "System requirements",
    description: "Check server, operating system, networking and storage guidance.",
    topic: "quick-start",
    Icon: CircleHelp,
    label: "View requirements",
  },
];

function SizeLabel({ bytes }) {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes <= 0) return null;
  return <span>{(bytes / (1024 * 1024)).toFixed(1)} MB</span>;
}

function DownloadCard({ definition, packageItem, channelLabel, version, onDownload, onOpenDocs, disabled }) {
  const { Icon } = definition;
  const [showIntegrity, setShowIntegrity] = useState(false);

  return (
    <div className="flex h-full min-w-0 flex-col rounded-2xl border border-border/80 bg-surface p-4 shadow-sm transition hover:border-primary/25 hover:shadow-md sm:p-5">
      <div className="flex items-start justify-between gap-2">
        <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
          <Icon className="h-5 w-5" />
        </div>
        {definition.id === "windows-desktop" && (
          <span className="rounded-full border border-primary/15 bg-primary/5 px-2.5 py-1 text-[10px] font-semibold text-primary">
            Recommended
          </span>
        )}
      </div>
      <h3 className="mt-4 text-sm font-semibold text-text">{definition.title}</h3>
      <p className="mt-1 min-h-10 text-xs leading-5 text-text-muted">{definition.subtitle}</p>
      <Button type="button" className="mt-4 w-full justify-center" disabled={disabled || !packageItem?.url}
        onClick={() => onDownload(packageItem, definition.id === "windows-desktop")}>
        <Download className="h-4 w-4" />
        {definition.kind === "cli" ? "Download CLI" : "Download installer"}
      </Button>
      <div className="mt-4 space-y-2 border-t border-border/70 pt-3 text-xs">
        <div className="flex items-center justify-between gap-2 text-text-muted"><span>Version</span><span className="font-semibold text-text">{version || "Not available"}</span></div>
        <div className="flex items-center justify-between gap-2 text-text-muted"><span>Channel</span><span className="font-semibold text-text">{channelLabel}</span></div>
        <div className="flex items-center justify-between gap-2 text-text-muted"><span>Format</span><span className="font-medium text-text">{definition.type}</span></div>
        {typeof packageItem?.size_bytes === "number" && (
          <div className="flex items-center justify-between gap-2 text-text-muted"><span>Size</span><span className="font-semibold text-text"><SizeLabel bytes={packageItem.size_bytes} /></span></div>
        )}
      </div>
      <p className="mt-3 min-h-4 break-all text-[11px] leading-4 text-text-muted">{packageItem?.asset || "Release package unavailable"}</p>
      <div className="mt-auto flex items-center justify-between gap-3 pt-3">
        <button type="button" onClick={() => onOpenDocs(definition.topic)} className="inline-flex min-h-8 items-center gap-1 text-xs font-semibold text-primary hover:underline">
          Setup guide <ArrowRight className="h-3.5 w-3.5" />
        </button>
        {packageItem?.sha256 && (
          <button type="button" aria-expanded={showIntegrity} onClick={() => setShowIntegrity((value) => !value)}
            className="min-h-8 text-xs font-semibold text-text-muted hover:text-text">
            {showIntegrity ? "Hide SHA-256" : "Verify SHA-256"}
          </button>
        )}
      </div>
      {showIntegrity && packageItem?.sha256 && (
        <div className="mt-3 rounded-xl border border-border bg-surface-muted/40 px-3 py-2">
          <p className="text-[11px] font-medium text-text-muted">SHA-256 checksum</p>
          <p className="mt-1 break-all font-mono text-[11px] leading-5 text-text">{packageItem.sha256}</p>
        </div>
      )}
    </div>
  );
}

function SetupStep({ number, item }) {
  const { Icon } = item;
  return (
    <li className="relative flex min-w-0 flex-col rounded-2xl border border-border/70 bg-surface-muted/15 p-4">
      <div className="flex items-center gap-2.5">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-primary/10 text-xs font-bold text-primary">{number}</span>
        <Icon className="h-4 w-4 text-primary" />
      </div>
      <h3 className="mt-3 text-sm font-semibold text-text">{item.label}</h3>
      <p className="mt-1 text-xs leading-5 text-text-muted">{item.description}</p>
      {number < SETUP_STEPS.length && (
        <ArrowRight className="absolute -right-2.5 top-1/2 z-10 hidden h-5 w-5 -translate-y-1/2 rounded-full bg-surface p-1 text-primary lg:block" aria-hidden="true" />
      )}
    </li>
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
      const parsed = parseApiError(error, "The WEAVE CBT installer is temporarily unavailable.");
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
  const channelLabel = CHANNEL_LABELS[release?.channel] || "Current environment";

  const packages = DOWNLOAD_PLATFORMS.map((definition) => {
    const packageItem = release?.packages?.find(
      (packageItem) =>
        packageItem.platform === "windows" && definition.platform === "windows"
          ? packageItem.kind === definition.kind
          : packageItem.platform === "linux" && definition.platform === "linux"
            ? packageItem.kind === definition.kind
            : false,
    );
    // Keep the existing Windows Desktop API fields compatible with older releases.
    if (!packageItem && definition.id === "windows-desktop" && release?.installer_url) {
      return { definition, packageItem: {
        asset: packageName,
        url: release.installer_url,
        sha256: release.installer_sha256,
      } };
    }
    return { definition, packageItem };
  });

  const startDownload = (packageItem = null, desktop = false) => {
    if (!release?.installer_url || (!packageItem && !desktop)) return;
    const downloadLink = document.createElement("a");
    if (desktop || !packageItem) {
      downloadLink.href = release.installer_url;
      downloadLink.download = packageName;
    } else {
      downloadLink.href = packageItem.url;
      downloadLink.download = packageItem.asset;
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
      showError(parseApiError(error, "Could not create a pairing code.").message);
    } finally {
      setCreatingPairingCode(false);
    }
  };

  const openDocs = (topic) => {
    navigate(topic ? "/admin/cbt/documentation?topic=" + encodeURIComponent(topic) : "/admin/cbt/documentation");
  };

  return (
    <DashboardLayout role="admin" title="Set up CBT Server">
      <div className="mx-auto w-full max-w-[1360px] space-y-6 pb-12">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3">
            <Button type="button" variant="ghost" size="icon" aria-label="Back to CBT servers" onClick={() => navigate("/admin/cbt")}>
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div className="min-w-0">
              <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-primary">WEAVE CBT</p>
              <h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-3xl">Set up a local exam server</h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-text-muted">Download the correct CBT package for your school server, finish local installation and return to connect it to this WEAVE workspace.</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {release && <span className="rounded-full border border-primary/15 bg-primary/5 px-3 py-2 text-xs font-semibold text-primary">{channelLabel} environment</span>}
            <Button type="button" variant="outline" size="sm" onClick={() => openDocs()}>
              <BookOpen className="h-4 w-4" /> Documentation
            </Button>
          </div>
        </div>

        <div className="overflow-hidden rounded-2xl border border-primary/10 bg-gradient-to-r from-primary/10 via-surface to-surface p-5 sm:p-7">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
            <div className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-primary text-primary-foreground shadow-sm shadow-primary/20">
              <MonitorDown className="h-6 w-6" />
            </div>
            <div className="flex-1">
              <h2 className="text-lg font-semibold text-text">Your school, your local exam server.</h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-text-muted">
                WEAVE CBT runs examinations on your school-controlled network. Choose a supported installer below,
                prepare your computer, confirm that students can reach it, then pair with your school workspace.
              </p>
            </div>
            <div className="hidden shrink-0 items-center gap-2 rounded-xl border border-primary/15 bg-surface/80 px-4 py-3 text-xs font-medium text-text-muted lg:flex">
              <ShieldCheck className="h-5 w-5 text-primary" /> Offline-ready exam delivery
            </div>
          </div>
        </div>

        <section aria-labelledby="cbt-download-heading">
          <Card className="rounded-2xl border-border/80 p-4 shadow-sm sm:p-6">
            <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 id="cbt-download-heading" className="text-lg font-semibold text-text">Download WEAVE CBT</h2>
                <p className="mt-1 text-sm text-text-muted">Choose a desktop installer or a standalone command-line package for the server computer.</p>
              </div>
              <div className="flex items-center gap-2 rounded-xl border border-border bg-surface-muted/30 px-3 py-2 text-xs">
                <span className="text-text-muted">Release channel</span>
                <span className="font-semibold text-text">{channelLabel}</span>
              </div>
            </div>

            {loadingRelease ? (
              <div className="flex min-h-36 items-center justify-center rounded-2xl border border-dashed border-border bg-surface-muted/30 p-6 text-center">
                <div><RefreshCw className="mx-auto h-5 w-5 animate-spin text-primary" /><p className="mt-3 text-sm text-text-muted">Checking official packages for this environment...</p></div>
              </div>
            ) : releaseError ? (
              <div role="alert" className="flex flex-col gap-4 rounded-xl border border-amber-300/60 bg-amber-50/70 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-start gap-3"><AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" />
                  <div><p className="text-sm font-semibold text-amber-900">Installer metadata could not be loaded</p><p className="mt-1 text-sm leading-6 text-amber-900">{releaseError}</p></div>
                </div>
                <Button type="button" variant="outline" size="sm" onClick={loadRelease}><RefreshCw className="h-4 w-4" /> Try again</Button>
              </div>
            ) : (
              <>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {packages.map(({definition, packageItem}) => (
                    <DownloadCard key={definition.id} definition={definition} packageItem={packageItem}
                      channelLabel={channelLabel} version={release?.manager_version} disabled={loadingRelease}
                      onDownload={startDownload} onOpenDocs={openDocs} />
                  ))}
                </div>
                <div className="mt-4 flex flex-col gap-3 rounded-xl border border-emerald-200/80 bg-emerald-50/50 p-4 sm:flex-row sm:items-start">
                  <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-700" />
                  <div className="flex-1">
                    <p className="text-sm font-semibold text-emerald-900">Environment matched automatically</p>
                    <p className="mt-1 text-xs leading-6 text-emerald-900">WEAVE selected the {channelLabel.toLowerCase()} release for this workspace. Do not mix staging and production packages.</p>
                  </div>
                  {release?.checksums_url && <a href={release.checksums_url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-8 shrink-0 items-center gap-1.5 text-xs font-semibold text-emerald-800 hover:underline">
                    <ExternalLink className="h-3.5 w-3.5" /> SHA256SUMS
                  </a>}
                </div>
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border/70 pt-4 text-xs text-text-muted">
                  <span>Manager version <strong className="text-text">{release?.manager_version || "—"}</strong> · CBT version <strong className="text-text">{release?.cbt_version || "—"}</strong></span>
                  {release?.release_notes && <span className="max-w-xl leading-5">{release.release_notes}</span>}
                </div>
              </>
            )}
          </Card>
        </section>

        <section aria-labelledby="cbt-steps-heading">
          <Card className="rounded-2xl border-border/80 p-4 shadow-sm sm:p-6">
            <div className="mb-4">
              <h2 id="cbt-steps-heading" className="text-lg font-semibold text-text">Quick start: four steps</h2>
              <p className="mt-1 text-sm text-text-muted">Follow this sequence to avoid pairing before the server is ready.</p>
            </div>
            <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {SETUP_STEPS.map((item, index) => <SetupStep key={item.label} number={index + 1} item={item} />)}
            </ol>
          </Card>
        </section>

        <section aria-label="Setup help" className="grid gap-3 sm:grid-cols-3">
          {SUPPORT_LINKS.map(({title, description, topic, Icon, label}) => (
            <button key={topic} type="button" onClick={() => openDocs(topic)}
              className="group flex min-w-0 items-start gap-3 rounded-2xl border border-border/80 bg-surface p-4 text-left shadow-sm transition hover:border-primary/30 hover:bg-primary/5 sm:p-5">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary"><Icon className="h-5 w-5" /></span>
              <span className="min-w-0"><span className="block text-sm font-semibold text-text">{title}</span><span className="mt-1 block text-xs leading-5 text-text-muted">{description}</span>
                <span className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-primary">{label} <ChevronRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" /></span>
              </span>
            </button>
          ))}
        </section>

        <Card className="rounded-2xl border-border/80 p-4 sm:p-6">
          <div className="grid gap-5 sm:grid-cols-3">
            <div className="flex items-start gap-3"><HardDrive className="mt-0.5 h-5 w-5 shrink-0 text-primary" /><div><h3 className="text-sm font-semibold text-text">Local school data</h3><p className="mt-1 text-xs leading-6 text-text-muted">Question banks, attempts and the exam database remain on your school's server. Back up data before maintenance.</p></div></div>
            <div className="flex items-start gap-3"><Wifi className="mt-0.5 h-5 w-5 shrink-0 text-primary" /><div><h3 className="text-sm font-semibold text-text">Internet and LAN</h3><p className="mt-1 text-xs leading-6 text-text-muted">Setup, pairing and synchronization require internet. Exams should be tested on the school LAN while offline.</p></div></div>
            <div className="flex items-start gap-3"><Server className="mt-0.5 h-5 w-5 shrink-0 text-primary" /><div><h3 className="text-sm font-semibold text-text">Network safety</h3><p className="mt-1 text-xs leading-6 text-text-muted">Reserve a private server IP, restrict firewall access and verify trusted HTTPS from a student device.</p></div></div>
          </div>
        </Card>

        <div className="flex flex-col gap-4 rounded-2xl border border-primary/20 bg-primary/5 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-surface text-primary"><Link2 className="h-5 w-5" /></span>
            <div>
              <h2 className="text-base font-semibold text-text">Ready to connect your CBT server?</h2>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-text-muted">Complete installation and verify the local Manager first. Pairing codes expire, so generate one only when you're ready to enter it in WEAVE CBT.</p>
              <button type="button" onClick={() => openDocs("pairing")} className="mt-2 inline-flex min-h-8 items-center gap-1 text-xs font-semibold text-primary hover:underline">
                <Info className="h-3.5 w-3.5" /> How pairing works <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          <Button type="button" className="shrink-0 justify-center" disabled={creatingPairingCode} onClick={continueToPairing}>
            {creatingPairingCode ? <RefreshCw className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
            {creatingPairingCode ? "Generating code..." : "Continue to pairing"}
          </Button>
        </div>
      </div>
    </DashboardLayout>
  );
}
