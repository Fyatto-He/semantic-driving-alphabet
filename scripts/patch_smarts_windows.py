"""Make the pip-installed SMARTS 2.0.1 importable on native Windows.

SMARTS only supports Linux/macOS officially. Each entry below replaces one
Unix-only snippet in site-packages. The script is idempotent: run it once after
`pip install`, and again after any reinstall.

    .venv\\Scripts\\python scripts\\patch_smarts_windows.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# (module file relative to the smarts package, original snippet, replacement)
PATCHES = [
    (
        "core/utils/core_logging.py",
        # `CDLL(None)` (= "this process's libc") does not exist on Windows.
        'libc = ctypes.CDLL(None)\n'
        'try:\n'
        '    c_stderr = ctypes.c_void_p.in_dll(libc, "stderr")\n'
        '    c_stdout = ctypes.c_void_p.in_dll(libc, "stdout")\n'
        'except:\n'
        '    # macOS\n'
        '    c_stderr = ctypes.c_void_p.in_dll(libc, "__stderrp")\n'
        '    c_stdout = ctypes.c_void_p.in_dll(libc, "__stdoutp")\n',
        'if os.name == "nt":\n'
        '    # Windows: fflush(NULL) flushes every C stream, so no stream handles are needed.\n'
        '    libc = ctypes.CDLL("ucrtbase")\n'
        '    c_stderr = c_stdout = None\n'
        'else:\n'
        '    libc = ctypes.CDLL(None)\n'
        '    try:\n'
        '        c_stderr = ctypes.c_void_p.in_dll(libc, "stderr")\n'
        '        c_stdout = ctypes.c_void_p.in_dll(libc, "stdout")\n'
        '    except:\n'
        '        # macOS\n'
        '        c_stderr = ctypes.c_void_p.in_dll(libc, "__stderrp")\n'
        '        c_stdout = ctypes.c_void_p.in_dll(libc, "__stdoutp")\n',
    ),
    (
        "core/utils/resources.py",
        # Windows cannot reopen a NamedTemporaryFile that is still open.
        '            c.flush()\n'
        '            with open(c.name, "r", encoding="utf-8") as file:\n'
        '                out_config = yaml.safe_load(file)\n',
        '            c.flush()\n'
        '            out_config = yaml.safe_load(conf)\n',
    ),
]


def main() -> int:
    spec = importlib.util.find_spec("smarts")
    if spec is None or not spec.submodule_search_locations:
        print("smarts is not installed in this environment")
        return 1
    pkg = Path(list(spec.submodule_search_locations)[0])
    status = 0
    for rel, old, new in PATCHES:
        path = pkg / rel
        text = path.read_text(encoding="utf-8")
        if new in text:
            print(f"already patched: {rel}")
        elif old in text:
            path.write_text(text.replace(old, new), encoding="utf-8")
            print(f"patched:         {rel}")
        else:
            print(f"NOT APPLIED (source differs from SMARTS 2.0.1): {rel}")
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
