# Deployment Guide — M&S Card Calculator

Target: unprivileged Debian LXC on Proxmox VE, accessible over Tailscale only.

---

## 1. Container choice: privileged vs unprivileged

Use an **unprivileged** container. It maps the container's root (UID 0) to an
unprivileged host UID, so a container escape gives an attacker no host
privileges. The only complication is Tailscale, which needs a TUN device — this
is handled below without switching to privileged mode.

---

## 2. Create the LXC container

In the Proxmox web UI or via `pct`:

```bash
# On the Proxmox host shell:
pct create 200 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname ms-calculator \
  --cores 1 \
  --memory 256 \
  --swap 256 \
  --rootfs local-lvm:4 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 \
  --features nesting=1,keyctl=1
```

- **Debian 12 (Bookworm)** is the recommended template — stable, long-lived,
  small. Download it first via Proxmox → local → CT Templates → Templates.
- `nesting=1` is needed for some Tailscale kernel operations.
- `keyctl=1` is required by Tailscale's key storage.
- 4 GB root disk and 256 MB RAM are generous for this workload.

---

## 3. Persistent data: bind-mount for SQLite

Create a directory on the host (or a ZFS dataset if you use ZFS) that will
survive container rebuilds, then bind-mount it into the container.

```bash
# On the Proxmox host:
mkdir -p /mnt/pve/data/ms-calculator

# Stop the container if running, then add the mount point:
pct set 200 --mp0 /mnt/pve/data/ms-calculator,mp=/data,backup=1

# Start the container:
pct start 200
```

`backup=1` tells Proxmox's vzdump to include this mount point when backing up
the container — see §8.

If you use ZFS, replace the host path with a dedicated dataset:

```bash
zfs create rpool/data/ms-calculator
pct set 200 --mp0 /rpool/data/ms-calculator,mp=/data,backup=1
```

---

## 4. Install Tailscale inside the container

Tailscale runs **inside** the container rather than relying on a subnet router.
This is simpler and means the container's firewall and bind address are all
self-contained. The TUN device is what requires the extra container config above.

```bash
# Inside the container (pct enter 200 or ssh in):
apt update && apt install -y curl

curl -fsSL https://tailscale.com/install.sh | sh

# Bring up Tailscale and authenticate:
tailscale up --advertise-tags=tag:ms-calculator

# Note the Tailscale IP:
tailscale ip -4
# e.g. 100.x.x.x — you will need this in step 6.
```

If Tailscale complains about `/dev/net/tun` not existing, create it on the
**host** for this container:

```bash
# On the Proxmox host:
echo 'lxc.cgroup2.devices.allow = c 10:200 rwm' >> /etc/pve/lxc/200.conf
echo 'lxc.mount.entry = /dev/net/tun dev/net/tun none bind,create=file' \
  >> /etc/pve/lxc/200.conf
pct restart 200
```

---

## 5. Install the application

```bash
# Inside the container:
apt install -y python3 python3-venv git

useradd -r -s /bin/false -d /opt/ms-calculator mscalc

# Copy the app files (from your workstation or git clone):
mkdir -p /opt/ms-calculator
# scp -r /path/to/ms-calculator/* root@<ct-ip>:/opt/ms-calculator/
# or: git clone <your-repo> /opt/ms-calculator

cd /opt/ms-calculator
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# Create the data directory with correct ownership:
mkdir -p /data
chown mscalc:mscalc /data
```

---

## 6. Configure and install the systemd unit

Edit `deploy/ms-calculator.service`: set `MS_CALC_HOST` to the Tailscale IP
you noted in §4, and set `MS_CALC_SECRET` to a long random string
(`python3 -c "import secrets; print(secrets.token_hex(32))"`).

```bash
# Inside the container:
cp /opt/ms-calculator/deploy/ms-calculator.service /etc/systemd/system/

systemctl daemon-reload
systemctl enable ms-calculator
systemctl start ms-calculator
systemctl status ms-calculator
```

The app binds **only** to `MS_CALC_HOST` (the Tailscale IP). It will not
listen on `0.0.0.0`, the LAN interface, or localhost.

---

## 7. Verify Tailscale-only access

These checks confirm the app is unreachable from outside the tailnet.

### 7a — confirm the listening address

```bash
# Inside the container:
ss -tlnp | grep 5000
# Must show 100.x.x.x:5000, NOT 0.0.0.0:5000 or :::5000
```

### 7b — confirm reachability from a tailnet device

From any machine on your tailnet:

```bash
curl -s http://100.x.x.x:5000/   # should return the app HTML
```

### 7c — confirm unreachability from the LAN

From a machine on your LAN that is **not** enrolled in Tailscale:

```bash
curl --connect-timeout 5 http://<container-LAN-ip>:5000/
# Must time out or refuse — not return the app
```

### 7d — confirm unreachability from the internet

From a machine outside your network (a phone on mobile data, or a VPS):

```bash
curl --connect-timeout 5 http://<your-public-IP>:5000/
# Must time out — your router should have no port-forward for 5000
```

If any of 7c or 7d succeed, the app is listening on a broader interface than
intended. Re-check `MS_CALC_HOST` in the unit file and restart the service.

---

## 8. Backups

### Proxmox vzdump (container-level backup)

Proxmox's built-in backup captures the entire container including the
bind-mounted `/data` directory (because `backup=1` was set in §3).

In the Proxmox web UI: Datacenter → Backup → Add. Schedule it to run nightly
or weekly, targeting the storage of your choice. The SQLite WAL files
(`card.db-shm`, `card.db-wal`) are included automatically.

### SQLite-only snapshot (lightweight alternative)

If you want a portable copy of just the database without a full container dump:

```bash
# On the Proxmox host (or from the container via cron):
sqlite3 /mnt/pve/data/ms-calculator/card.db ".backup /mnt/pve/data/ms-calculator/card-$(date +%Y%m%d).db"
```

The `.backup` command uses the SQLite online backup API — it is safe to run
against a live database with no need to stop the app.

Add this to a cron job on the host to run nightly:

```
0 2 * * * sqlite3 /mnt/pve/data/ms-calculator/card.db \
  ".backup /mnt/pve/data/ms-calculator/card-$(date +\%Y\%m\%d).db"
```

Prune old snapshots to taste (`find ... -mtime +30 -delete`).

---

## Summary checklist

- [ ] Unprivileged LXC 200 created with `nesting=1,keyctl=1`
- [ ] `/data` bind-mounted with `backup=1`
- [ ] TUN device accessible inside container (verified with `ip tuntap`)
- [ ] Tailscale running and authenticated inside container
- [ ] App installed under `/opt/ms-calculator`, venv built
- [ ] `MS_CALC_HOST` set to Tailscale IP in unit file
- [ ] `MS_CALC_SECRET` set to a random value
- [ ] systemd unit enabled and started
- [ ] `ss -tlnp` shows `100.x.x.x:5000` only
- [ ] Reachable from tailnet device
- [ ] Not reachable from LAN or internet
- [ ] Proxmox backup schedule configured
