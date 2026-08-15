"""Lightweight SNMP v1 GET client using Python stdlib only (no external deps).

Sends a SNMPv1 GET request over UDP, parses the response, returns the value.

Bare-bones BER encoding/decoding — just enough for simple OID GET queries.
"""

from __future__ import annotations

import socket
import struct
from typing import Tuple


def encode_length(length: int) -> bytes:
    """BER length encoding: short form or long form."""
    if length < 128:
        return bytes([length])
    # Long form: first byte = 0x80 | num_bytes, followed by big-endian bytes
    result = bytearray()
    while length > 0:
        result.insert(0, length & 0xFF)
        length >>= 8
    result.insert(0, 0x80 | len(result))
    return bytes(result)


def encode_integer(value: int) -> bytes:
    """BER INTEGER encoding (universal tag 0x02)."""
    if value == 0:
        return b'\x02\x01\x00'
    result = bytearray()
    v = value
    while v > 0:
        result.insert(0, v & 0xFF)
        v >>= 8
    # Ensure positive: if high bit set, prepend 0x00
    if result[0] & 0x80:
        result.insert(0, 0x00)
    return bytes([0x02]) + encode_length(len(result)) + bytes(result)


def encode_octet_string(data: bytes) -> bytes:
    """BER OCTET STRING encoding (universal tag 0x04)."""
    return b'\x04' + encode_length(len(data)) + data


def encode_oid(oid: str) -> bytes:
    """Encode dotted OID string to BER OBJECT IDENTIFIER (tag 0x06)."""
    parts = [int(x) for x in oid.split('.')]
    # First two sub-IDs combined: 40 * part1 + part2
    encoded = bytearray([40 * parts[0] + parts[1]])
    for val in parts[2:]:
        # Base-128 encoding, high bit = continuation
        sub = bytearray()
        while True:
            sub.insert(0, val & 0x7F)
            val >>= 7
            if val == 0:
                break
        # Set high bit on all but last byte
        for i in range(len(sub) - 1):
            sub[i] |= 0x80
        encoded.extend(sub)
    return b'\x06' + encode_length(len(encoded)) + bytes(encoded)


def encode_null() -> bytes:
    """BER NULL encoding (tag 0x05)."""
    return b'\x05\x00'


def encode_varbind(oid: str) -> bytes:
    """Encode a single varbind: SEQUENCE { OID, NULL }."""
    body = encode_oid(oid) + encode_null()
    return b'\x30' + encode_length(len(body)) + body


def encode_get_request(oid: str, community: str = "public", request_id: int = 1) -> bytes:
    """Build a complete SNMPv1 GET request PDU."""
    # PDU body
    pdu_body = (
        encode_integer(request_id)
        + encode_integer(0)  # error
        + encode_integer(0)  # error-index
        + b'\x30' + encode_length(len(encode_varbind(oid))) + encode_varbind(oid)
    )
    pdu = b'\xA0' + encode_length(len(pdu_body)) + pdu_body

    # Whole message
    msg_body = (
        encode_integer(0)  # version: SNMPv1
        + encode_octet_string(community.encode('ascii'))
        + pdu
    )
    msg = b'\x30' + encode_length(len(msg_body)) + msg_body
    return msg


# ── DECODING ────────────────────────────────────────────

def _decode_ber(data: bytes, offset: int = 0) -> tuple[int, int, int]:  # (tag, length, value_start)
    """Decode BER tag + length at offset. Returns (tag, length, content_offset)."""
    tag = data[offset]
    offset += 1
    first_len_byte = data[offset]
    offset += 1
    if first_len_byte < 128:
        length = first_len_byte
    else:
        num_bytes = first_len_byte & 0x7F
        length = 0
        for _ in range(num_bytes):
            length = (length << 8) | data[offset]
            offset += 1
    return tag, length, offset


def _decode_integer(data: bytes, length: int, offset: int) -> int:
    """Decode a BER INTEGER value."""
    value = 0
    for i in range(length):
        value = (value << 8) | data[offset + i]
    # Handle two's complement negative
    if data[offset] & 0x80:
        value -= (1 << (length * 8))
    return value


