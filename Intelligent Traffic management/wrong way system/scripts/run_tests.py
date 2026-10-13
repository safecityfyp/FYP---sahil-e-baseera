"""Minimal test runner for environments without pytest: python scripts/run_tests.py [-k substr]"""
import inspect
import os
import sys
import tempfile
import time
import traceback
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
if "pytest" not in sys.modules:   # tiny shim so the test module imports
    shim = types.ModuleType("pytest")

    class _Mark:
        def parametrize(self, name, values):
            def deco(fn):
                fn._params = (name, values)
                return fn
            return deco
    shim.mark = _Mark()
    sys.modules["pytest"] = shim

import pathlib  # noqa: E402
import tests.test_system as T  # noqa: E402

k = sys.argv[sys.argv.index("-k") + 1] if "-k" in sys.argv else ""
failed = 0
for name, fn in inspect.getmembers(T, inspect.isfunction):
    if not name.startswith("test_") or k not in name:
        continue
    cases = [(p,) for p in fn._params[1]] if hasattr(fn, "_params") else [()]
    for args in cases:
        kw = {}
        if "tmp_path" in inspect.signature(fn).parameters:
            kw["tmp_path"] = pathlib.Path(tempfile.mkdtemp())
        t0 = time.time()
        try:
            fn(*args, **kw)
            print(f"PASS {name}{list(args) if args else ''} ({time.time() - t0:.1f}s)")
        except Exception:
            failed += 1
            print(f"FAIL {name}{list(args) if args else ''}")
            traceback.print_exc()
print("FAILED" if failed else "ALL PASSED", failed)
sys.exit(1 if failed else 0)
