#!/usr/bin/env python3
"""Render the homelab diagram (r/homelab style) from inventory.yaml.

Usage: python3 build.py [--unredacted]   → out/homelab.svg + out/homelab.png
                                            (--unredacted → out/homelab-unredacted.*)
Content comes from inventory.yaml; the layout (positions of every box and line) is
hand-placed in this file, so moving things means moving coordinates.
Line width encodes link speed (SPEED_W).
"""
import base64
import html
import pathlib
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent
INV = yaml.safe_load((ROOT / "inventory.yaml").read_text())
ICONS = ROOT / "icons"
OUT = ROOT / "out"

UNREDACTED = "--unredacted" in sys.argv
RED = INV["redact"]
DOMAIN = INV["meta"]["domain"]
SHOWN_DOMAIN = DOMAIN if (UNREDACTED or not RED["domain"]) else RED["domain_placeholder"]
# the WAN address is real and public; keep it out of the default render too
PUBLIC_IP = INV["bgw"].get("wan_ip") or ""
PUBLIC_SHOWN = PUBLIC_IP if UNREDACTED else "public IPv4 · /23"

W = 2400

# ---------------------------------------------------------------- palette
BG = "#0b0f15"
GRID = "#151c26"
PANEL = "#111821"
PANEL2 = "#161f2b"
CHIP = "#19222e"
BORDER = "#253042"
TEXT = "#e6edf3"
MUTED = "#8d9aab"
FAINT = "#5d6a7c"
TRUNK = "#d5dde6"
TRUNK_BORDER = "#3a475a"
LINK = "#79c0ff"
REDDIT = "#ff5722"
DISK = "#1d2734"
DISK_EDGE = "#5a6b82"
PROTO = {"TCP": "#79c0ff", "UDP": "#39c5cf"}
SPEED_W = {"10G": 9.5, "2.5G": 3.8, "1G": 2.4, "100M": 1.4}
VLAN = {v["key"]: v for v in INV["vlans"]}
C = {k: v["color"] for k, v in VLAN.items()}
SANS = "Fira Sans"
MONO = "Fira Code"


def sub(s):
    """Fill {domain} placeholders and apply redaction."""
    s = str(s).replace("{domain}", SHOWN_DOMAIN)
    if not UNREDACTED and RED["domain"]:
        s = s.replace(DOMAIN, SHOWN_DOMAIN)
    if PUBLIC_IP and not UNREDACTED:
        s = s.replace(PUBLIC_IP, PUBLIC_SHOWN)
    return s


def esc(s):
    return html.escape(sub(s), quote=True)


def tw(s, size, mono=False):
    """Rough text width for layout decisions."""
    return len(sub(s)) * size * (0.6 if mono else 0.53)


def _font_file(pattern):
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None


PIL_OK = False
try:
    from PIL import ImageFont
    _FONTS = {
        700: _font_file("Fira Sans:bold"),
        600: _font_file("Fira Sans:semibold"),
        500: _font_file("Fira Sans:medium"),
        400: _font_file("Fira Sans:book"),
    }
    if not all(_FONTS.values()):
        raise RuntimeError("Fira Sans not found")
    PIL_OK = True
    _FCACHE = {}

    def measure(s, size, weight=700):
        weight = min(_FONTS, key=lambda w: abs(w - weight))
        key = (weight, size)
        if key not in _FCACHE:
            _FCACHE[key] = ImageFont.truetype(_FONTS[weight], size=size * 8)
        return _FCACHE[key].getlength(s) / 8
except Exception:
    def measure(s, size, weight=700):
        return sum(0.68 if c.isupper() else 0.58 if c.isdigit() else 0.5 for c in s) * size


def fqdn(h):
    return f"{h}.{SHOWN_DOMAIN}"


def fit(s, size, weight, width, floor=9.5):
    """Largest size ≤ size at which `s` fits `width`."""
    if measure(s, size, weight) <= width:
        return size
    return max(floor, round(size * width / measure(s, size, weight), 2))


