#!/usr/bin/env python3
"""Move BuildStream CAS archives between a runner and GHCR.

The multi-runner workflow keeps the CAS of each stage (core, and every
dependency chunk) as one zstd tarball on GHCR. This script owns that
transport: the reference format, the media type, the archive filter, the
restore stream, the builder shutdown before an archive and the push policy.
The workflow keeps the job topology and the build policy.

Usage:
    cas_transport.py ref <repository> <image_name> <arch_suffix> <stage> <tag>
    cas_transport.py exists <ref>
    cas_transport.py restore <ref> <cache_dir>
    cas_transport.py stop-builders <bst2_image> <workspace>
    cas_transport.py archive <bst2_image> <cache_dir> <output_dir> <file>
                             [--reserve-bytes N]
    cas_transport.py push <ref> <file> [--best-effort]

Exit codes: 0 on success. `exists` exits 1 when the reference has no
manifest. `archive --reserve-bytes` exits 1 when it skips or fails the
archive; it prints a workflow warning first and removes the partial file.
Other failures exit non-zero.
"""

import argparse
import contextlib
import hashlib
import http.client
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

MEDIA_TYPE = "application/vnd.buildstream.cas.tar.zst"

# The archive and the restore use the same filter. Sources are cached
# separately (actions/cache), logs go to artifacts, and staging, tmp and
# sockets are unfinished or live state that must not reach another runner.
EXCLUDES = ("./sources", "./logs", "./cas/staging", "./cas/tmp", "*.sock")

PUSH_ATTEMPTS = 3

# Blob download: block size, and how many connections one blob may use.
BLOCK = 4 * 1024 * 1024
FETCH_ATTEMPTS = 40


def ref(repository, image_name, arch_suffix, stage, tag):
    """GHCR reference of one stage's CAS archive."""
    return f"ghcr.io/{repository.lower()}/cache-{image_name}{arch_suffix}-{stage}:{tag}"


def tar_excludes():
    return [f"--exclude={pattern}" for pattern in EXCLUDES]


def warn(message):
    print(f"::warning::{message}", flush=True)


def exists(reference):
    result = subprocess.run(
        ["oras", "manifest", "fetch", reference],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def cas_layer(manifest_json):
    """(digest, size) of the CAS layer in a manifest; error if there is none."""
    for layer in json.loads(manifest_json).get("layers", []):
        if layer.get("mediaType") == MEDIA_TYPE:
            return layer["digest"], int(layer["size"])
    raise SystemExit(f"manifest has no {MEDIA_TYPE} layer")


def cas_layer_digest(manifest_json):
    """Digest of the CAS layer in a manifest; error if there is none."""
    return cas_layer(manifest_json)[0]


def split_ref(reference):
    """`ghcr.io/owner/repo/name:tag` -> (registry, `owner/repo/name`, tag)."""
    registry, _, rest = reference.partition("/")
    name, _, tag = rest.rpartition(":")
    return registry, name, tag


def registry_url(registry):
    """Base URL of a registry. A loopback registry (the tests) uses plain HTTP."""
    scheme = "http" if registry.split(":")[0] in ("127.0.0.1", "localhost") else "https"
    return f"{scheme}://{registry}"


def stored_auth(registry, auth_file=None):
    """Basic credential that `oras login` or `podman login` stored, or None."""
    candidates = (
        [auth_file]
        if auth_file
        else [
            os.environ.get("DOCKER_CONFIG") and os.path.join(os.environ["DOCKER_CONFIG"], "config.json"),
            os.path.expanduser("~/.docker/config.json"),
            os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/nonexistent"), "containers/auth.json"),
        ]
    )
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        try:
            auths = json.loads(Path(path).read_text()).get("auths", {})
        except (OSError, ValueError):
            continue
        for key in (registry, f"https://{registry}"):
            if auths.get(key, {}).get("auth"):
                return auths[key]["auth"]
    return None


def pull_token(registry, name, basic=None):
    """Registry token limited to `pull` on one repository; anonymous without `basic`."""
    request = urllib.request.Request(
        f"{registry_url(registry)}/token?service={registry}&scope=repository:{name}:pull"
    )
    if basic:
        request.add_header("Authorization", f"Basic {basic}")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)["token"]


