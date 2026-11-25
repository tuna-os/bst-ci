#!/usr/bin/env python3
"""Seed a developer's BuildStream cache from the CAS archives CI publishes.

The multi-runner workflow keeps the CAS of each stage as one zstd tarball on
GHCR (see cas_transport.py). This script is the read-only side for a
developer machine: it downloads those archives, verifies them and extracts
them into a local BuildStream cache directory. After that, `bst build`
rebuilds only the elements whose cache key differs from the published ones.

It has no push path. It asks the registry for a pull-scoped token only, and
it does not read any stored credential unless --auth-file is given.

Usage:
    cas_bootstrap.py list <repository> <image_name> [stage ...]
    cas_bootstrap.py pull <repository> <image_name> <cache_dir> [stage ...]
                          [--arch-suffix S] [--tag T] [--keep-archives]
                          [--reserve-gib N] [--auth-file PATH]
    cas_bootstrap.py states [file]

`stage` defaults to `core`. Chunk stages are named by the planner, for
example `chunk0-cmake`; the planning job of a nightly run prints them.

`pull` is resumable. An interrupted download continues from the byte it
reached, and a stage whose published digest is already recorded in
<cache_dir>/.cas-bootstrap/ is skipped. An archive is extracted only after
its SHA-256 equals the digest in the registry manifest.

`states` reads `bst show --format '%{name}||%{state}'` output and prints how
many elements are already cached and how many remain to build.

Exit codes: 0 on success, 1 on a failed or refused operation, 2 on usage.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cas_transport  # noqa: E402  (one owner for the ref format and filter)

MANIFEST_TYPES = "application/vnd.oci.image.manifest.v1+json"
STATE_DIR = ".cas-bootstrap"
BLOCK = 4 * 1024 * 1024
# The archives expand to about three times their compressed size
# (measured on the tromso core archive, 2026-11).
EXPANSION = 3


def log(message):
    print(f"cas-bootstrap: {message}", file=sys.stderr, flush=True)


def gib(count):
    return f"{count / 1024**3:.1f} GiB"


def split_ref(reference):
    return cas_transport.split_ref(reference)


def stored_auth(auth_file, registry):
    """Basic credential for `registry` from a docker-style auth file."""
    basic = cas_transport.stored_auth(registry, auth_file)
    if not basic:
        raise SystemExit(f"{auth_file} has no credential for {registry}")
    return basic


def pull_token(registry, name, auth_file=None):
    """Registry token limited to `pull` on one repository; anonymous by default.

    Stored credentials are read only when `auth_file` names a file.
    """
    request = urllib.request.Request(
        f"{cas_transport.registry_url(registry)}/token?service={registry}&scope=repository:{name}:pull"
    )
    if auth_file:
        request.add_header("Authorization", f"Basic {stored_auth(auth_file, registry)}")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)["token"]


def fetch_manifest(reference, auth_file=None):
    """Manifest of `reference`, or None when the registry has none."""
    registry, name, tag = split_ref(reference)
    try:
        token = pull_token(registry, name, auth_file)
        request = urllib.request.Request(f"{cas_transport.registry_url(registry)}/v2/{name}/manifests/{tag}")
        request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Accept", MANIFEST_TYPES)
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403, 404):
            return None
        raise


def cas_layer(manifest):
    """(digest, size) of the CAS layer in a manifest."""
    return cas_transport.cas_layer(json.dumps(manifest))


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while block := stream.read(BLOCK):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def download(reference, digest, size, target, auth_file=None, opener=None, pause=time.sleep):
    """Write the blob `digest` to `target`, resuming a partial file.

    The registry cuts multi-gigabyte downloads every few minutes, and a
    developer can stop a download at any time. Both cases continue with an
    HTTP Range request from the size of the partial file. The transfer is
    cas_transport.stream_blob, the same code the CI restore uses.
    """
    registry, name, _ = split_ref(reference)
    part = Path(f"{target}.part")
    offset = part.stat().st_size if part.exists() else 0
    if offset > size:
        part.unlink()
        offset = 0
    if offset:
        log(f"resuming at {gib(offset)} of {gib(size)}")
    started = time.monotonic()
    with open(part, "ab") as out:
        cas_transport.stream_blob(
            reference,
            digest,
            size,
            out,
            offset=offset,
            token_source=lambda: pull_token(registry, name, auth_file),
            opener=opener,
            pause=pause,
        )
    received = size - offset
    seconds = max(time.monotonic() - started, 0.001)
    log(f"downloaded {gib(received)} in {seconds:.0f}s ({received / seconds / 1024**2:.0f} MiB/s)")
    found = file_sha256(part)
    if found != digest:
        part.unlink()
        raise SystemExit(
            f"digest mismatch for {reference}: got {found}, expected {digest}; partial file removed"
        )
    part.rename(target)
    return seconds


def extract(archive, cache_dir):
    """Extract a verified archive into `cache_dir` with the transport filter."""
    unzstd = subprocess.Popen(["zstd", "-d", "-c", "-T0", str(archive)], stdout=subprocess.PIPE)
    untar = subprocess.Popen(
        ["tar", "-xf", "-", "-C", str(cache_dir), "--no-same-owner", *cas_transport.tar_excludes()],
        stdin=unzstd.stdout,
    )
    unzstd.stdout.close()
    codes = [untar.wait(), unzstd.wait()]
    if any(codes):
        raise SystemExit(f"extraction of {archive} failed (tar, zstd exit codes: {codes})")


def read_stamp(state, stage):
    try:
        return json.loads((state / f"{stage}.json").read_text())
    except (OSError, ValueError):
        return {}


def pull_stage(reference, stage, cache_dir, args):
    """Seed one stage. Returns a summary row."""
    state = Path(cache_dir) / STATE_DIR
    state.mkdir(parents=True, exist_ok=True)
    manifest = fetch_manifest(reference, args.auth_file)
    if manifest is None:
        raise SystemExit(
            f"no readable manifest at {reference}. Check the stage name. If the package is private, "
            "pass --auth-file with a token that has the read:packages scope."
        )
    digest, size = cas_layer(manifest)
    if read_stamp(state, stage).get("digest") == digest:
        log(f"{stage}: already seeded from {digest[:19]}, skipping")
        return {"stage": stage, "digest": digest, "size": size, "status": "already seeded"}
    archive = state / f"{digest.replace(':', '-')}.tar.zst"
    have = 0
    if archive.exists():
        have = size
    elif Path(f"{archive}.part").exists():
        have = Path(f"{archive}.part").stat().st_size
    needed = (size - have) + EXPANSION * size + args.reserve_gib * 1024**3
    free = shutil.disk_usage(cache_dir).free
    if free < needed:
        raise SystemExit(
            f"{stage}: {gib(free)} free in {cache_dir}, about {gib(needed)} needed "
            f"({gib(size)} archive, about {gib(EXPANSION * size)} extracted, {args.reserve_gib} GiB reserve)"
        )
    log(f"{stage}: {reference} {digest[:19]} ({gib(size)} compressed)")
    seconds = 0.0
    if archive.exists():
        if file_sha256(archive) != digest:
            archive.unlink()
            raise SystemExit(f"{stage}: the kept archive no longer matches {digest}; removed it, run again")
    else:
        seconds = download(reference, digest, size, archive, args.auth_file)
    log(f"{stage}: digest verified, extracting into {cache_dir}")
    started = time.monotonic()
    extract(archive, cache_dir)
    extract_seconds = time.monotonic() - started
    stamp = {
        "ref": reference,
        "digest": digest,
        "size": size,
        "created": manifest.get("annotations", {}).get("org.opencontainers.image.created"),
        "restored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (state / f"{stage}.json").write_text(json.dumps(stamp, indent=2) + "\n")
    if not args.keep_archives:
        archive.unlink()
    return {
        "stage": stage,
        "digest": digest,
        "size": size,
        "status": f"seeded (download {seconds:.0f}s, extract {extract_seconds:.0f}s)",
    }


def stage_refs(args):
    stages = args.stage or ["core"]
    return [
        (stage, cas_transport.ref(args.repository, args.image_name, args.arch_suffix, stage, args.tag))
        for stage in stages
    ]


def command_list(args):
    missing = 0
    for stage, reference in stage_refs(args):
        manifest = fetch_manifest(reference, args.auth_file)
        if manifest is None:
            print(f"{stage}\t-\t-\t{reference}\tno readable manifest")
            missing += 1
            continue
        digest, size = cas_layer(manifest)
        created = manifest.get("annotations", {}).get("org.opencontainers.image.created", "-")
        print(f"{stage}\t{gib(size)}\t{created}\t{reference}\t{digest}")
    return 1 if missing else 0


def command_pull(args):
    for tool in ("zstd", "tar"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} is required and was not found on PATH")
    os.makedirs(args.cache_dir, exist_ok=True)
    rows = [pull_stage(reference, stage, args.cache_dir, args) for stage, reference in stage_refs(args)]
    for row in rows:
        print(f"{row['stage']}\t{gib(row['size'])}\t{row['digest'][:19]}\t{row['status']}")
    return 0


def count_states(lines):
    """Count elements by state from `name||state` lines; other lines are ignored."""
    counts = {}
    for line in lines:
        parts = line.strip().split("||")
        if len(parts) < 2 or not parts[0].endswith(".bst"):
            continue
        counts[parts[1]] = counts.get(parts[1], 0) + 1
    return counts


def command_states(args):
    text = Path(args.file).read_text() if args.file else sys.stdin.read()
    counts = count_states(text.splitlines())
    total = sum(counts.values())
    if not total:
        raise SystemExit("no `name||state` lines found; use bst show --format '%{name}||%{state}'")
    cached = counts.get("cached", 0)
    detail = ", ".join(f"{state} {count}" for state, count in sorted(counts.items()))
    share = 100 * cached // total
    print(f"{cached} of {total} elements are in the local cache ({share}%), {total - cached} to build")
    print(f"states: {detail}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def remote(p, with_cache):
        p.add_argument("repository", help="owner/repo, e.g. tuna-os/tromso")
        p.add_argument("image_name", help="e.g. tromso")
        if with_cache:
            p.add_argument("cache_dir")
        p.add_argument("stage", nargs="*", help="default: core")
        p.add_argument("--arch-suffix", default="")
        p.add_argument("--tag", default="latest")
        p.add_argument("--auth-file", help="docker-style auth file; only for a private package")

    remote(sub.add_parser("list"), with_cache=False)
    p = sub.add_parser("pull")
    remote(p, with_cache=True)
    p.add_argument("--keep-archives", action="store_true")
    p.add_argument("--reserve-gib", type=int, default=10, help="disk to keep free (default 10)")
    p = sub.add_parser("states")
    p.add_argument("file", nargs="?")

    args = parser.parse_args(argv)
    if args.command == "list":
        return command_list(args)
    if args.command == "pull":
        return command_pull(args)
    return command_states(args)


if __name__ == "__main__":
    sys.exit(main())
