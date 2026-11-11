#!/usr/bin/env python3
"""Download the third-party service icons into icons/.

They are not part of this repo (they belong to their projects). Source: the
homarr-labs/dashboard-icons collection via jsDelivr, raw GitHub as a fallback.

Usage: python3 fetch_icons.py
"""
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
ICONS = ROOT / "icons"
SOURCES = [
    "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/{}.svg",
    "https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/svg/{}.svg",
]

# local file name (as used in inventory.yaml / build.py) -> dashboard-icons name
ICON_MAP = {
    "adguard": "adguard-home",
    "alloy": "alloy",
    "audiobookshelf": "audiobookshelf",
    "authelia": "authelia",
    "bazarr": "bazarr",
    "beszel": "beszel",
    "caddy": "caddy",
    "changedetection": "changedetection",
    "cloudflare": "cloudflare",
    "coredns": "coredns",
    "crafty": "crafty-controller",
    "crowdsec": "crowdsec",
    "cyberchef": "cyberchef",
    "docker": "docker",
    "excalidraw": "excalidraw",
    "flatcar": "flatcar",
    "forgejo": "forgejo",
    "glance": "glance",
    "gotify": "gotify",
    "grafana": "grafana",
    "hoarder": "hoarder",
    "homarr": "homarr",
    "homebridge": "homebridge",
    "influxdb": "influxdb",
    "it-tools": "it-tools",
    "joplin": "joplin",
    "karakeep": "karakeep",
    "linkwarden": "linkding",
    "mealie": "mealie",
    "memos": "memos",
    "metube": "metube",
    "miniflux": "miniflux",
    "n8n": "n8n",
    "ollama-l": "ollama",
    "openwebui-l": "open-webui",
    "overseerr": "overseerr",
    "paperless": "paperless-ngx",
    "patchmon": "patchmon",
    "plex": "plex",
    "privatebin": "privatebin",
    "prometheus": "prometheus",
    "proxmox": "proxmox",
    "prowlarr": "prowlarr",
    "pulse": "pulse",
    "radarr": "radarr",
    "raspberry-pi": "raspberry-pi",
    "readarr": "readarr",
    "router": "router",
    "sabnzbd": "sabnzbd",
    "sonarr": "sonarr",
    "speedtest": "ookla-speedtest",
    "stash": "stash",
    "synology": "synology",
    "tailscale": "tailscale",
    "tautulli": "tautulli",
    "tp-link": "tp-link",
    "unifi": "unifi",
    "uptime-kuma": "uptime-kuma",

    "windows": "microsoft-windows",
    "wireguard": "wireguard",
}

# dark icons without a light variant: recolor them for the dark background
RECOLOR = {
    "ollama-l": ("ollama", 'fill="black"', 'fill="#e6edf3"'),
}


def download(name, tries=3):
    """Fetch one icon from the first source that delivers it."""
    last = None
    for url in SOURCES:
        req = urllib.request.Request(url.format(name), headers={"User-Agent": "homelab-diagram/1.0"})
        for _ in range(tries):
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return r.read().decode("utf-8")
            except Exception as e:                      # noqa: BLE001 - network flake or missing file
                last = e
                if getattr(e, "code", None) in (403, 404):
                    break
    raise last


def main():
    missing = []
    for local, remote in sorted(ICON_MAP.items()):
        dest = ICONS / f"{local}.svg"
        if dest.exists():
            continue
        try:
            svg = download(remote)
        except Exception as e:                          # noqa: BLE001
            missing.append(f"{local} ({remote}): {e}")
            continue
        if local in RECOLOR:
            _, old, new = RECOLOR[local]
            svg = svg.replace(old, new)
        dest.write_text(svg)
    have = len(list(ICONS.glob("*.svg")))
    print(f"icons in {ICONS}: {have}")
    for m in missing:
        print("  missing:", m)


if __name__ == "__main__":
    main()
