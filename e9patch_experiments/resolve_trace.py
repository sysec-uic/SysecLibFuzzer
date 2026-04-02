#!/usr/bin/env python3
"""Resolve e9patch hook trace addresses to function names.

Reads the symbol table from the binary (nm) and the raw trace log,
computes the ASLR base offset, and prints the resolved trace.

Usage: python3 resolve_trace.py <binary> <trace.log>
"""
import subprocess
import sys
import re


def load_symbols(binary):
    syms = {}
    # Regular symbols
    out = subprocess.check_output(["nm", binary], text=True, stderr=subprocess.DEVNULL)
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            try:
                offset = int(parts[0], 16)
            except ValueError:
                continue
            syms[offset] = parts[2]
    # PLT entries from objdump
    try:
        out = subprocess.check_output(
            ["objdump", "-d", "-j", ".plt.sec", binary],
            text=True, stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        try:
            out = subprocess.check_output(
                ["objdump", "-d", "-j", ".plt", binary],
                text=True, stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            out = ""
    for m in re.finditer(r"^([0-9a-f]+)\s+<(.+?)@plt>:", out, re.MULTILINE):
        offset = int(m.group(1), 16)
        syms[offset] = m.group(2) + "@plt"
    return syms


def find_base(trace_addrs, syms):
    sym_offsets = set(syms.keys())
    for addr in trace_addrs:
        for off in sym_offsets:
            candidate = addr - off
            if candidate <= 0 or candidate % 0x1000 != 0:
                continue
            hits = sum(1 for a in trace_addrs if (a - candidate) in sym_offsets)
            if hits >= 2:
                return candidate
    return None


def main():
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <binary> <trace.log>")
        return 1

    syms = load_symbols(sys.argv[1])

    entries = []
    with open(sys.argv[2]) as f:
        for line in f:
            m = re.match(
                r"TRACE seq=(\d+) target=0x([0-9a-f]+) call_id=(\d+)", line
            )
            if m:
                entries.append(
                    (int(m.group(1)), int(m.group(2), 16), int(m.group(3)))
                )

    if not entries:
        print("no trace entries found")
        return 1

    addrs = list({addr for _, addr, _ in entries})
    base = find_base(addrs, syms)
    if base is None:
        print("could not determine base address")
        return 1

    for seq, addr, call_id in entries:
        offset = addr - base
        name = syms.get(offset, f"<0x{offset:x}>")
        print(f"seq={seq:<4d} {name:<30s} call_id={call_id}")


if __name__ == "__main__":
    sys.exit(main() or 0)
