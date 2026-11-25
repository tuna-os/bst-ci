#!/usr/bin/env python3
"""Extract a BuildStream CAS tar stream and refuse damaged objects.

Usage: zstd -d -c cas.tar.zst | cas_untar.py <cache_dir>

A CAS object is a file `cas/objects/<2 hex>/<62 hex>` and its name is the
SHA-256 of its content. buildbox-casd and BuildStream trust that name and do
not read the content again. Restores that the registry cut left a truncated
object on disk, the next archive carried it on, and a later build mapped a
short libLLVM and died with SIGBUS (tuna-os/brussels run 45560680452). So
this script:

- writes an object only after its content matches its name;
- drops an object that does not match, with a warning. BuildStream then
  finds the artifact incomplete and pulls or builds it again;
- keeps an object that is already on disk when its size is the same, and
  replaces it when the size differs;
- writes each file under a temporary name first, so a stream that stops
  leaves no short file.

Exit code: 0 when the whole stream was read, also when objects were dropped.
"""

import argparse
import fnmatch
import hashlib
import os
import re
import sys
import tarfile

from cas_transport import EXCLUDES

OBJECT = re.compile(r"cas/objects/([0-9a-f]{2})/([0-9a-f]{62})")
BLOCK = 1024 * 1024


def excluded(name):
    """True for a path that the archive filter (EXCLUDES) leaves out."""
    for pattern in EXCLUDES:
        if pattern.startswith("./"):
            if name == pattern[2:] or name.startswith(pattern[2:] + "/"):
                return True
        elif fnmatch.fnmatch(os.path.basename(name), pattern):
            return True
    return False


def write_object(source, target, member, digest):
    """Write one object; return False when its content is not `digest`."""
    temporary = f"{target}.part"
    sha = hashlib.sha256()
    try:
        with open(temporary, "wb") as out:
            while block := source.read(BLOCK):
                sha.update(block)
                out.write(block)
        if sha.hexdigest() != digest:
            return False
        os.chmod(temporary, member.mode & 0o777)
        # casd expires objects by modification time.
        os.utime(temporary, (member.mtime, member.mtime))
        os.replace(temporary, target)
        return True
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def extract(stream, cache_dir):
    """Extract `stream`; return (objects written, objects dropped)."""
    written = dropped = 0
    directories = set()
    # Streaming mode keeps no list of members: 2.4 million per archive.
    with tarfile.open(fileobj=stream, mode="r|") as archive:
        for member in archive:
            archive.members = []
            name = os.path.normpath(member.name)
            if name == "." or excluded(name):
                continue
            target = os.path.join(cache_dir, name)
            match = OBJECT.fullmatch(name)
            if not match:
                if name.startswith("cas/objects/") and not member.isdir():
                    # A temporary or link name is not an object.
                    continue
                if member.isdir():
                    os.makedirs(target, exist_ok=True)
                    continue
                # Refuses a path outside the cache, before the unlink.
                tarfile.tar_filter(member, cache_dir)
                if os.path.lexists(target):
                    os.unlink(target)
                archive.extract(member, cache_dir, filter="tar")
                continue
            if not member.isfile():
                continue
            # An object on disk was verified when it was restored.
            if os.path.exists(target) and os.path.getsize(target) == member.size:
                continue
            parent = os.path.dirname(target)
            if parent not in directories:
                os.makedirs(parent, exist_ok=True)
                directories.add(parent)
            if write_object(archive.extractfile(member), target, member, match[1] + match[2]):
                written += 1
            else:
                dropped += 1
                print(
                    f"::warning::dropped CAS object {match[1]}{match[2]}:"
                    f" its {member.size} bytes do not match its name",
                    flush=True,
                )
    # A tar ends with zero blocks; read them so zstd gets no SIGPIPE.
    while stream.read(BLOCK):
        pass
    return written, dropped


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cache_dir")
    args = parser.parse_args(argv)
    os.makedirs(args.cache_dir, exist_ok=True)
    written, dropped = extract(sys.stdin.buffer, args.cache_dir)
    print(f"cas_untar: {written} objects written, {dropped} dropped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
