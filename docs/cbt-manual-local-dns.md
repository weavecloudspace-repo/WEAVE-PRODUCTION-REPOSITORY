# CBT student hostname resolution: manual setup (current default)

**Current supported default:** configure the operating system `hosts` file on **every
computer that needs to open the CBT student URL**. The CBT server's hostname is
issued by WEAVE Cloud when the server is paired, but **local name resolution is
not configured automatically** by pairing or certificate issuance.

The examples below use the test hostname
`test-server1.testschool1.cbt.weavecloudspace.com` and school server IP
`192.168.1.12`. **Replace both with your actual paired server hostname and its
current reachable school-LAN IPv4 address.** A staging installation can have a
`.cbt-staging.weavecloudspace.com` hostname; use the exact name returned by
WEAVE, not the example.

These steps affect local hostname resolution **only on the computer being
edited**. They do not change public DNS, WEAVE Cloud's DNS-01 TXT records, the
school router, or another student device. Run WEAVE network setup and HTTPS
activation separately and verify that the computer can reach the CBT server.

## Windows 10/11 — run as Administrator

1. Open **PowerShell as Administrator**. Open the Windows hosts file:

   ```powershell
   notepad C:\Windows\System32\drivers\etc\hosts
   ```

2. Add **one line** at the bottom, substituting your school server's LAN IP and
   assigned hostname:

   ```text
   192.168.1.12 test-server1.testschool1.cbt.weavecloudspace.com
   ```

   Save as the existing file named `hosts`, without adding `.txt`. If a
   matching hostname entry already exists, **update that entry** rather than
   creating contradictory mappings.

3. Refresh the Windows DNS resolver cache:

   ```powershell
   ipconfig /flushdns
   ```

4. Verify resolution and HTTPS:

   ```powershell
   ping test-server1.testschool1.cbt.weavecloudspace.com
   curl.exe -I https://test-server1.testschool1.cbt.weavecloudspace.com
   ```

   The `ping` output should resolve the hostname to `192.168.1.12`; ICMP
   replies are not required if ping is blocked. The HTTPS request must use the
   hostname (not the raw IP) so the certificate name matches.

## Linux (Ubuntu/Debian and other distributions)

1. Open a terminal with sudo privileges and edit the system hosts file:

   ```bash
   sudo nano /etc/hosts
   ```

2. Add or correct the hostname mapping:

   ```text
   192.168.1.12 test-server1.testschool1.cbt.weavecloudspace.com
   ```

3. Save and exit (in nano, **Ctrl+O**, Enter, then **Ctrl+X**).
   `/etc/hosts` is normally read by the system name-service switch without a
   cache flush. If the system uses **systemd-resolved**, you can additionally
   flush its cache:

   ```bash
   sudo resolvectl flush-caches
   ```

   Run that command only when `resolvectl` is installed. On systems without
   it, a resolver-cache flush may be unnecessary; avoid restarting unrelated
   networking services.

4. Verify resolution and HTTPS:

   ```bash
   getent hosts test-server1.testschool1.cbt.weavecloudspace.com
   curl -I https://test-server1.testschool1.cbt.weavecloudspace.com
   ```

   The `getent` output should include `192.168.1.12`.

## Important operating notes

- Repeat the appropriate steps on **each student device**, whether the server
  runs on Windows/WSL2 or native Linux. Editing the server's hosts file alone
  does **not** configure student devices.
- The mapping is for the **school LAN**. Student devices must be connected to
  that LAN and able to reach the server on TCP/443.
- If the server's LAN IP changes, update the hosts entry on every device. Use a
  DHCP reservation or stable server IP where possible.
- Certificates are still issued and renewed independently using WEAVE's
  DNS-01 flow. A correct hosts entry does not create or activate HTTPS.
- Do not disable browser certificate validation, ignore certificate errors, or
  invent a public A record for a private school IP.
- WEAVE's optional **CoreDNS** setup and related CLI commands remain supported
  as an advanced, opt-in alternative; this guide does **not** remove or disable
  them. Router/DHCP DNS changes are **not** the default procedure today.
- The public CA certificate applies to its exact assigned hostname. If you
  reinstall and pair as a new server, use the new hostname and replace old
  hosts entries.

Troubleshooting: first check the host mapping and server IP; then check
`weave network doctor` on the CBT host, Windows TCP/80 and TCP/443 portproxy
where applicable, firewall restrictions, and the active TLS certificate. On
Linux CBT hosts there is no Windows portproxy; ensure native Docker port
publishing and the host firewall permit student LAN traffic.
