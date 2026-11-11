# CLAUDE.md — this fork's layout

This is a fork of `Goblinmine/homelab-diagram` rebuilt for one specific lab: a flat
`192.168.7.0/24` LAN, AT&T fiber behind a BGW320 in IP passthrough, a UniFi UX Max gateway
with four mesh APs, TP-Link switching, and a four-node Proxmox cluster running 60 guests.

The original `CLAUDE.md` (the interview-driven adaptation guide) lives in the upstream repo
and is still the right document for adapting *this* code to *another* lab. This file records
what changed here so a future session does not re-derive it.

## Layout map of `build.py`

| Section | What it holds | Coordinates |
|---|---|---|
| `TOP: internet` | cloud, remote card, Cloudflare/Tailscale cards | `CX`, `CY0`, `RX_/RY_`, `CSX/CSY` |
| AT&T gateway | fiber port, four LAN ports, IP passthrough | `FY, FH`, `GWX, GWW` |
| UX Max | hardware list (left), services grid (right) | `OX, OY, OW, OH` |
| switch | 9 jacks, VLAN ticks, port labels | `BX, BY, BW, BH`, `PX0, PITCH` |
| right column | exposure, monitoring (2 cols), AP mesh + SSIDs, public hostnames | `IX_, IY_, IW_`, `apy`, `ph_y` |
| left column | networks table, fleet facts, legend | `vx, vy, vw`, `fy0`, `LEG_Y` |
| cluster | one block per node; each block splits into 1–3 sub-columns | `TXX, TWW`, `DY`, `GY`, `BLOCK_X` |
| storage | DS920+, `volume1`, pool disks, shares | `SY0`, `STW`, `SH0` |
| media pipeline | 4 nodes across, prowlarr + shares below | `MPX`, `MPW`, `r1`, `r2` |

## Things that are easy to break

- **Canvas height is derived, not constant.** `SVG.render()` emits the background based on
  `self.max_y`, which `rect`/`text`/`icon`/`line` update. Never reintroduce a fixed `H`; the old
  code grew it by hand and clipped content twice.
- **Cluster columns are adaptive.** `SUBS` picks 1–3 sub-columns per node from its guest count,
  targeting `ROWS = 8` rows. Add guests and the block widens; the `assert nx(3) + BLOCK_W[3]`
  catches overflow.
- **Chip text is measured in Fira Code, not the proportional font.** `guest_chip()` uses
  `tw(..., mono=True)` for the IP and id (`measure()` would under-report and the hostname
  would collide with the IP — that bug happened). Hostnames are only printed when the measured
  width fits; the complete list is in the "Public services" card.
- **`fit()` shrinks instead of clipping.** Any label passed through it fits its box. Use it for
  anything data-driven; only hand-tuned static strings can skip it.
- **Redaction covers three things**: `{domain}`/`paine.pro` → `example.com`, SSID names, and the
  public WAN IP (`PUBLIC_IP` → `public IPv4 · /23`). All three go through `sub()`, so anything
  drawn by `S.text` is covered. Verify before publishing:

  ```bash
  grep -c 'paine\.pro\|KingArthur\|104\.13\.212\.149' out/homelab.svg   # must be 0
  ```

## Facts and their sources

`inventory.yaml` was filled on 2026-11-11 from live read-only checks:

- `pvesh get /cluster/resources --type vm` — 60 running guests (53 QEMU + 7 LXC), ids, RAM.
- UniFi API — WAN uplink (`1G` negotiated on `eth1`), VLANs 20/30, the three SSIDs, four mesh
  APs on 6 GHz, the two port forwards, and the fixed-IP map.
- `dig @192.168.7.55 <name>.flatcar-lab.internal` — every VM's address.
- Synology DSM over SSH — DS920+, four SHR disks (24+20+16+12 TB), NVMe cache, `volume1`
  19 TiB used of 42 TiB.
- Prometheus `speedtest_tracker_download_bits` — ~940/900 Mbit/s peak.

If a fact changes, change it in `inventory.yaml` only; `build.py` reads everything from there.

## Verify a render

```bash
python3 build.py && python3 build.py --unredacted
# look at the PNG yourself, then zoom into dense areas (PNG px = SVG × 1.6):
magick out/homelab.png -crop 1400x700+500+1500 +repage /tmp/crop.png
```

The `assert`s at the end of `build.py` cover the vertical chain, the right column, the
cluster's guest list and both bottom cards. They do not catch text overlap inside a card —
that still needs eyes on the PNG.
