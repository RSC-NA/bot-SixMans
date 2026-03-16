import struct


def get_emoji(value):
    try:
        if isinstance(value, int):
            return struct.pack("<I", value).decode("utf-32le")
        if isinstance(value, str):
            return struct.pack("<I", int(value, base=16)).decode("utf-32le")  # i == react_hex
    except (ValueError, TypeError):
        return None