def _decode_oid(data: bytes, length: int, offset: int) -> str:
    """Decode BER OBJECT IDENTIFIER to dotted string."""
    end = offset + length
    parts = []
    # First byte = 40*x + y
    parts.append(data[offset] // 40)
    parts.append(data[offset] % 40)
    offset += 1
    while offset < end:
        val = 0
        while True:
            byte = data[offset]
            offset += 1
            val = (val << 7) | (byte & 0x7F)
            if not (byte & 0x80):
                break
        parts.append(val)
    return '.'.join(str(p) for p in parts)


def _decode_value(data: bytes, length: int, offset: int) -> tuple[int, str | int]:
    """Decode a BER value (tag determined by looking at offset-1-L). Returns (end_offset, value)."""
    # We need the tag, but it was consumed earlier. Use what we have.
    # For our purposes, values are either INTEGER (02), OCTET STRING (04),
    # OID (06), NULL (05), or counter/gauge (41/42).
    # Actually, the value starts at offset, but we need the tag which is just before.
    # Let's change approach: decode_value needs tag + length + data.
    return offset + length, "?"  # placeholder


def snmp_get(host: str, oid: str, community: str = "public",
             port: int = 161, timeout: float = 3) -> str | None:
    """Send an SNMPv1 GET request and return the response value as a string.

    Returns None on any error (timeout, parse failure, etc.).
    """
    sock = None
    try:
        request = encode_get_request(oid, community)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(request, (host, port))

        response, _ = sock.recvfrom(4096)

        # Parse the SNMP response manually
        # Step 1: skip outer SEQUENCE (tag 0x30)
        outer_tag, outer_len, off = _decode_ber(response, 0)
        if outer_tag != 0x30:
            return None

        # Step 2: version (INTEGER)
        ver_tag, ver_len, off = _decode_ber(response, off)
        if ver_tag != 0x02:
            return None
        off += ver_len  # skip version value

        # Step 3: community (OCTET STRING)
        comm_tag, comm_len, off = _decode_ber(response, off)
        if comm_tag != 0x04:
            return None
        off += comm_len  # skip community value

        # Step 4: GET-RESPONSE PDU (tag 0xA2)
        pdu_tag, pdu_len, pdu_start = _decode_ber(response, off)
        if pdu_tag != 0xA2:
            return None
        off = pdu_start

        # Step 5: request-id (INTEGER)
        rid_tag, rid_len, off = _decode_ber(response, off)
        if rid_tag != 0x02:
            return None
        off += rid_len

        # Step 6: error-status (INTEGER)
        es_tag, es_len, off = _decode_ber(response, off)
        if es_tag != 0x02:
            return None
        off += es_len

        # Step 7: error-index (INTEGER)
        ei_tag, ei_len, off = _decode_ber(response, off)
        if ei_tag != 0x02:
            return None
        off += ei_len

        # Step 8: varbind-list (SEQUENCE)
        vb_tag, vb_len, off = _decode_ber(response, off)
        if vb_tag != 0x30:
            return None
        vb_end = off + vb_len

        # Step 9: varbind (SEQUENCE)
        vb2_tag, vb2_len, off = _decode_ber(response, off)
        if vb2_tag != 0x30:
            return None

        # Step 10: OID
        oid_tag, oid_len, off = _decode_ber(response, off)
        if oid_tag != 0x06:
            return None
        off += oid_len  # skip OID bytes

        # Step 11: value
        val_tag, val_len, off = _decode_ber(response, off)
        value_bytes = response[off:off + val_len]

        # Decode based on tag
        if val_tag == 0x02:  # INTEGER
            return str(_decode_integer(value_bytes, val_len, 0))
        elif val_tag == 0x04:  # OCTET STRING
            return value_bytes.decode('ascii', errors='replace')
        elif val_tag == 0x06:  # OID
            return _decode_oid(value_bytes, val_len, 0)
        elif val_tag in (0x41, 0x42):  # Counter, Gauge
            return str(_decode_integer(value_bytes, val_len, 0))
        elif val_tag == 0x05:  # NULL
            return "0"
        elif val_tag == 0x43:  # TimeTicks
            return str(_decode_integer(value_bytes, val_len, 0))
        else:
            # Fallback: try as integer, otherwise hex
            try:
                return str(_decode_integer(value_bytes, val_len, 0))
            except Exception:
                return value_bytes.hex()

    except (socket.timeout, OSError, struct.error, IndexError, ValueError) as err:
        # Expected: printer unreachable, SNMP not supported, etc.
        pass
    except Exception:
        pass
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass

    return None