class SVG:
    def __init__(self):
        self.p = []
        self._icon_cache = {}
        self.max_y = 0

    def add(self, s):
        self.p.append(s)

    def grow(self, y):
        if y > self.max_y:
            self.max_y = y

    def rect(self, x, y, w, h, rx=10, fill=PANEL, stroke=BORDER, sw=1.2, op=1, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.grow(y + h)
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}" opacity="{op}"{d}/>')

    def text(self, x, y, s, size=14, fill=TEXT, weight=400, anchor="start", mono=False, ls=0, op=1):
        fam = MONO if mono else SANS
        lsa = f' letter-spacing="{ls}"' if ls else ""
        try:
            self.grow(y + float(size) * 0.4)
        except (TypeError, ValueError):
            self.grow(y + 6)
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{fam}" font-size="{size}" fill="{fill}" '
                 f'font-weight="{weight}" text-anchor="{anchor}" opacity="{op}"{lsa}>{esc(s)}</text>')

    def icon(self, name, x, y, size):
        if name not in self._icon_cache:
            f = ICONS / f"{name}.svg"
            if not f.exists():
                raise SystemExit(f"missing icon '{name}' – run: python3 fetch_icons.py")
            self._icon_cache[name] = base64.b64encode(f.read_bytes()).decode()
        self.grow(y + size)
        # size is always numeric here
        self.add(f'<image x="{x:.1f}" y="{y:.1f}" width="{size}" height="{size}" '
                 f'href="data:image/svg+xml;base64,{self._icon_cache[name]}"/>')

    def line(self, pts, color, sw=3, dash=None, r=10, op=1, cap="round"):
        self.grow(max(p[1] for p in pts) + sw)
        self.add(f'<path d="{rounded(pts, r)}" fill="none" stroke="{color}" stroke-width="{sw}" '
                 f'stroke-linecap="{cap}" stroke-linejoin="round" opacity="{op}"'
                 + (f' stroke-dasharray="{dash}"' if dash else "") + "/>")

    def arrow(self, pts, color=MUTED, sw=1.8, dash=None, r=8):
        self.line(pts, color, sw, dash=dash, r=r)
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
        dx, dy = x1 - x0, y1 - y0
        ln = max(abs(dx), abs(dy)) or 1
        ux, uy = dx / ln, dy / ln
        a, b = 8, 4.5
        p1 = (x1 - ux * a - uy * b, y1 - uy * a + ux * b)
        p2 = (x1 - ux * a + uy * b, y1 - uy * a - ux * b)
        self.add(f'<path d="M{x1},{y1} L{p1[0]:.1f},{p1[1]:.1f} L{p2[0]:.1f},{p2[1]:.1f} Z" fill="{color}"/>')

    def pill(self, x, y, s, color, size=12, fill=None, mono=False, anchor="start", h=None, pad=8,
             tcolor=None, weight=600):
        w = tw(s, size, mono) + pad * 2
        h = h or size + 10
        if anchor == "middle":
            x -= w / 2
        elif anchor == "end":
            x -= w
        self.rect(x, y, w, h, rx=h / 2, fill=fill or color + "22", stroke=color + "88", sw=1)
        self.text(x + w / 2, y + h / 2 + size * 0.36, s, size, tcolor or color, weight, "middle", mono)
        return w

    def label(self, x, y, s, color=MUTED, size=12, anchor="middle", mono=False, bg=BG):
        w = tw(s, size, mono) + 12
        bx = x - w / 2 if anchor == "middle" else (x if anchor == "start" else x - w)
        self.rect(bx, y - size - 2, w, size + 9, rx=5, fill=bg, stroke=bg, sw=0)
        self.text(bx + w / 2, y + 1, s, size, color, 500, "middle", mono)

    def render(self):
        """Wrap the drawn body; the canvas grows to the lowest element, so nothing clips."""
        height = int(self.max_y + 36)
        head = [
            '<defs><pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse">'
            f'<circle cx="1.5" cy="1.5" r="1.3" fill="{GRID}"/></pattern></defs>',
            f'<rect x="0" y="0" width="{W}" height="{height}" rx="0" fill="{BG}" '
            f'stroke="{BG}" stroke-width="0"/>',
            f'<rect x="0" y="0" width="{W}" height="{height}" rx="0" fill="url(#dots)" '
            'stroke="none" stroke-width="0"/>',
        ]
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
                f'viewBox="0 0 {W} {height}">' + "".join(head) + "".join(self.p) + "</svg>")


