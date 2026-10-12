"""Static safety validator for free-form part bodies (AST, before anything reaches Fusion).

The body is code Claude wrote; the prelude around it is ours. The body may only build geometry in the component it
is given. Allowed imports: adsk(.core/.fusion), math, json, traceback, re. Rejected: any other import, file and
process access (open, os, subprocess, ...), dynamic code (exec, eval, compile, __import__), introspection escapes
(dunder / underscore names), document-level operations (save, close, documents, activeDocument, Application),
reaching outside the part (rootComponent, parentDesign, ...) and deleteMe (nothing outside the part may be deleted;
inside it, cut/join operations replace deletion). The body must define build(part) and must not redefine the
prelude's names.
"""
from __future__ import annotations

import ast

ALLOWED_IMPORTS = {"adsk", "adsk.core", "adsk.fusion", "math", "json", "traceback", "re"}
FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr",
                   "setattr", "delattr", "input", "breakpoint", "exit", "quit", "memoryview", "os", "sys",
                   "subprocess", "shutil", "socket", "pathlib", "importlib", "builtins", "ctypes", "CFG"}
FORBIDDEN_ATTRS = {"save", "saveAs", "close", "deleteMe", "documents", "activeDocument", "activeProduct",
                   "rootComponent", "parentDesign", "userInterface", "Application", "terminate",
                   "executeTextCommand", "scripts", "addIns", "importManager", "exportManager", "dataFile",
                   "dataProject", "data", "fireCustomEvent", "open", "userParameters", "allParameters",
                   "materialLibraries", "preferences", "attributes", "snapshots", "transform", "transform2",
                   "system", "popen", "remove", "unlink", "rmdir"}
RESERVED = {"run", "build_result", "emit", "mm", "pt", "val", "Part", "begin_part", "finish_part", "ensure_anchor",
            "adsk", "json", "math", "re", "traceback", "base64", "sys"}
MAX_BODY_CHARS = 30000


class UnsafeScript(ValueError):
    """The body violates the script contract; .problems lists each violation with its line."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def check_body(body: str) -> list[str]:
    """Problems found in the body (empty list = acceptable)."""
    if len(body) > MAX_BODY_CHARS:
        return [f"body too long ({len(body)} > {MAX_BODY_CHARS} characters)"]
    try:
        tree = ast.parse(body)
    except SyntaxError as e:
        return [f"line {e.lineno}: SyntaxError: {e.msg}"]
    problems: list[str] = []

    def bad(node, msg):
        problems.append(f"line {getattr(node, 'lineno', '?')}: {msg}")

    has_build = False
    for node in tree.body:                                   # top level: imports, functions, constant assignments
        if isinstance(node, ast.FunctionDef):
            if node.name == "build":
                has_build = True
                if len(node.args.args) != 1:
                    bad(node, "build must take exactly one argument: build(part)")
            elif node.name in RESERVED:
                bad(node, f"must not redefine prelude name '{node.name}'")
        elif isinstance(node, (ast.Import, ast.ImportFrom, ast.Expr)):
            pass                                             # imports are checked below; docstrings are fine
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name) and n.id in RESERVED:
                        bad(node, f"must not redefine prelude name '{n.id}'")
        else:
            bad(node, f"top level may only hold imports, functions and constants (found {type(node).__name__})")
    if not has_build:
        problems.append("body must define build(part)")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name not in ALLOWED_IMPORTS:
                    bad(node, f"import '{a.name}' not allowed")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "") not in ALLOWED_IMPORTS or node.level:
                bad(node, f"import from '{node.module}' not allowed")
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES:
                bad(node, f"name '{node.id}' not allowed")
            elif node.id.startswith("_"):
                bad(node, f"underscore name '{node.id}' not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_ATTRS:
                bad(node, f"attribute '.{node.attr}' not allowed (outside the part / document-level)")
            elif node.attr.startswith("_"):
                bad(node, f"underscore attribute '.{node.attr}' not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bad(node, "global/nonlocal not allowed")
        elif isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom, ast.Lambda)):
            if isinstance(node, ast.Lambda):
                continue                                     # lambdas are harmless
            bad(node, f"{type(node).__name__} not allowed")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "@@RESULT@@" in node.value:
            bad(node, "the body must not print result markers (the prelude emits the result)")
    return problems


def validate_body(body: str) -> None:
    problems = check_body(body)
    if problems:
        raise UnsafeScript(problems)
