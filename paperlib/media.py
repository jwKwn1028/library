"""Validation and hashing for supported research-document formats."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import zipfile


SUPPORTED_EXTENSIONS = {".epub", ".mobi", ".pdf"}


class MediaError(RuntimeError):
    """A document is missing, unsafe, or does not match its extension."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_pdf(path: Path) -> None:
    try:
        with path.open("rb") as stream:
            signature = stream.read(5)
    except OSError as error:
        raise MediaError(f"cannot read PDF {path}: {error}") from error
    if signature != b"%PDF-":
        raise MediaError(f"file does not have a PDF signature: {path}")
    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo:
        result = subprocess.run(
            [pdfinfo, str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            raise MediaError(f"pdfinfo could not parse: {path}")


def _check_epub(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not entries or entries[0].filename != "mimetype":
                raise MediaError(f"EPUB does not begin with a mimetype entry: {path}")
            mimetype = entries[0]
            if mimetype.compress_type != zipfile.ZIP_STORED:
                raise MediaError(f"EPUB mimetype entry is compressed: {path}")
            if mimetype.extra or mimetype.flag_bits & 0x1:
                raise MediaError(f"EPUB mimetype entry has unsupported flags: {path}")
            if archive.read(mimetype) != b"application/epub+zip":
                raise MediaError(f"EPUB has an invalid mimetype value: {path}")
            if "META-INF/container.xml" not in archive.namelist():
                raise MediaError(f"EPUB is missing META-INF/container.xml: {path}")
    except MediaError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise MediaError(f"cannot parse EPUB {path}: {error}") from error


def _check_mobi(path: Path) -> None:
    try:
        with path.open("rb") as stream:
            header = stream.read(78)
            if len(header) < 78 or header[60:68] != b"BOOKMOBI":
                raise MediaError(f"file does not have a MOBI PalmDB signature: {path}")
            record_count = int.from_bytes(header[76:78], byteorder="big")
            if record_count < 1:
                raise MediaError(f"MOBI contains no PalmDB records: {path}")
            record_table = stream.read(record_count * 8 + 2)
            if len(record_table) != record_count * 8 + 2:
                raise MediaError(f"MOBI has a truncated PalmDB record table: {path}")
            first_offset = int.from_bytes(record_table[:4], byteorder="big")
            if first_offset < 78 + record_count * 8 + 2:
                raise MediaError(f"MOBI has an invalid first record offset: {path}")
            if first_offset >= path.stat().st_size:
                raise MediaError(f"MOBI first record points beyond the file: {path}")
    except MediaError:
        raise
    except OSError as error:
        raise MediaError(f"cannot read MOBI {path}: {error}") from error


def validate_media(path: Path) -> None:
    extension = path.suffix.casefold()
    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise MediaError(
            f"unsupported library format {extension or '<none>'}; use {supported}"
        )
    if extension == ".pdf":
        _check_pdf(path)
    elif extension == ".epub":
        _check_epub(path)
    else:
        _check_mobi(path)
