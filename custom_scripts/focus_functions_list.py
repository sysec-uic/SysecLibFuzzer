## given a file (crash_log.txt)
## extract all the function names from the crash log
## and return them as a list and print it in the following format:
## focus_functions="function1", "function2", "function3"... 
## also print the count of focus functions
## finally, since some crash logs has too many sections, please
## allow me to pass what section I want (1,2,3...) as an argument to the script
## usage: python foucs_functions_list.py crash_log.txt 2
## finally, skip llvm functions (functions that start with 'llvm::') and run
## time functions, and fuzzers speically functions (functions that start with 'fuzzer::')

## here's a sample crash log:



import sys
import re

STACK_LINE_RE = re.compile(r"^\s*#\d+\s+.+?\s+in\s+(.+)$")


def split_sections(lines):
    sections = []
    current = []
    for line in lines:
        if STACK_LINE_RE.match(line):
            current.append(line.rstrip("\n"))
        else:
            if current:
                sections.append(current)
                current = []
    if current:
        sections.append(current)
    return sections


def parse_symbol_and_path(line):
    match = STACK_LINE_RE.match(line)
    if not match:
        return None, None
    rest = match.group(1).strip()
    name_part = rest
    path_part = None

    if " /" in rest:
        name_part, path_part = rest.split(" /", 1)
        path_part = "/" + path_part.strip()
    elif " (" in rest:
        name_part, path_part = rest.split(" (", 1)
        path_part = path_part.strip()

    if "(" in name_part:
        name_part = name_part.split("(", 1)[0].strip()
    name_part = name_part.strip()

    return name_part, path_part


def is_excluded(name, path_part):
    if not name:
        return True
    if name.startswith("llvm::"):
        return True
    if name.startswith("fuzzer::"):
        return True
    if name == "LLVMFuzzerTestOneInput":
        return True
    if name.startswith("__") or name == "_start":
        return True
    if name == "main" and path_part and "compiler-rt/lib/fuzzer" in path_part:
        return True
    if path_part:
        if "compiler-rt/lib/fuzzer" in path_part:
            return True
        if "compiler-rt/lib/asan" in path_part:
            return True
        if "/lib/" in path_part and (
            "libc.so" in path_part
            or "libstdc++" in path_part
            or "libgcc" in path_part
        ):
            return True
    return False


def collect_focus_functions(section_lines):
    seen = set()
    ordered = []
    for line in section_lines:
        name, path_part = parse_symbol_and_path(line)
        if is_excluded(name, path_part):
            continue
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def main():
    if len(sys.argv) < 2:
        print("usage: python foucs_functions_list.py crash_log.txt [section]")
        return 1

    crash_log_path = sys.argv[1]
    section_index = 1
    if len(sys.argv) >= 3:
        try:
            section_index = int(sys.argv[2])
        except ValueError:
            print("section must be an integer (1, 2, 3, ...)")
            return 1

    with open(crash_log_path, "r", errors="ignore") as crash_log:
        lines = crash_log.readlines()

    sections = split_sections(lines)
    if not sections:
        print("no stack sections found")
        return 1

    if section_index < 1 or section_index > len(sections):
        print(f"section {section_index} out of range (1-{len(sections)})")
        return 1

    focus_functions = collect_focus_functions(sections[section_index - 1])
    if focus_functions:
        formatted = ", ".join(f"\"{name}\"" for name in focus_functions)
        print(f"focus_functions={formatted}")
    else:
        print("focus_functions=")

    print(f"focus_functions_count={len(focus_functions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