def stream_blob(reference, digest, size, out, offset=0, token_source=None, opener=None, pause=time.sleep):
    """Write bytes `offset`..`size` of blob `digest` to `out`; return their SHA-256 object.

    GHCR cuts a download of a multi-gigabyte blob after some minutes
    ("stream error: stream ID 1; PROTOCOL_ERROR"), and `oras blob fetch`
    cannot continue it. Each cut here continues with an HTTP Range request
    from the byte it reached, so the consumer of `out` sees one whole stream.
    The caller compares the returned hash with `digest` (when `offset` is 0).
    """
    registry, name, _ = split_ref(reference)
    opener = opener or urllib.request.urlopen
    token_source = token_source or (lambda: pull_token(registry, name, stored_auth(registry)))
    url = f"{registry_url(registry)}/v2/{name}/blobs/{digest}"
    sha = hashlib.sha256()
    token = token_source()
    attempt = 0
    while offset < size:
        attempt += 1
        if attempt > FETCH_ATTEMPTS:
            raise SystemExit(f"blob fetch stopped at byte {offset} of {size} after {FETCH_ATTEMPTS} attempts")
        request = urllib.request.Request(url)
        # Not forwarded on the redirect to the signed storage URL.
        request.add_unredirected_header("Authorization", f"Bearer {token}")
        if offset:
            request.add_header("Range", f"bytes={offset}-")
        try:
            with opener(request, timeout=120) as response:
                if offset and response.status != 206:
                    raise SystemExit(f"server ignored Range (HTTP {response.status}); cannot resume")
                while offset < size:
                    block = response.read(min(BLOCK, size - offset))
                    if not block:
                        break
                    out.write(block)
                    sha.update(block)
                    offset += len(block)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise SystemExit(f"blob {digest} is not in {registry}/{name} (HTTP 404)") from error
            if error.code == 401:
                token = token_source()
            print(
                f"blob fetch: HTTP {error.code} at byte {offset} (attempt {attempt}); retrying",
                file=sys.stderr,
                flush=True,
            )
            pause(min(30, 2 * attempt))
        except (OSError, http.client.HTTPException) as error:
            if isinstance(error, BrokenPipeError):
                raise SystemExit("blob fetch: the consumer of the stream stopped") from error
            print(
                f"blob fetch: connection cut at byte {offset} (attempt {attempt}): {error}; resuming",
                file=sys.stderr,
                flush=True,
            )
            pause(min(30, 2 * attempt))
    if attempt > 1:
        print(f"blob fetch: complete after {attempt} connections", file=sys.stderr, flush=True)
    return sha


