# Working on stalemd

- Code lives in `src/stalemd/`: `src/stalemd/extract.py` finds references, `src/stalemd/checks.py` checks them, `src/stalemd/cli.py` prints results.
- Run the tests with `python -m pytest -q` (stdlib only at runtime; pytest is the only dev dependency).
- Try it on the demo with `python -m stalemd --root examples/demo-repo` from inside `src/`, or `pip install .` first.
- The demo's expected output is asserted in `tests/test_cli.py`; update both together.
- No runtime dependencies. Keep it Python 3.9 compatible.
