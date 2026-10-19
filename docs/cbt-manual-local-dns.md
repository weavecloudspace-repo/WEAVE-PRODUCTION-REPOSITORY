# CBT student hostname resolution — offline setup and manual fallback

WEAVE CBT offers a **portable offline client-configuration package** for Windows
and Linux student computers. It configures the OS `hosts` file locally; it does
**not** change the router, public DNS, pairing identity, certificates, or other
student computers. Configuring the server alone does not configure its clients.

## Recommended: USB client setup (Windows and Linux)

On the **CBT server**, first finish pairing, `weave network setup` (on Windows
WSL2), and `weave tls` activation. Then export a package using the installed
WEAVE CLI:

```bash
weave network client export --output <directory>
```

The export reads the **active paired HTTPS hostname** and school LAN address
from WEAVE's existing configuration. It refuses unpaired or incomplete setups.
The package is specific to the **server operating system**:

- Windows server: `WEAVE-CBT-Client-Windows.zip`, containing
  `WEAVE-CBT-Client-Setup.exe` and `weave-client.json`.
- Native Linux server: `WEAVE-CBT-Client-Linux.zip`, containing
  `weave-cbt-client-setup` and `weave-client.json`.

To configure **Windows** student computers:

1. Copy the Windows ZIP to a USB drive; extract it on the student PC.
2. Keep `weave-client.json` in the **same folder** as
   `WEAVE-CBT-Client-Setup.exe`.
3. Double-click `WEAVE-CBT-Client-Setup.exe` and approve the Windows
   Administrator/UAC prompt.
4. Review the utility's result: the WEAVE-owned hosts entry is updated, the
   Windows DNS resolver cache is flushed automatically if the entry changed,
   and hostname resolution and HTTPS connectivity are checked.

To configure **Linux** student computers:

1. Copy the Linux ZIP to a USB drive; extract it on the student PC.
2. Keep `weave-client.json` beside `weave-cbt-client-setup`.
3. Run the executable as root (no Python, Docker or WEAVE CLI required):

   ```bash
   chmod +x ./weave-cbt-client-setup
   sudo ./weave-cbt-client-setup
   ```

4. The utility updates the WEAVE-owned `/etc/hosts` entry and attempts
   automatic DNS-cache flushing through an available local resolver tool.
   Where no cache service is present, it reports that fact. It then checks
   resolution and HTTPS separately.

The setup tool **requires elevated permission** on each client because
modifying a system hosts file is an administrative operation. The ZIP and
executable can be shared offline; do not disable Defender or other device
protections to run an untrusted package. Obtain packages only from your
school's authorized administrator and inspect the hostname and IP displayed.

### What happens after the CBT server IP or paired domain changes?

Reconfigure the server, then generate and redistribute a **new package**.
Running the updated utility on each student PC replaces its previous
WEAVE-managed hosts block with one mapping for the new server:

```text
# BEGIN WEAVE CBT CLIENT RESOLUTION
192.168.1.12 test-server1.testschool1.cbt.weavecloudspace.com
# END WEAVE CBT CLIENT RESOLUTION
```

These example values are not universal; the tool reads your school's actual
paired values. Client state is recorded at
`C:\ProgramData\WeaveCBT\ClientNetwork\config.json` on Windows or
`/var/lib/weave-cbt/client-network/config.json` on Linux. It also saves a
recoverable hosts-file backup in that directory. Subsequent runs are
idempotent (no duplicates). A missing state file does not prevent replacement
of a well-formed, recognizable WEAVE-owned block.

**Ownership safety:** The tool refuses malformed/tampered WEAVE markers, a
disagreement between saved state and the hosts file, or a conflicting
unmanaged mapping. It does not automatically delete entries that an admin
previously wrote by hand. Resolve such conflicts deliberately using the
manual instructions below; do not delete unrelated hosts entries.

To remove the **currently active** WEAVE-owned mapping, run the matching
latest package with `--remove` as administrator/root. A package from an old
server configuration must not remove a newer installed mapping.

Updating or removing mappings happens **only on PCs that run the utility**;
this USB-based mechanism does not push changes to all computers. For centrally
managed LAN resolution, the optional WEAVE CoreDNS service with router/DHCP
DNS configuration remains supported.

### Troubleshooting the generated client utility

- A successful hosts-file change does **not** establish TCP/443 connectivity
  or guarantee the certificate is trusted. HTTPS issues are reported
  separately; do not bypass browser certificate verification.
- Client IP and hostname must correspond to the current school LAN and
  paired HTTPS identity. If they have changed, export another package.
- If there is an unmanaged duplicate hostname, preserve the unrelated entry
  and resolve the conflict before rerunning the utility.
- DNS cache flushing is automatic after changes; administrators need not
  run `ipconfig /flushdns` or `resolvectl flush-caches` for this workflow.
- Windows export runs from Windows and Linux export from Linux; there is
  no cross-OS `--platform` export flag in the current CLI.
- For server-side issues, use `weave network doctor`; client-side hosts
  changes cannot repair WSL forwarding, LAN firewall or the CBT server.

## Manual fallback: Windows 10/11

When the client utility cannot be used, open PowerShell **as Administrator**
and edit the Windows hosts file:

```powershell
notepad C:\Windows\System32\drivers\etc\hosts
```

Add **one mapping**, using the real paired server FQDN and reachable school
LAN IP (illustrative values shown):

```text
192.168.1.12 test-server1.testschool1.cbt.weavecloudspace.com
```

Update an existing mapping rather than creating contradictory entries.
Save the file as `hosts` (not `hosts.txt`), then manually flush the cache:

```powershell
ipconfig /flushdns
ping test-server1.testschool1.cbt.weavecloudspace.com
curl.exe -I https://test-server1.testschool1.cbt.weavecloudspace.com
```

`ping` should resolve the name to the LAN IP; ICMP replies may still be
blocked. HTTPS must use the hostname, not a bare IP, to match its certificate.

## Manual fallback: Linux

Edit `/etc/hosts` with root privileges:

```bash
sudo nano /etc/hosts
```

Add or correct the mapping:

```text
192.168.1.12 test-server1.testschool1.cbt.weavecloudspace.com
```

Save and check:

```bash
getent hosts test-server1.testschool1.cbt.weavecloudspace.com
curl -I https://test-server1.testschool1.cbt.weavecloudspace.com
```

Linux generally consults `/etc/hosts` directly. If `systemd-resolved` is
used and `resolvectl` is installed, manual changes may warrant:

```bash
sudo resolvectl flush-caches
```

That manual flush is **not** required when using the portable client utility;
the utility manages resolver refresh automatically where available.

## General operating notes

- Configure **each** student computer, not just the CBT server.
- Keep the server IP stable where possible (for example, DHCP reservation).
- The assigned hostname may end in `.cbt.weavecloudspace.com` or
  `.cbt-staging.weavecloudspace.com`; use the exact paired value.
- A hosts-file entry changes only local resolution and cannot issue/renew TLS.
- The local server must remain reachable from student PCs on the school LAN.
- Optional CoreDNS plus router/DHCP remains a separate advanced approach;
  no router or public DNS settings are modified by this utility.
