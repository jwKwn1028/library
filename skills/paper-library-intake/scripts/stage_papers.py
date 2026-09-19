#!/usr/bin/env python3
"""Safely copy external research documents into the private intake inbox."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys
import tempfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from paperlib.media import (  # noqa: E402
    INBOX_DIRECTORY,
    LIBRARY_DIRECTORY,
    MediaError,
    media_files,
    sha256,
    validate_media,
)
from intake_papers import (  # noqa: E402
    INTERRUPTED_EXIT_CODE,
    IntakeError,
    library_lock,
)


class StageError(RuntimeError):
    """A staging preflight or copy failed."""


@dataclass(frozen=True)
class StagePlan:
    source: Path
    destination: Path
    digest: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or copy explicit external PDF, EPUB, or MOBI files into "
            "the private Inbox without changing the originals."
        )
    )
    parser.add_argument("sources", type=Path, nargs="+", help="files to stage")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="library root")
    parser.add_argument("--apply", action="store_true", help="copy the reviewed plan")
    parser.add_argument(
        "--lock-timeout",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="seconds to wait for the library lock (default: 5)",
    )
    return parser.parse_args()


def source_path(value: Path) -> Path:
    expanded = value.expanduser()
    candidate = expanded if expanded.is_absolute() else Path.cwd() / expanded
    if candidate.is_symlink():
        raise StageError(f"source must not be a symlink: {value}")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise StageError(f"cannot resolve source {value}: {error}") from error
    if not resolved.is_file():
        raise StageError(f"source is not a regular file: {value}")
    try:
        validate_media(resolved)
    except MediaError as error:
        raise StageError(str(error)) from error
    return resolved


def existing_media_hashes(root: Path) -> dict[str, Path]:
    hashes: dict[str, Path] = {}
    for directory_name in (INBOX_DIRECTORY, LIBRARY_DIRECTORY):
        try:
            candidates = media_files(root, directory_name)
        except MediaError as error:
            raise StageError(str(error)) from error
        for candidate in candidates:
            if candidate.is_symlink():
                raise StageError(f"existing media must not be a symlink: {candidate}")
            hashes.setdefault(sha256(candidate), candidate)
    return hashes


def build_plans(root: Path, sources: list[Path]) -> list[StagePlan]:
    inbox = root / "Inbox"
    existing_hashes = existing_media_hashes(root)
    destinations: set[Path] = set()
    digests: dict[str, Path] = {}
    plans: list[StagePlan] = []
    for value in sources:
        source = source_path(value)
        destination = inbox / source.name
        if destination in destinations:
            raise StageError(
                f"multiple sources target the same inbox path: {destination}"
            )
        if destination.exists() or destination.is_symlink():
            raise StageError(f"inbox destination already exists: {destination}")
        digest = sha256(source)
        duplicate = existing_hashes.get(digest) or digests.get(digest)
        if duplicate is not None:
            raise StageError(
                f"source duplicates existing content: {source} and {duplicate}"
            )
        destinations.add(destination)
        digests[digest] = source
        plans.append(StagePlan(source, destination, digest))
    return plans


def print_plans(root: Path, plans: list[StagePlan], apply: bool) -> None:
    print(
        "STAGE PLAN — copies begin after this summary"
        if apply
        else "DRY RUN — no files changed"
    )
    for plan in plans:
        print()
        print(f"COPY   {plan.source}")
        print(f"    -> {plan.destination.relative_to(root)}")
        print(f"FORMAT {plan.source.suffix.removeprefix('.').upper()}")
        print(f"SHA256 {plan.digest}")


def copy_plans(root: Path, plans: list[StagePlan]) -> None:
    inbox = root / "Inbox"
    inbox_existed = inbox.exists()
    inbox.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    temporary_paths: list[Path] = []
    try:
        for plan in plans:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{plan.destination.stem}.",
                suffix=plan.destination.suffix,
                dir=inbox,
            )
            os.close(descriptor)
            temporary_path = Path(temporary_name)
            temporary_paths.append(temporary_path)
            shutil.copy2(plan.source, temporary_path)
            validate_media(temporary_path)
            if sha256(temporary_path) != plan.digest:
                raise StageError(f"staged copy hash mismatch: {plan.source}")
            try:
                os.link(temporary_path, plan.destination)
            except FileExistsError as error:
                raise StageError(
                    f"inbox destination appeared during staging: {plan.destination}"
                ) from error
            created.append(plan.destination)
            temporary_path.unlink()
            temporary_paths.remove(temporary_path)
    # BaseException also covers Ctrl-C, which must not leave partial copies.
    except BaseException as error:
        for path in temporary_paths:
            path.unlink(missing_ok=True)
        for path in reversed(created):
            path.unlink(missing_ok=True)
        if not inbox_existed:
            try:
                inbox.rmdir()
            except OSError:
                pass
        if not isinstance(error, Exception):
            raise
        if isinstance(error, (MediaError, StageError)):
            raise StageError(str(error)) from error
        raise StageError(
            f"staging failed and copied files were rolled back: {error}"
        ) from error


def main() -> int:
    try:
        args = parse_args()
        root = args.root.expanduser().resolve()
        if not root.is_dir():
            raise StageError(f"library root does not exist: {root}")
        with library_lock(root, args.lock_timeout):
            plans = build_plans(root, args.sources)
            print_plans(root, plans, args.apply)
            if not args.apply:
                print(
                    "\nDry run complete. Re-run with --apply after reviewing this plan."
                )
                return 0
            copy_plans(root, plans)
            print(f"\nStaged {len(plans)} file(s) in Inbox; originals were preserved.")
            return 0
    except KeyboardInterrupt:
        print("ERROR: interrupted; no partial Inbox copies were left", file=sys.stderr)
        return INTERRUPTED_EXIT_CODE
    except (IntakeError, MediaError, OSError, StageError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
