#!/usr/bin/env python3
"""BuildStream CAS transport manager for bst-ci.

Handles reference construction, archive packaging, extraction, verification,
and ORAS push/pull transport commands for CAS cache artifacts in GHCR.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
import time

MEDIA_TYPE = "application/vnd.buildstream.cas.tar.zst"


def format_cas_ref(
    repo: str,
    image_name: str,
    arch: str,
    target_type: str,
    tag: str,
) -> str:
    """Construct standard GHCR OCI reference for a CAS cache layer."""
    repo_clean = repo.strip().lower()
    arch_suffix = f"-{arch.strip().lower()}" if arch and arch.strip().lower() != "x86_64" else ""
    return f"ghcr.io/{repo_clean}/cache-{image_name}{arch_suffix}-{target_type}:{tag}"


def check_manifest(ref: str) -> bool:
    """Check if the given CAS reference exists in GHCR using oras manifest fetch."""
    try:
        res = subprocess.run(
            ["oras", "manifest", "fetch", ref],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        return res.returncode == 0
    except Exception:
        return False


def pull_and_extract_cas(
    ref: str,
    archive_name: str,
    dest_cache_dir: str,
) -> bool:
    """Pull CAS archive using ORAS and extract into BuildStream cache directory."""
    os.makedirs(dest_cache_dir, exist_ok=True)
    try:
        res = subprocess.run(["oras", "pull", ref, "-o", "."], capture_output=True, text=True, timeout=600)
        if res.returncode != 0:
            return False

        if not os.path.isfile(archive_name):
            return False

        # Decompress zstd and unpack tar
        zstd_proc = subprocess.Popen(["zstd", "-d", "-c", "-T0", archive_name], stdout=subprocess.PIPE)
        tar_proc = subprocess.Popen(["tar", "-xf", "-", "-C", dest_cache_dir], stdin=zstd_proc.stdout)
        if zstd_proc.stdout is not None:
            zstd_proc.stdout.close()
        tar_proc.communicate()
        zstd_proc.wait()

        with contextlib.suppress(OSError):
            os.remove(archive_name)

        return tar_proc.returncode == 0 and zstd_proc.returncode == 0
    except Exception as exc:
        print(f"Error pulling/extracting CAS from {ref}: {exc}", file=sys.stderr)
        return False


def archive_cas(
    bst_image: str,
    src_cache_dir: str,
    output_archive_path: str,
) -> bool:
    """Package BuildStream cache into tar.zst excluding staging and tmp."""
    out_dir = os.path.dirname(os.path.abspath(output_archive_path))
    archive_filename = os.path.basename(output_archive_path)
    os.makedirs(out_dir, exist_ok=True)

    exclude_args = "--exclude 'cas/staging' --exclude 'cas/tmp'"
    cmd = [
        "podman", "run", "--rm",
        "-v", f"{src_cache_dir}:/input:ro",
        "-v", f"{out_dir}:/output:rw",
        bst_image,
        "sh", "-c",
        f"tar -cf - -C /input {exclude_args} . | zstd -T0 > /output/{archive_filename}",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
        return res.returncode == 0 and os.path.isfile(output_archive_path)
    except Exception as exc:
        print(f"Error creating CAS archive: {exc}", file=sys.stderr)
        return False


def push_cas_with_retry(
    ref: str,
    archive_path: str,
    max_retries: int = 3,
    soft_fail: bool = True,
) -> bool:
    """Push CAS archive to GHCR with retry backoff."""
    if not os.path.isfile(archive_path):
        print(f"Archive {archive_path} does not exist", file=sys.stderr)
        return False

    artifact_spec = f"{archive_path}:{MEDIA_TYPE}"
    for attempt in range(1, max_retries + 1):
        try:
            res = subprocess.run(
                ["oras", "push", ref, artifact_spec],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if res.returncode == 0:
                return True
            print(f"CAS push attempt {attempt} for {ref} failed: {res.stderr.strip()}", file=sys.stderr)
        except Exception as exc:
            print(f"CAS push attempt {attempt} for {ref} error: {exc}", file=sys.stderr)

        if attempt < max_retries:
            time.sleep(attempt * 10)

    if soft_fail:
        print(f"::warning::CAS push to {ref} failed after {max_retries} attempts", file=sys.stderr)
        return False
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BuildStream CAS transport manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ref
    p_ref = subparsers.add_parser("ref", help="Construct GHCR CAS reference")
    p_ref.add_argument("--repo", required=True, help="GitHub repository (e.g. tuna-os/tromso)")
    p_ref.add_argument("--image", required=True, help="Image name (e.g. tromso)")
    p_ref.add_argument("--arch", default="x86_64", help="Architecture (x86_64 or aarch64)")
    p_ref.add_argument("--type", required=True, help="Target type (core or chunk identifier)")
    p_ref.add_argument("--tag", required=True, help="Cache tag (latest or composite key)")

    # check
    p_check = subparsers.add_parser("check", help="Check if CAS ref exists in GHCR")
    p_check.add_argument("ref", help="ORAS reference")

    # pull
    p_pull = subparsers.add_parser("pull", help="Pull and extract CAS")
    p_pull.add_argument("--ref", required=True, help="ORAS reference to pull")
    p_pull.add_argument("--archive", required=True, help="Local archive file name")
    p_pull.add_argument("--dest", required=True, help="Destination cache directory")

    # archive
    p_arch = subparsers.add_parser("archive", help="Create tar.zst archive from cache")
    p_arch.add_argument("--image", required=True, help="BST2 container image")
    p_arch.add_argument("--src", required=True, help="Source cache directory")
    p_arch.add_argument("--out", required=True, help="Output archive path")

    # push
    p_push = subparsers.add_parser("push", help="Push CAS archive to GHCR")
    p_push.add_argument("--ref", required=True, help="Target ORAS reference")
    p_push.add_argument("--archive", required=True, help="Path to archive")
    p_push.add_argument("--retries", type=int, default=3, help="Max retry attempts")
    p_push.add_argument("--strict", action="store_true", help="Fail with non-zero exit if push fails")

    args = parser.parse_args(argv)

    if args.command == "ref":
        print(format_cas_ref(args.repo, args.image, args.arch, args.type, args.tag))
        return 0
    elif args.command == "check":
        exists = check_manifest(args.ref)
        print("true" if exists else "false")
        return 0 if exists else 1
    elif args.command == "pull":
        ok = pull_and_extract_cas(args.ref, args.archive, args.dest)
        return 0 if ok else 1
    elif args.command == "archive":
        ok = archive_cas(args.image, args.src, args.out)
        return 0 if ok else 1
    elif args.command == "push":
        ok = push_cas_with_retry(args.ref, args.archive, args.retries, soft_fail=not args.strict)
        return 0 if ok or not args.strict else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
