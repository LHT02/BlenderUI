# SPDX-License-Identifier: GPL-2.0-or-later
"""Find `_template_*` helpers in `keymap_data/*.py` that nothing can reach.

These files define a large family of `_template_*` functions that build lists of
keymap items; the keymap definitions call the top of each family and the rest are
internal helpers. When BLUI deletes a module, the keymap data that named the
helper goes with it - but the helper *definition* is easy to leave behind,
because nothing about deleting a caller makes a definition look wrong. This scan
finds those leftovers.

It found twelve on 2026-09-16 (242 lines, since deleted): see "Dead
`_template_*` helpers in the keymap data" in `blui/README.md` for the list and
the `git log -S` evidence that their callers were removed by BLUI's own module
deletions rather than never having existed.

Why a transitive closure and not a grep. Two ways a flat count goes wrong:

1. **Same name, different file.** `_template_items_tool_select` and friends are
   defined in *both* preset data files and are live in `blender_default.py`,
   dead in `industry_compatible_data.py`. Counting occurrences per name reports
   the name, not the definition.
2. **Dead helpers call dead helpers.** `_template_items_tool_select_actions_simple`
   is reached only from its dead siblings, so it looks referenced until you
   decide its only caller is itself unreachable. A single pass under-reports.

So the reachability is a closure: a helper is live if something outside every
`_template_*` definition names it, or if a live helper names it. Everything else
is dead - it cannot contribute a keymap item, and if it names operators BLUI has
deleted it is a trap for the next reader.

Run::

    python source\\blui\\tools\\scan_dead_keymap_helpers.py [--check]

With no arguments it prints every dead helper and exits 0. With `--check` it
exits 1 if anything dead is found, so a later round can use it as a gate.

This only reads. It needs a plain Python 3, not BLUI.
"""
import ast
import os
import sys

DEFAULT_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    os.pardir, os.pardir,  # ...\source\blui\tools -> ...\source
    "scripts", "presets", "keyconfig", "keymap_data",
))


def helper_refs_in(node):
    """Names of `_template*` identifiers appearing anywhere under `node`."""
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id.startswith("_template"):
            names.add(sub.id)
    # ast.Name misses nothing here: helpers are called as plain names, and
    # `*_template_x(...)` is still a Name inside a Starred node.
    return names


def scan_file(path):
    """Return (dead, total_dead_lines, n_defs) for one keymap data file."""
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)

    defs = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_template"):
            defs[node.name] = node

    # Direct edges: helper -> helpers it names inside its own body.
    edges = {name: helper_refs_in(node) for name, node in defs.items()}

    # References from outside every helper definition.
    outside = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_template"):
            continue
        outside |= helper_refs_in(node)

    live = set(outside)
    changed = True
    while changed:
        changed = False
        for name in list(live):
            for callee in edges.get(name, ()):
                if callee not in live:
                    live.add(callee)
                    changed = True

    dead = sorted(set(defs) - live)
    total = sum(defs[name].end_lineno - defs[name].lineno + 1 for name in dead)
    return [(name, defs[name]) for name in dead], total, len(defs)


def main(argv):
    check_only = "--check" in argv
    directory = DEFAULT_DIR
    for arg in argv[1:]:
        if not arg.startswith("--"):
            directory = arg

    if not os.path.isdir(directory):
        print("scan_dead_keymap_helpers: no such directory: %s" % directory)
        return 2

    total_dead = 0
    for fn in sorted(os.listdir(directory)):
        if not fn.endswith(".py"):
            continue
        path = os.path.join(directory, fn)
        dead, dead_lines, n_defs = scan_file(path)
        print("=== %s ===" % fn)
        print("  helpers defined: %d   live: %d   dead: %d"
              % (n_defs, n_defs - len(dead), len(dead)))
        for name, node in dead:
            n = node.end_lineno - node.lineno + 1
            print("    DEAD %-48s line %5d  %4d lines" % (name, node.lineno, n))
        print("  dead total: %d lines" % dead_lines)
        print()
        total_dead += len(dead)

    if check_only:
        if total_dead:
            print("scan_dead_keymap_helpers: FAILED (%d dead helper%s)"
                  % (total_dead, "" if total_dead == 1 else "s"))
            return 1
        print("scan_dead_keymap_helpers: OK, no unreachable _template_* helpers")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