def restore(reference, cache_dir, pause=time.sleep):
    """Stream the archive at `reference` into `cache_dir`.

    A reference that has no manifest is a cold cache, not an error. Once the
    manifest exists, a failure in the fetch, the decompression or the
    extraction fails the restore, and so does a stream whose SHA-256 is not
    the layer digest.
    """
    os.makedirs(cache_dir, exist_ok=True)
    manifest = subprocess.run(
        ["oras", "manifest", "fetch", reference], capture_output=True, text=True, check=False
    )
    if manifest.returncode != 0:
        print(f"No existing cache at {reference}, starting fresh.", flush=True)
        return
    digest, size = cas_layer(manifest.stdout)
    unzstd = subprocess.Popen(["zstd", "-d", "-c", "-T0"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    untar = subprocess.Popen(["tar", "-xf", "-", "-C", cache_dir, *tar_excludes()], stdin=unzstd.stdout)
    unzstd.stdout.close()
    found = None
    error = None
    try:
        found = "sha256:" + stream_blob(reference, digest, size, unzstd.stdin, pause=pause).hexdigest()
    except SystemExit as stop:
        error = str(stop)
    with contextlib.suppress(OSError):
        unzstd.stdin.close()
    codes = [untar.wait(), unzstd.wait()]
    if error:
        raise SystemExit(f"restore of {reference} failed: {error}")
    if found != digest:
        raise SystemExit(f"restore of {reference} failed: stream is {found}, the manifest says {digest}")
    if any(codes):
        raise SystemExit(f"restore of {reference} failed (tar, zstd exit codes: {codes})")


def stop_builders(bst2_image, workspace):
    """Stop the bst2 containers that mount this job's workspace at /src.

    The build client can exit before its container. A container that still
    writes to the CAS during the archive gives a torn archive. Containers of
    other workspaces on a shared runner are left running.
    """
    workspace = os.path.realpath(workspace)
    builders = subprocess.run(
        ["podman", "ps", "--quiet", "--filter", f"ancestor={bst2_image}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    for builder in builders:
        inspect = subprocess.run(
            [
                "podman",
                "inspect",
                "--format",
                '{{range .Mounts}}{{if eq .Destination "/src"}}{{.Source}}{{end}}{{end}}',
                builder,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if inspect.returncode == 0:
            if inspect.stdout.strip() == workspace:
                subprocess.run(["podman", "stop", "--ignore", "--time", "30", builder], check=True)
            continue
        # An auto-removed container has already stopped; other errors fail.
        status = subprocess.run(["podman", "container", "exists", builder], check=False).returncode
        if status != 1:
            raise SystemExit(f"cannot inspect builder {builder} (podman container exists: {status})")


def free_bytes(path):
    return shutil.disk_usage(path).free


def archive(bst2_image, cache_dir, output_dir, filename, reserve_bytes=None):
    """Write `cache_dir` as `output_dir/filename` inside the bst2 container.

    The archive runs in the container because the CAS is written by its
    root user. With `reserve_bytes`, the archive keeps that much disk free,
    and a skip or failure is a warning (return False) instead of an error.
    """
    excludes = " ".join(f"--exclude '{pattern}'" for pattern in EXCLUDES)
    limit = ""
    if reserve_bytes is not None:
        avail = free_bytes(output_dir)
        print(f"disk free before CAS archive: {avail // 1048576} MiB", flush=True)
        if avail <= reserve_bytes:
            warn(
                f"only {avail // 1048576} MiB free; skipping the CAS archive and cache push"
                " — the next run rebuilds this stage"
            )
            return False
        # head -c stops the archive before it eats the reserve; zstd then gets
        # SIGPIPE and the pipeline fails into the warning below.
        limit = f" | head -c {avail - reserve_bytes}"
    command = f"tar -cf - -C /input {excludes} . | zstd -T0{limit} > /output/{filename}"
    result = subprocess.run(
        [
            "podman",
            "run",
            "--rm",
            "-v",
            f"{cache_dir}:/input:ro",
            "-v",
            f"{output_dir}:/output:rw",
            bst2_image,
            "bash",
            "-o",
            "pipefail",
            "-c",
            command,
        ],
        check=False,
    )
    if result.returncode == 0:
        return True
    Path(output_dir, filename).unlink(missing_ok=True)
    if reserve_bytes is None:
        raise SystemExit(f"CAS archive {filename} failed (exit {result.returncode})")
    warn("CAS archive failed; skipping the cache push — the next run rebuilds this stage")
    return False


def push(reference, filename, best_effort=False, retry_delay=10):
    """Push `filename` as the CAS layer of `reference`.

    Without `best_effort`, one attempt and a failure is an error. With it,
    transient registry errors are retried and a final failure is a warning:
    the tag is a cache, so a lost push costs the next run rebuild time only.
    """
    command = ["oras", "push", reference, f"{filename}:{MEDIA_TYPE}"]
    if not best_effort:
        rc = subprocess.run(command, check=False).returncode
        if rc != 0:
            raise SystemExit(f"push to {reference} failed (exit {rc})")
        return
    for attempt in range(1, PUSH_ATTEMPTS + 1):
        if subprocess.run(command, check=False).returncode == 0:
            return
        if attempt < PUSH_ATTEMPTS:
            print(
                f"cache push attempt {attempt} for {reference} failed; retrying in {attempt * retry_delay}s",
                flush=True,
            )
            time.sleep(attempt * retry_delay)
    warn(
        f"cache push to {reference} failed after {PUSH_ATTEMPTS} attempts"
        " — the next run rebuilds this stage instead of restoring it"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ref")
    for name in ("repository", "image_name", "arch_suffix", "stage", "tag"):
        p.add_argument(name)

    p = sub.add_parser("exists")
    p.add_argument("ref")

    p = sub.add_parser("restore")
    p.add_argument("ref")
    p.add_argument("cache_dir")

    p = sub.add_parser("stop-builders")
    p.add_argument("bst2_image")
    p.add_argument("workspace")

    p = sub.add_parser("archive")
    p.add_argument("bst2_image")
    p.add_argument("cache_dir")
    p.add_argument("output_dir")
    p.add_argument("file")
    p.add_argument("--reserve-bytes", type=int)

    p = sub.add_parser("push")
    p.add_argument("ref")
    p.add_argument("file")
    p.add_argument("--best-effort", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "ref":
        print(ref(args.repository, args.image_name, args.arch_suffix, args.stage, args.tag))
    elif args.command == "exists":
        return 0 if exists(args.ref) else 1
    elif args.command == "restore":
        delay = os.environ.get("CAS_FETCH_RETRY_DELAY")
        restore(args.ref, args.cache_dir, (lambda _s: time.sleep(float(delay))) if delay else time.sleep)
    elif args.command == "stop-builders":
        stop_builders(args.bst2_image, args.workspace)
    elif args.command == "archive":
        ok = archive(args.bst2_image, args.cache_dir, args.output_dir, args.file, args.reserve_bytes)
        return 0 if ok else 1
    elif args.command == "push":
        delay = int(os.environ.get("CAS_PUSH_RETRY_DELAY", "10"))
        push(args.ref, args.file, args.best_effort, delay)
    return 0


if __name__ == "__main__":
    sys.exit(main())
