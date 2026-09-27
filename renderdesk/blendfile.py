"""Read a .blend header without opening Blender.

Blender refuses nothing when asked to open a file from a newer release, it just
loads it with silent data loss. So the version gate has to happen before Blender
is ever started, and before a GPU is ever billed.

Two header layouts exist and both are handled:

  old (<= 4.x)  b"BLENDER" + pointer char + endian char + 3 digits   ("BLENDER-v405")
  new (5.x+)    b"BLENDER" + 2-digit header size + pointer char
                + 2-digit format version + marker + 4 digits         ("BLENDER17-01v0501")

In both the digits are major*100 + minor, so 4.5 -> 405 and 5.1 -> 501.
The whole file may be gzip or zstd compressed, in which case the header sits
inside the compressed stream.
"""
import gzip
import io

MAGIC = b"BLENDER"


def _head(path, size=64):
    with open(path, "rb") as fh:
        raw = fh.read(max(size, 4096))
    if raw.startswith(MAGIC):
        return raw
    if raw.startswith(b"\x1f\x8b"):
        with gzip.open(io.BytesIO(raw)) as gz:
            return gz.read(size)
    if raw.startswith(b"\x28\xb5\x2f\xfd"):
        try:
            from compression import zstd
        except ImportError:
            try:
                import zstandard

                return zstandard.ZstdDecompressor().decompressobj().decompress(raw, size)
            except ImportError:
                raise ValueError("file is zstd-compressed and no zstd decoder is available")
        return zstd.ZstdDecompressor().decompress(raw, max_length=size)
    raise ValueError("not a .blend file")


def version(path):
    """(major, minor) of the Blender that saved this file."""
    head = _head(path)
    if not head.startswith(MAGIC):
        raise ValueError("not a .blend file")
    size_field = head[7:9].decode("ascii", "replace")
    if size_field.isdigit():
        header_size = int(size_field)
        digits = head[header_size - 4:header_size].decode("ascii", "replace")
    else:
        digits = head[9:12].decode("ascii", "replace")
    if not digits.isdigit():
        raise ValueError("unreadable .blend version header")
    number = int(digits)
    return number // 100, number % 100


def parse_version(text):
    """'5.1.2' or '4.5' -> (5, 1)."""
    bits = str(text).split(".")
    return int(bits[0]), int(bits[1]) if len(bits) > 1 else 0
