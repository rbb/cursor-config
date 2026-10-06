#!/usr/bin/env python3
"""Flag Python functions where a name is both loaded and bound locally.

Binding (assignment, augmented assignment, delete, for/as targets, etc.)
makes a name local for the entire function. Any load of that name may raise
UnboundLocalError unless the name is a parameter or declared global/nonlocal.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    func: str
    name: str
    message: str

    def format(self) -> str:
        return (
            f"{self.path}:{self.line}: load-and-bind: "
            f"in `{self.func}`, name `{self.name}` is loaded and bound in the "
            f"same scope — {self.message}"
        )


def _arg_names(node: ast.arguments) -> set[str]:
    names: set[str] = set()
    for arg in node.args:
        names.add(arg.arg)
    for arg in node.kwonlyargs:
        names.add(arg.arg)
    if node.vararg:
        names.add(node.vararg.arg)
    if node.kwarg:
        names.add(node.kwarg.arg)
    for arg in node.posonlyargs:
        names.add(arg.arg)
    return names


def _collect_global_nonlocal(body: list[ast.stmt]) -> tuple[set[str], set[str]]:
    global_names: set[str] = set()
    nonlocal_names: set[str] = set()
    for stmt in body:
        if isinstance(stmt, ast.Global):
            global_names.update(stmt.names)
        elif isinstance(stmt, ast.Nonlocal):
            nonlocal_names.update(stmt.names)
    return global_names, nonlocal_names


class _NameUseVisitor(ast.NodeVisitor):
    """Collect loads and stores for names in one function body (no nested defs)."""

    def __init__(self) -> None:
        self.loads: set[str] = set()
        self.stores: set[str] = set()
        self.first_load_line: dict[str, int] = {}
        self.first_store_line: dict[str, int] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_comprehension(self, node: ast.comprehension) -> None:
        if isinstance(node.target, ast.Name):
            self._record_store(node.target.id, node.target.lineno)
        self.visit(node.iter)
        for if_clause in node.ifs:
            self.visit(if_clause)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self._record_load(node.id, node.lineno)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self._record_store(node.id, node.lineno)

    def _record_load(self, name: str, line: int) -> None:
        self.loads.add(name)
        self.first_load_line.setdefault(name, line)

    def _record_store(self, name: str, line: int) -> None:
        self.stores.add(name)
        self.first_store_line.setdefault(name, line)


def _check_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef, path: Path
) -> list[Finding]:
    global_names, nonlocal_names = _collect_global_nonlocal(node.body)
    params = _arg_names(node.args)
    visitor = _NameUseVisitor()
    for stmt in node.body:
        visitor.visit(stmt)

    findings: list[Finding] = []
    bound_and_loaded = (visitor.loads & visitor.stores) - params
    bound_and_loaded -= global_names
    bound_and_loaded -= nonlocal_names

    qual = node.name
    for name in sorted(bound_and_loaded):
        load_line = visitor.first_load_line.get(name, node.lineno)
        store_line = visitor.first_store_line.get(name, node.lineno)
        if load_line <= store_line:
            msg = (
                "load may run before local binding (UnboundLocalError). "
                "Use a different local name, `global`, `nonlocal`, or mutate "
                "without rebinding."
            )
        else:
            msg = (
                "name is local due to binding elsewhere in this function; "
                "verify loads only run after assignment."
            )
        findings.append(
            Finding(
                path=path,
                line=load_line,
                func=qual,
                name=name,
                message=msg,
            )
        )
    return findings


class _FunctionScanner(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.findings: list[Finding] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.findings.extend(_check_function(node, self.path))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.findings.extend(_check_function(node, self.path))
        self.generic_visit(node)


def check_file(path: Path) -> list[Finding]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"{path}:0: error: {exc}", file=sys.stderr)
        return []

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        print(f"{path}:{exc.lineno or 0}: syntax: {exc.msg}", file=sys.stderr)
        return []

    scanner = _FunctionScanner(path)
    scanner.visit(tree)
    return scanner.findings


def iter_py_files(targets: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for target in targets:
        if target.is_file() and target.suffix == ".py":
            files.append(target)
        elif target.is_dir():
            files.extend(sorted(target.rglob("*.py")))
    return files


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "Usage: check_scoping.py <file-or-dir> [...]",
            file=sys.stderr,
        )
        return 2

    paths = [Path(p).resolve() for p in argv[1:]]
    all_findings: list[Finding] = []
    for py_file in iter_py_files(paths):
        all_findings.extend(check_file(py_file))

    for finding in sorted(all_findings, key=lambda f: (str(f.path), f.line, f.name)):
        print(finding.format())

    return 1 if all_findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