def rounded(pts, r):
    if len(pts) == 2:
        return f"M{pts[0][0]},{pts[0][1]} L{pts[1][0]},{pts[1][1]}"
    d = f"M{pts[0][0]},{pts[0][1]}"
    for i in range(1, len(pts) - 1):
        (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
        l1 = max(abs(x1 - x0), abs(y1 - y0))
        l2 = max(abs(x2 - x1), abs(y2 - y1))
        rr = min(r, l1 / 2, l2 / 2)
        ax = x1 - (x1 - x0) / l1 * rr if l1 else x1
        ay = y1 - (y1 - y0) / l1 * rr if l1 else y1
        bx = x1 + (x2 - x1) / l2 * rr if l2 else x1
        by = y1 + (y2 - y1) / l2 * rr if l2 else y1
        d += f" L{ax:.1f},{ay:.1f} Q{x1},{y1} {bx:.1f},{by:.1f}"
    d += f" L{pts[-1][0]},{pts[-1][1]}"
    return d


S = SVG()


# ---------------------------------------------------------------- shared pieces
def hostname(g):
    if g.get("host"):
        return fqdn(g["host"]), LINK
    if g.get("internal"):
        return f"{g['internal']}.internal", None
    return None, None


def addr(x, y, ip, g, color, size=12):
    S.text(x, y, ip, size, color, 500, mono=True)
    name, ncol = hostname(g)
    if name:
        cw_ = size * 0.6
        dx = x + len(ip) * cw_ + cw_ * 0.6
        S.text(dx, y, "·", size, MUTED, 400, mono=True)
        S.text(dx + cw_ * 1.6, y, name, size, ncol or color, 400, mono=True, op=1 if ncol else 0.85)


HWC = "#c08a5c"


def hw_bar(x, y, h):
    S.add(f'<rect x="{x+1}" y="{y+12}" width="4" height="{h-24}" rx="2" fill="{HWC}"/>')


TAB = 34


def tab_width(g):
    return 16 + measure(g["name"], 20, 700) + 7 + measure("·", 20, 700) + 7 + measure(g["type"], 14, 600) + 18


def folder(x, y, w, h, tab_w, fill, stroke, sw):
    t = y - TAB
    r, rt, sl = 12, 9, 16
    d = (f"M{x},{y+h-r} L{x},{t+rt} Q{x},{t} {x+rt},{t} L{x+tab_w-sl:.1f},{t} "
         f"C{x+tab_w-sl/3:.1f},{t} {x+tab_w-sl/3:.1f},{y} {x+tab_w+sl/2:.1f},{y} "
         f"L{x+w-r},{y} Q{x+w},{y} {x+w},{y+r} L{x+w},{y+h-r} Q{x+w},{y+h} {x+w-r},{y+h} "
         f"L{x+r},{y+h} Q{x},{y+h} {x},{y+h-r} Z")
    S.add(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')


def device_card(x, y, w, h, icons, g, color, fill=PANEL, stroke=None, sw=1.6):
    folder(x, y, w, h, tab_width(g), fill, stroke or color + "aa", sw)
    S.add(f'<text x="{x+16}" y="{y-10}" font-family="{SANS}" fill="{TEXT}">'
          f'<tspan font-size="20" font-weight="700">{esc(g["name"])}</tspan>'
          f'<tspan dx="7" font-size="20" font-weight="700" fill-opacity="0.6">·</tspan>'
          f'<tspan dx="7" font-size="14" font-weight="600">{esc(g["type"])}</tspan></text>')
    ix = x + 14
    for ic in icons:
        S.icon(ic, ix, y + 15, 54)
        ix += 58
    tx_ = ix + 8
    avail = x + w - 14 - tx_
    dy = 0 if g.get("os") else 8
    S.text(tx_, y + 28 + dy, g.get("model") or "custom build",
           fit(g.get("model") or "custom build", 14, 500, avail),
           TEXT if g.get("model") else MUTED, 500)
    addr(tx_, y + 48 + dy, g["ip"], g, color, fit(g["ip"] + " " + (hostname(g)[0] or ""), 12, 500, avail))
    if g.get("os"):
        S.text(tx_, y + 66, g["os"], fit(g["os"], 12, 400, avail), MUTED, 400)
    if g.get("note"):
        S.text(tx_, y + 84, g["note"], fit(g["note"], 12, 400, avail), FAINT, 400)


def jack(x, y, w, h, fill, stroke, sfp=False):
    S.rect(x, y, w, h, rx=5, fill=fill, stroke=stroke, sw=1.4)
    if sfp:
        S.rect(x + 8, y + 9, w - 16, h - 18, rx=2, fill="#0b0f15", stroke="none", sw=0)
    else:
        S.add(f'<path d="M{x+10},{y+h-8} v-14 h6 v-5 h{w-32} v5 h6 v14 z" fill="#0b0f15"/>')


def ticks(cx, y, untagged=None, tagged=(), up=False):
    vk = ([untagged] if untagged else []) + list(tagged)
    x0 = cx - (len(vk) * 7) / 2
    for j, k in enumerate(vk):
        hh = 8 if k == untagged else 5
        yy = y - hh if up else y
        S.add(f'<rect x="{x0 + j*7:.1f}" y="{yy}" width="5" height="{hh}" rx="1" fill="{C[k]}"/>')


def vlan_tag(vkey):
    v = VLAN[vkey]
    return f"{v['tag']} · {v['name']}" if v["tag"].startswith("VLAN") else v["name"]


# ---------------------------------------------------------------- layout constants
LAN = C["lan"]
WANN = C["wan"]
CX = 1200
CY0 = 166
FY, FH = 316, 104                       # AT&T gateway body
OX, OY, OW, OH = 700, 476, 800, 348     # UX Max
BX, BY, BW, BH = 560, 985, 1160, 204    # TP-Link switching
PX0, PITCH = BX + 150, 116              # switch port centres
DY = 1345                               # cluster card body top
GY = 74                                 # cluster header band
ROW_HEAD = 84
CHIP_H, CHIP_G = 44, 4
BLOCK_GAP = 16
SUB_GAP = 8
TXX, TWW = 40, W - 80

nodes = INV["cluster"]["nodes"]
ROWS = 8                                     # target guest rows per node
SUBS = [min(3, max(1, -(-len(n["guests"]) // ROWS))) for n in nodes]
ROWS = max(-(-len(n["guests"]) // k) for n, k in zip(nodes, SUBS))
SUB_W = (TWW - 40 - BLOCK_GAP * 3 - SUB_GAP * (sum(SUBS) - len(SUBS))) / sum(SUBS)
BLOCK_W = [k * SUB_W + (k - 1) * SUB_GAP for k in SUBS]
ZH = ROW_HEAD + ROWS * (CHIP_H + CHIP_G) + 18
TH0 = GY + ZH + 22
H = DY + TH0 + 420

# ---------------------------------------------------------------- background + header
meta = INV["meta"]
title = meta["title"] if (UNREDACTED or not RED["domain"]) else meta["title_redacted"]
S.text(40, 86, title, 46, TEXT, 700, ls=-0.5)
S.text(W - 40, 74, meta["watermark"], 21, REDDIT, 700, "end")
S.text(W - 40, 100, meta["date"], 16, MUTED, 400, "end")
S.text(40, 112, f'{INV["internet"]["isp"]} · {INV["cluster"]["os"]} · '
                f'{sum(len(n["guests"]) for n in nodes)} guests on {len(nodes)} nodes', 15, MUTED, 400)

# ================================================================ TOP: internet
ISP = INV["internet"]["speed"]
blobs = [(-95, 18, 42), (-45, -8, 56), (25, -18, 62), (90, 6, 48), (130, 26, 30), (-130, 30, 28)]
for dx, dy, r in blobs:
    S.add(f'<circle cx="{CX+dx}" cy="{CY0+dy}" r="{r+2.5}" fill="#3a4a60"/>')
S.add(f'<rect x="{CX-150}" y="{CY0+12}" width="300" height="46" rx="23" fill="#3a4a60"/>')
for dx, dy, r in blobs:
    S.add(f'<circle cx="{CX+dx}" cy="{CY0+dy}" r="{r}" fill="#1a2433"/>')
S.add(f'<rect x="{CX-147.5}" y="{CY0+14.5}" width="295" height="41" rx="20.5" fill="#1a2433"/>')
S.text(CX, CY0 + 12, "Internet", 26, TEXT, 600, "middle")
S.text(CX, CY0 + 38, INV["internet"]["isp"], 13, MUTED, 400, "middle")

# remote access (left of the cloud)
rw = INV["remote"]
RX_, RY_ = 640, 152
S.rect(RX_, RY_, 330, 84, rx=12, fill=PANEL, stroke=C["ts"] + "aa", sw=1.6)
S.icon("tailscale", RX_ + 16, RY_ + 22, 38)
S.text(RX_ + 66, RY_ + 38, rw["name"], 18, TEXT, 600)
S.text(RX_ + 66, RY_ + 60, rw["note"], fit(rw["note"], 13, 400, 248), MUTED, 400)
S.line([(RX_ + 334, RY_ + 42), (CX - 130, RY_ + 42)], C["ts"], 1.8, dash="2 5", r=0)

# cloud services (right)
CSX, CSY = 1760, 150
for i, cs in enumerate(INV["internet"]["cloud_services"]):
    y = CSY + i * 54
    S.rect(CSX, y, 600, 44, rx=10, fill=PANEL2, stroke=BORDER)
    S.icon(cs["icon"], CSX + 10, y + 9, 26)
    S.text(CSX + 46, y + 20, cs["name"], 14, TEXT, 600)
    S.text(CSX + 46, y + 36, cs["note"], fit(cs["note"], 12, 400, 540), MUTED, 400)
S.line([(CX + 140, 168), (CSX, 168)], FAINT, 1.6, dash="2 5", r=0)
S.line([(CX + 160, 212), (CSX, 212)], FAINT, 1.6, dash="2 5", r=0)

# ---- AT&T gateway
bg = INV["bgw"]
S.label(CX - 10, (CY0 + 58 + FY - TAB) / 2 + 5, "↓ " + ISP["down"], "#c3cdd9", 12, anchor="end", mono=True)
S.label(CX + 10, (CY0 + 58 + FY - TAB) / 2 + 5, "↑ " + ISP["up"], "#c3cdd9", 12, anchor="start", mono=True)
GWX, GWW = CX - 310, 620
device_card(GWX, FY, GWW, FH, ["router"], bg, WANN)
FIBX = GWX + 300
S.line([(CX, CY0 + 58), (CX, FY + 26)], "#6b7a90", 3)
S.rect(FIBX - 22, FY + 26, 44, 36, rx=5, fill="#2a3443", stroke=TRUNK, sw=1.4)
S.add(f'<circle cx="{FIBX}" cy="{FY+44}" r="11" fill="#0b0f15" stroke="#5a6b82" stroke-width="2"/>'
      f'<circle cx="{FIBX}" cy="{FY+44}" r="2.5" fill="{TRUNK}"/>')
S.label(FIBX, FY + 18, "Fiber", MUTED, 11, mono=True, bg=PANEL)
S.text(FIBX, FY + FH - 9, "ONT", 10.5, MUTED, 500, "middle")

WANX = None
for i, lbl in enumerate(bg["ports"][1:], start=1):
    cx_ = GWX + 366 + (i - 1) * 54
    used = i == 1
    jack(cx_ - 22, FY + 28, 44, 36, (WANN + "55") if used else "#1b222c", WANN if used else "#3a475a")
    S.text(cx_, FY + 21, lbl, 11, MUTED, 500, "middle", mono=True)
    if used:
        WANX = cx_
        S.text(cx_, FY + FH - 9, "ip passthrough", 10.5, WANN, 600, "middle")

# ---- UX Max
ux = INV["uxmax"]
device_card(OX, OY, OW, OH, ["unifi"], ux, LAN, stroke=TRUNK_BORDER)
S.text(OX + 20, OY + 92, "HARDWARE", 11.5, HWC, 700, ls=1.4)
S.text(OX + 420, OY + 92, "SERVICES", 11.5, HWC, 700, ls=1.4)

for i, hwi in enumerate(ux["hw"]):
    x, y = OX + 16, OY + 102 + i * 62
    w_, h_ = 250, 56
    S.rect(x, y, w_, h_, rx=11, fill="#151d29", stroke="#2e3a4c", sw=1.2)
    hw_bar(x, y, h_)
    S.icon(hwi["icon"], x + 12, y + 14, 28)
    S.text(x + 50, y + 17, hwi["label"], 10, HWC, 700, ls=1.3)
    S.text(x + 50, y + 35, hwi["value"], 15.5, TEXT, 700)
    S.text(x + 50, y + 50, hwi["sub"], fit(hwi["sub"], 10.5, 400, 188), MUTED, 400)

svx = OX + 420
svc = [
    ("unifi", "UniFi Network", "gateway + 4 mesh APs"),
    ("cloudflare", "cloudflared", "3 tunnel connectors"),
    ("adguard", "AdGuard DNS", "on the RPi4 pair"),
    ("glyph-dhcp", "DHCP", "reservations .2–.250"),
    ("wireguard", "WireGuard", "udp/51820 → dns1"),
    ("tailscale", "Tailscale", "mesh · 14 peers"),
]
sw_, sh_ = 175, 50
for i, (ic, nm, nt) in enumerate(svc):
    col, row = i % 2, i // 2
    x = svx + col * (sw_ + 10)
    y = OY + 102 + row * (sh_ + 8)
    S.rect(x, y, sw_, sh_, rx=9, fill=CHIP, stroke=BORDER, sw=1)
    S.icon(ic, x + 9, y + 12, 26)
    S.text(x + 40, y + 22, nm, fit(nm, 13, 600, sw_ - 48), TEXT, 600)
    S.text(x + 40, y + 39, nt, fit(nt, 10.5, 400, sw_ - 48), MUTED, 400)

# WAN cable + LAN cable
S.line([(WANX, FY + FH), (WANX, OY + 14)], WANN, SPEED_W["1G"])
jack(WANX - 22, OY + 14, 44, 36, WANN + "55", WANN)
S.label(WANX + 10, (FY + FH + OY + 14) / 2 + 4, "1G", WANN, 11, anchor="start", mono=True)
SWX = OX + OW / 2
jack(SWX - 22, OY + OH - 44, 44, 36, LAN + "55", LAN)
S.line([(SWX, OY + OH), (SWX, BY)], LAN, SPEED_W["1G"])
S.label(SWX + 12, (OY + OH + BY) / 2 + 4, "1G · LAN", LAN, 11, anchor="start", mono=True)

# ================================================================ switch
swc = INV["switch"]
device_card(BX, BY, BW, BH, ["tp-link"], swc, LAN, fill="#141b25", stroke=TRUNK_BORDER)
PORTS = {}
for i, p in enumerate(swc["ports"]):
    cx_ = PX0 + i * PITCH
    PORTS[p["name"]] = cx_
    unt, tagged = p.get("untagged"), p.get("tagged", [])
    fill, stroke = (C[unt] + "55", C[unt]) if unt and not tagged else ("#2a3443", TRUNK)
    jack(cx_ - 22, BY + 120, 44, 34, fill, stroke)
    S.text(cx_, BY + 112, p["name"], 11, MUTED, 500, "middle", mono=True)
    ticks(cx_, BY + 158, unt, tagged)
    S.text(cx_, BY + 190, p["to"], fit(p["to"], 10.5, 500, PITCH - 16), MUTED, 500, "middle")

SB = BY + BH

# ---- four node cables merge into one trunk
BUSY = SB + 24
MERGE = BX + 30
for port in ("p1", "p2", "p3", "p4"):
    S.line([(PORTS[port], SB), (PORTS[port], BUSY), (MERGE, BUSY)], LAN, SPEED_W["1G"])
S.line([(MERGE, BUSY), (MERGE, DY)], LAN, SPEED_W["1G"])
S.label(MERGE + 12, (BUSY + DY) / 2 + 4, "4× 1G", LAN, 11, anchor="start", mono=True)

# ================================================================ right column: exposure + monitoring + APs
IX_, IY_, IW_ = 1760, 262, 600
pf = INV["port_forwards"]
ih_ = 84 + len(pf) * 44
S.rect(IX_, IY_, IW_, ih_, rx=14, fill=PANEL, stroke=BORDER, sw=1.4)
S.text(IX_ + 20, IY_ + 32, "Open to the internet", 18, TEXT, 600)
S.text(IX_ + 20, IY_ + 52, "two forwards · NAT-PMP off · the rest is Cloudflare Tunnel", 12, MUTED, 400)
for i, r in enumerate(pf):
    y = IY_ + 66 + i * 44
    S.rect(IX_ + 14, y, IW_ - 28, 38, rx=8, fill=CHIP, stroke=BORDER, sw=1)
    S.text(IX_ + 26, y + 24, r["port"], 13, TEXT, 600, mono=True)
    S.text(IX_ + 140, y + 17, r["to"], 13.5, TEXT, 600)
    S.text(IX_ + 140, y + 32, r["what"], fit(r["what"], 11.5, 400, 340), MUTED, 400)
    px = IX_ + IW_ - 24
    for pr in reversed(r["proto"].split("/")):
        px -= S.pill(px, y + 9, pr, PROTO[pr], 11, mono=True, anchor="end", pad=7, h=20) + 6

mon = INV["monitoring"]
MY_ = IY_ + ih_ + 16
MH_ = 46 + ((len(mon) + 1) // 2) * 30
S.rect(IX_, MY_, IW_, MH_, rx=14, fill=PANEL, stroke=BORDER, sw=1.4)
S.text(IX_ + 20, MY_ + 28, "Monitoring", 18, TEXT, 600)
S.text(IX_ + 20, MY_ + 45, "every VM runs telegraf + watchtower + diun + beszel-agent", 11, MUTED, 400)
half = (len(mon) + 1) // 2
colw = (IW_ - 40) / 2
for i, m in enumerate(mon):
    col, row = i // half, i % half
    x = IX_ + 20 + col * colw
    y = MY_ + 54 + row * 30
    S.icon(m["icon"], x, y, 20)
    S.text(x + 26, y + 11, m["name"], 12.5, TEXT, 600)
    S.text(x + 26, y + 24, m["note"], fit(m["note"], 10.5, 400, colw - 34), MUTED, 400)

# ---- AP mesh card (wireless uplink from the gateway)
apy = MY_ + MH_ + 16
APX, APW, APH = IX_, IW_, 186
apd = INV["devices"]["aps"]
S.rect(APX, apy, APW, APH, rx=14, fill=PANEL, stroke=TRUNK_BORDER, sw=1.6)
S.icon("unifi", APX + 16, apy + 14, 34)
S.text(APX + 60, apy + 32, apd["name"], 17, TEXT, 600)
S.text(APX + APW - 14, apy + 32, "wireless · 6 GHz", 11, TRUNK, 500, "end", mono=True)
S.text(APX + 60, apy + 50, apd["model"], 12, MUTED, 400)
S.text(APX + 16, apy + 76, "SSIDs", 11, FAINT, 600, ls=1.2)
for i, s in enumerate(INV["ssids"]):
    name = s["redacted"] if (RED["ssid_names"] and not UNREDACTED) else s["name"]
    col = C[s["vlan"]]
    sy = apy + 90 + i * 22
    S.add(f'<circle cx="{APX+24}" cy="{sy+5}" r="4" fill="{col}"/>')
    S.text(APX + 38, sy + 9, name, 13, TEXT, 500)
    S.text(APX + 122, sy + 9, vlan_tag(s["vlan"]), 11.5, col, 500, mono=True)
    S.text(APX + 300, sy + 9, s["bands"], 11, MUTED, 400)
S.text(APX + 16, apy + APH - 14, apd["ip"], 10.5, MUTED, 400, mono=True)
S.text(APX + APW - 14, apy + APH - 14, "125 clients total", 10.5, MUTED, 400, "end")
S.line([(OX + OW, apy + 60), (APX, apy + 60)], TRUNK, 2, dash="2 5", r=0)
S.label((OX + OW + APX) / 2, apy + 52, "Wi-Fi mesh", TRUNK, 10.5, bg=BG)

# ---- networks table
vx, vy, vw = 40, 150, 500
vh = 62 + len(INV["vlans"]) * 56
S.rect(vx, vy, vw, vh, rx=14, fill=PANEL, stroke=BORDER, sw=1.4)
S.text(vx + 20, vy + 34, "Networks", 19, TEXT, 600)
for i, v in enumerate(INV["vlans"]):
    y = vy + 50 + i * 56
    S.rect(vx + 14, y, vw - 28, 48, rx=9, fill=CHIP, stroke=v["color"] + "55", sw=1)
    S.add(f'<rect x="{vx+14}" y="{y}" width="6" height="48" rx="3" fill="{v["color"]}"/>')
    S.text(vx + 30, y + 20, v["tag"], 12.5, v["color"], 600, mono=True)
    S.text(vx + 118, y + 20, v["name"], 15, TEXT, 600)
    S.text(vx + vw - 24, y + 20, v["subnet"], fit(v["subnet"], 12, 500, 210), TEXT, 500, "end", mono=True)
    S.text(vx + 30, y + 38, v["note"], fit(v["note"], 11.5, 400, vw - 60), MUTED, 400)

# ---- fleet facts (fills the gap under the networks table)
FL = INV["fleet"]
fy0 = vy + vh + 16
fw0 = vw
fh0 = 56 + len(FL["facts"]) * 34
S.rect(vx, fy0, fw0, fh0, rx=14, fill=PANEL, stroke=BORDER, sw=1.4)
S.text(vx + 20, fy0 + 32, FL["title"], 18, TEXT, 600)
S.text(vx + 20, fy0 + 50, FL["note"], fit(FL["note"], 11.5, 400, fw0 - 40), MUTED, 400)
for i, fp in enumerate(FL["facts"]):
    y = fy0 + 62 + i * 34
    S.icon(fp["icon"], vx + 20, y, 22)
    S.text(vx + 50, y + 12, fp["name"], 13, TEXT, 600)
    S.text(vx + 186, y + 12, fp["note"], fit(fp["note"], 11.5, 400, fw0 - 210), MUTED, 400)


LEG_Y = vy + vh + 16 + 56 + len(INV["fleet"]["facts"]) * 34 + 16

# ---- legend
LG_ROWS = ["access", "wan", "wireless", "net", "speed", "public", "internal", "ticks"]
lgx, lgy, lgw = 40, LEG_Y, 500
LR = 27
lgh = 52 + len(LG_ROWS) * LR + 8
S.rect(lgx, lgy, lgw, lgh, rx=14, fill=PANEL, stroke=BORDER, sw=1.4)
S.text(lgx + 20, lgy + 36, "Legend", 19, TEXT, 600)
SX, TX = lgx + 22, lgx + 176
for i, k in enumerate(LG_ROWS):
    y = lgy + 66 + i * LR
    t = None
    if k == "access":
        for jj, c in enumerate(["lan", "20", "30"]):
            S.line([(SX + jj * 14, y), (SX + jj * 14 + 10, y)], C[c], 3.6, r=0, cap="butt")
        t = "physical cable, colored by network"
    elif k == "wan":
        S.line([(SX, y), (SX + 50, y)], WANN, 3, r=0)
        t = "WAN (AT&T gateway)"
    elif k == "wireless":
        S.line([(SX, y), (SX + 50, y)], TRUNK, 2, dash="2 5", r=0)
        t = "Wi-Fi mesh uplink"
    elif k == "net":
        S.line([(SX, y), (SX + 50, y)], MUTED, 1.8, dash="2 5", r=0)
        t = "over the internet"
    elif k == "speed":
        S.text(SX, y + 4.5, "1G", 12.5, C["lan"], 600, mono=True)
        t = "line width = speed · all links are 1G"
    elif k == "public":
        S.text(SX, y + 4.5, "app." + SHOWN_DOMAIN, 12, LINK, 500, mono=True)
        t = "public via Cloudflare Tunnel"
    elif k == "internal":
        S.text(SX, y + 4.5, "name.internal", 12, C["lan"], 400, mono=True, op=0.78)
        t = "internal DNS, LAN only"
    elif k == "ticks":
        for jj, c in enumerate(["lan", "20", "30"]):
            S.add(f'<rect x="{SX + jj*7}" y="{y-5 if jj == 0 else y-2}" width="5" '
                  f'height="{8 if jj == 0 else 5}" rx="1" fill="{C[c]}"/>')
        t = "port networks (tall = untagged)"
    if t:
        S.text(TX, y + 4.5, t, 13, MUTED, 400)

# ---- public hostnames (right column, under the AP card)
PH_ = INV["fleet"]
hosts = PH_["public_hosts"]
cols = 3
cell_w = (IW_ - 36) / cols
cell_h = 23
rows_ = -(-len(hosts) // cols)
ph_y = apy + APH + 16
ph_h = 58 + rows_ * cell_h
S.rect(IX_, ph_y, IW_, ph_h, rx=14, fill=PANEL, stroke=BORDER, sw=1.4)
S.text(IX_ + 20, ph_y + 30, PH_["hosts_title"], 18, TEXT, 600)
S.text(IX_ + 20, ph_y + 48, PH_["hosts_note"], fit(PH_["hosts_note"], 11, 400, IW_ - 40), MUTED, 400)
for i, h in enumerate(hosts):
    cx_ = IX_ + 18 + (i % cols) * cell_w
    cy_ = ph_y + 58 + (i // cols) * cell_h
    S.text(cx_, cy_ + 12, "·", 10, FAINT, 600)
    S.text(cx_ + 8, cy_ + 12, fqdn(h), fit(fqdn(h), 10.5, 500, cell_w - 14), LINK, 500, mono=True)

# ================================================================ Proxmox cluster
CL = INV["cluster"]
device_card(TXX, DY, TWW, TH0, ["proxmox"], {
    "name": CL["name"], "type": "Proxmox cluster", "model": CL["os"],
    "ip": "192.168.7.188 · .182 · .131 · .187", "os": "",
    "note": "no shared storage · ZFS on every node · every guest rebuilt from git",
}, LAN, fill="#0f151e", stroke=TRUNK_BORDER, sw=2)


BLOCK_X = []
_x = TXX + 20
for _w in BLOCK_W:
    BLOCK_X.append(_x)
    _x += _w + BLOCK_GAP


def nx(i):
    return BLOCK_X[i]


hy = DY + GY
for i, n in enumerate(nodes):
    x, bw = nx(i), BLOCK_W[i]
    S.rect(x, hy, bw, ROW_HEAD - 10, rx=11, fill="#151d29", stroke="#2e3a4c", sw=1.2)
    hw_bar(x, hy, ROW_HEAD - 10)
    S.text(x + 14, hy + 24, n["name"], 17, TEXT, 700)
    S.text(x + bw - 14, hy + 24, n["ip"], 11, LAN, 500, "end", mono=True)
    for k, hwi in enumerate(n["hw"]):
        S.text(x + 14, hy + 44 + k * 15, f'{hwi["label"]}  {hwi["value"]}', 10.5, MUTED, 400)
        S.text(x + 116, hy + 44 + k * 15, hwi["sub"], 10, FAINT, 400)


def guest_chip(g, x, y, w):
    """One guest: icon, name, VM/CT id, IP + hostname."""
    S.rect(x, y, w, CHIP_H, rx=8, fill=CHIP, stroke=BORDER, sw=1)
    S.icon(g.get("icons", ["flatcar"])[0], x + 7, y + 12, 18)
    tag = f'{g["kind"]} {g["id"]}'
    tag_w = tw(tag, 9.5, True)
    name_w = w - 38 - tag_w - 8
    S.text(x + 30, y + 17, g["name"], fit(g["name"], 12, 600, name_w), TEXT, 600)
    S.text(x + w - 8, y + 17, tag, 9.5, FAINT, 500, "end", mono=True)
    nm, ncol_ = hostname(g)
    S.text(x + 30, y + 33, g["ip"], 10.5, MUTED, 500, mono=True)
    if nm:
        ipw = tw(g["ip"], 10.5, True)          # drawn in Fira Code, so use the mono factor
        room = w - 38 - ipw - 7
        # only print the hostname when it stays readable; the full list is in the
        # "Public services" card on the right, so nothing is lost by omitting it here
        need = tw(nm, 9.5, True)
        if room >= need:
            S.text(x + 30 + ipw + 7, y + 33, nm, 9.5, ncol_ or MUTED, 500, mono=True)


for i, n in enumerate(nodes):
    half = -(-len(n["guests"]) // SUBS[i])
    for j, g in enumerate(n["guests"]):
        col, row = j // half, j % half
        x = nx(i) + col * (SUB_W + SUB_GAP)
        y = hy + ROW_HEAD + 6 + row * (CHIP_H + CHIP_G)
        guest_chip(g, x, y, SUB_W)

# ================================================================ storage
ST = INV["storage"]
SY0 = DY + TH0 + 30
STW, SH0 = 700, 300
S.rect(TXX, SY0, STW, SH0, rx=14, fill=PANEL, stroke=C["lan"] + "99", sw=1.5)
S.icon("synology", TXX + 18, SY0 + 16, 40)
S.text(TXX + 70, SY0 + 36, ST["name"], 19, TEXT, 600)
S.text(TXX + 70, SY0 + 56, "192.168.7.167 · DSM 7 · Celeron J4125 · 12 GB", 11, MUTED, 400)
S.text(TXX + 18, SY0 + SH0 - 16, ST["footer"], fit(ST["footer"], 10.5, 400, STW - 36), MUTED, 400)
S.pill(TXX + STW - 16, SY0 + 16, "LAN", LAN, 10.5, mono=True, h=19, pad=6, anchor="end")

pool = ST["pools"][0]
px_, py_, pw_, ph_ = TXX + 16, SY0 + 70, STW - 32, 118
S.rect(px_, py_, pw_, ph_, rx=10, fill=CHIP, stroke=BORDER, sw=1)
S.text(px_ + 14, py_ + 24, pool["name"], 15.5, TEXT, 700)
S.text(px_ + 14 + tw(pool["name"], 15.5) + 12, py_ + 24,
       fit(pool["layout"], 12, 400, pw_ - 40 - tw(pool["used"], 11) - tw(pool["name"], 15.5)), MUTED, 400)
S.text(px_ + pw_ - 14, py_ + 24, pool["used"], 11, MUTED, 400, "end")
bw_ = pw_ - 28
S.rect(px_ + 14, py_ + 32, bw_, 8, rx=4, fill="#253042", stroke="none", sw=0)
S.rect(px_ + 14, py_ + 32, max(bw_ * pool["pct"] / 100, 8), 8, rx=4, fill=C["lan"], stroke="none", sw=0)

dx = px_ + 14
for grp in pool["groups"]:
    if grp["kind"] == "hdd":
        for _ in range(grp["count"]):
            S.rect(dx, py_ + 52, 28, 38, rx=4, fill=DISK, stroke=DISK_EDGE, sw=1.2)
            S.add(f'<circle cx="{dx+14}" cy="{py_+67}" r="8.5" fill="none" stroke="{C["lan"]}" stroke-width="1.6"/>'
                  f'<circle cx="{dx+14}" cy="{py_+67}" r="2" fill="{C["lan"]}"/>')
            S.rect(dx + 7, py_ + 81, 14, 3, rx=1, fill=DISK_EDGE, stroke="none", sw=0)
            dx += 35
    else:
        S.rect(dx, py_ + 61, 92, 20, rx=2, fill=DISK, stroke=DISK_EDGE, sw=1.2)
        for k in range(3):
            S.rect(dx + 8 + k * 21, py_ + 65, 15, 12, rx=1, fill=C["lan"] + "55", stroke="none", sw=0)
        dx += 100
for k, grp in enumerate(pool["groups"]):
    S.text(px_ + 14, py_ + 108 + k * 15, grp["label"], 11.5, TEXT, 500)
    S.text(px_ + 150, py_ + 108 + k * 15, grp["sub"], 10.5, MUTED, 400)

SHARE_W = (STW - 36 - 3 * 8) / 4
shx = TXX + 18
for share in ST["shares"]:
    S.rect(shx, SY0 + SH0 - 78, SHARE_W, 30, rx=7, fill=C["lan"] + "16", stroke=C["lan"] + "cc", sw=1.2, dash="4 3")
    S.text(shx + 10, SY0 + SH0 - 58, share["name"], 11.5, TEXT, 600, mono=True)
    shx += SHARE_W + 8
S.text(TXX + 18, SY0 + SH0 - 16, "", 10, MUTED, 400)

# ================================================================ media pipeline
PL = INV["pipeline"]
MPX = TXX + STW + 20
MPW = W - 40 - MPX
MPY = SY0
NS = PL["nodes"]

G_ = 22
NW_ = (MPW - 36 - 3 * G_) / 4
NH_ = 78
r1 = MPY + 62
r2 = r1 + NH_ + 42
ax = [MPX + 18 + i * (NW_ + G_) for i in range(4)]
SHH = 52
MPH = (r2 + SHH + 20) - MPY

S.rect(MPX, MPY, MPW, MPH, rx=14, fill=PANEL, stroke=BORDER, sw=1.4)
S.text(MPX + 20, MPY + 30, "Media pipeline", 17, TEXT, 600)
S.text(MPX + 20, MPY + 48, "request → download → library → stream", 11.5, MUTED, 400)


def pnode(n, x, y, w=NW_):
    S.rect(x, y, w, NH_, rx=9, fill=CHIP, stroke=BORDER, sw=1)
    S.icon(n["icon"], x + 8, y + 8, 20)
    S.text(x + 34, y + 22, n["name"], fit(n["name"], 12.5, 600, w - 84), TEXT, 600)
    S.text(x + w - 10, y + 22, f'VM {n["vm"]}', 9.5, FAINT, 500, "end", mono=True)
    S.text(x + 34, y + 38, n["sub"], fit(n["sub"], 10.5, 400, w - 44), MUTED, 400)
    S.text(x + 10, y + 56, n["ip"], 10, FAINT, 500, mono=True)
    if n.get("host"):
        S.text(x + w - 10, y + 56, fqdn(n["host"]), fit(fqdn(n["host"]), 9.5, 500, 130), LINK, 500, "end", mono=True)


# row 1: the request path. row 2: indexers + Plex, with the two shares under them.
pnode(NS["request"], ax[0], r1)
pnode(NS["arrs"], ax[1], r1)
pnode(NS["sab"], ax[2], r1)
pnode(NS["plex"], ax[3], r1)
pnode(NS["prowlarr"], ax[0], r2)

S.arrow([(ax[0] + NW_ + 3, r1 + NH_ / 2), (ax[1] - 3, r1 + NH_ / 2)])
S.label(ax[0] + NW_ + G_ / 2, r1 + NH_ / 2 - 9, "request", MUTED, 10, bg=PANEL)
S.arrow([(ax[1] + NW_ + 3, r1 + NH_ / 2), (ax[2] - 3, r1 + NH_ / 2)])
S.label(ax[1] + NW_ + G_ / 2, r1 + NH_ / 2 - 9, "queue", MUTED, 10, bg=PANEL)
S.arrow([(ax[2] + NW_ + 3, r1 + NH_ / 2), (ax[3] - 3, r1 + NH_ / 2)])
S.label(ax[2] + NW_ + G_ / 2, r1 + NH_ / 2 - 9, "library", MUTED, 10, bg=PANEL)
S.arrow([(ax[0] + NW_ / 2 + 44, r2 - 3), (ax[0] + NW_ / 2 + 44, r1 + NH_ + 3)])
S.label(ax[0] + NW_ / 2 + 56, r1 + NH_ + 20, "indexers", MUTED, 10, bg=PANEL)

# shares: downloads under SABnzbd, media under Plex
shr_y = r2
for key, col in (("downloads", 2), ("media", 3)):
    sh = PL["shares"][key]
    sx = ax[col]
    S.rect(sx, shr_y, NW_, SHH, rx=8, fill=C["lan"] + "16", stroke=C["lan"] + "cc", sw=1.3, dash="5 4")
    S.icon("synology", sx + 9, shr_y + 15, 18)
    S.text(sx + 34, shr_y + 24, sh["name"], 11.5, TEXT, 600)
    S.text(sx + 34, shr_y + 40, sh["mounts"], 9.5, C["lan"], 500, mono=True)

S.arrow([(ax[2] + NW_ * 0.3, r1 + NH_ + 3), (ax[2] + NW_ * 0.3, shr_y - 3)])
S.label(ax[2] + NW_ * 0.3 + 12, r1 + NH_ + 20, "download", MUTED, 10, bg=PANEL)
S.arrow([(ax[1] + NW_ * 0.72, r1 + NH_ + 3), (ax[1] + NW_ * 0.72, shr_y - 34),
         (ax[3] + NW_ * 0.3, shr_y - 34), (ax[3] + NW_ * 0.3, shr_y - 3)])
S.label(ax[1] + NW_ * 0.72 + 76, shr_y - 41, "copy + rename", MUTED, 10, bg=PANEL)
S.arrow([(ax[3] + NW_ * 0.62, shr_y - 3), (ax[3] + NW_ * 0.62, r1 + NH_ + 3)])
S.label(ax[3] + NW_ * 0.62 + 12, r1 + NH_ + 20, "reads", MUTED, 10, bg=PANEL)

assert shr_y + SHH <= MPY + MPH - 8, "pipeline shares overflow the panel"

# ================================================================ assertions
assert OY + OH < BY, "UX Max overlaps the switch"
assert SB < DY - TAB, "switch overlaps the cluster card"
assert APX + APW <= W - 40, "AP card runs off the canvas"
assert ph_y + ph_h < DY - TAB, f"public-host card overlaps the cluster: {ph_y + ph_h}"
assert SY0 + SH0 <= H - 20, f"canvas too short: content ends at {SY0 + SH0}"
assert SY0 + MPH <= H - 20, f"canvas too short: pipeline ends at {SY0 + MPH}"

assert shr_y + 44 <= MPY + MPH - 10, "pipeline shares overflow the panel"
assert nx(3) + BLOCK_W[3] <= TXX + TWW - 18, "cluster columns overflow the card"
assert hy + ROW_HEAD + ROWS * (CHIP_H + CHIP_G) <= DY + TH0 - 10, "guest list overflows the cluster card"

OUT.mkdir(exist_ok=True)
name = "homelab-unredacted" if UNREDACTED else "homelab"
svg_path = OUT / f"{name}.svg"
svg_path.write_text(S.render())
png_path = OUT / f"{name}.png"
subprocess.run(["rsvg-convert", "-z", "1.6", "-o", str(png_path), str(svg_path)], check=True)
print(svg_path, png_path)
