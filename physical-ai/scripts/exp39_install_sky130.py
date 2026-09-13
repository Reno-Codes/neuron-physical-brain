"""Install official SKY130 open_pdks primitives via ciel-releases.

Windows-safe extract: download .tar.zst, decompress to .tar, then extract.
Does not invent models. Does not put the PDK inside the git repo.
"""

from __future__ import annotations

import json
import os
import tarfile
from pathlib import Path

import httpx
import zstandard as zstd

VERSION = "1689ac3f2dc763876eaf967227c7dfe831b031ae"
FAMILY = "sky130"
PDK_ROOT = Path(r"C:\dev\pdk")
RELEASES = "https://fossi-foundation.github.io/ciel-releases"
WANTED = ("common", "sky130_fd_pr")


def dest_version() -> Path:
    return PDK_ROOT / "ciel" / FAMILY / "versions" / VERSION


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        print(f"already have {path} ({path.stat().st_size} bytes)")
        return
    print(f"GET {url}")
    with httpx.stream("GET", url, follow_redirects=True, timeout=300.0) as r:
        r.raise_for_status()
        tmp = path.with_suffix(path.suffix + ".part")
        n = 0
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1024 * 256):
                f.write(chunk)
                n += len(chunk)
        tmp.replace(path)
    print(f"wrote {path} ({n} bytes)")


def extract_zst(zst_path: Path, out_dir: Path) -> None:
    tar_path = zst_path.with_suffix("")  # .tar
    if not tar_path.exists() or tar_path.stat().st_size == 0:
        print(f"decompress {zst_path.name}")
        dctx = zstd.ZstdDecompressor()
        with zst_path.open("rb") as src, tar_path.open("wb") as dst:
            dctx.copy_stream(src, dst)
    print(f"extract {tar_path.name} -> {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r") as tf:
        tf.extractall(out_dir)


def enable() -> None:
    current = PDK_ROOT / "ciel" / FAMILY / "current"
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_text(VERSION + "\n", encoding="ascii")
    version_dir = dest_version()
    for variant in ("sky130A", "sky130B"):
        src = version_dir / variant
        dst = PDK_ROOT / variant
        if not src.is_dir():
            continue
        if dst.exists() or dst.is_symlink():
            if dst.is_symlink() or dst.is_junction():
                dst.unlink()
            else:
                print(f"leave existing {dst}")
                continue
        try:
            os.symlink(src, dst, target_is_directory=True)
            print(f"symlink {dst} -> {src}")
        except OSError as e:
            print(f"symlink failed ({e}); using junction")
            os.system(f'cmd /c mklink /J "{dst}" "{src}"')


def main() -> None:
    man_url = f"{RELEASES}/{FAMILY}/{VERSION}/manifest.json"
    print(f"GET {man_url}")
    r = httpx.get(man_url, follow_redirects=True, timeout=60.0)
    r.raise_for_status()
    manifest = r.json()
    downloads = PDK_ROOT / "downloads" / FAMILY / VERSION
    downloads.mkdir(parents=True, exist_ok=True)
    (downloads / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    by_content = {a["content"]: a for a in manifest["assets"]}
    version_dir = dest_version()
    version_dir.mkdir(parents=True, exist_ok=True)
    for name in WANTED:
        asset = by_content[name]
        zst = downloads / asset["filename"]
        download(asset["url"], zst)
        extract_zst(zst, version_dir)
    enable()
    print("PDK_ROOT", PDK_ROOT)
    print("version", VERSION)
    print("sky130A", (PDK_ROOT / "sky130A").exists())


if __name__ == "__main__":
    main()
