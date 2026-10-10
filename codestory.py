#!/usr/bin/env python3
"""
codestory - turn a Python program into an animated story of how it works.

Commands
  scan  ENTRY [options]                 Read the code without running it.
  run   ENTRY [options] [-- ARGS ...]   Run the program under the tracer (safe mode on by default).
  build STORYBOARD [-o story.html]      Put a storyboard into the player as one shareable HTML file.

Examples
  python codestory.py scan main.py
  python codestory.py run main.py -- --date 2026-09-01 --input data/today.csv
  python codestory.py run main.py --live -- --date 2026-09-01
  python codestory.py build storyboard.json -o story.html
  python codestory.py run -m mypackage.cli -- --verbose

Standard library only. Run it with the same Python environment your project uses
(for example, with your virtualenv activated) so that your project's imports resolve.
"""

import argparse
import ast
import builtins
import datetime as _dt
import importlib.abc
import importlib.util
import io
import json
import os
import re
import runpy
import shutil
import sys
import sysconfig
import tempfile
import threading
import time
import traceback

VERSION = "0.3.0"
BUNDLE_SCHEMA = "codestory.bundle/2"
STORYBOARD_SCHEMA = "codestory.storyboard/1"

HERE = os.path.dirname(os.path.abspath(__file__))
SELF_FILE = os.path.abspath(__file__)

EXCLUDED_DIR_NAMES = {
    ".venv", "venv", "env", ".env", "site-packages", "dist-packages", "node_modules",
    ".git", "__pycache__", ".tox", ".nox", "build", "dist", ".mypy_cache", ".pytest_cache",
}

SECRET_NAME = re.compile(r"(?i)(pass(word|wd)?|pwd|secret|token|api[_-]?key|apikey|auth|credential|private[_-]?key|dsn|conn(ection)?[_-]?str)")
SECRET_VALUE_PATTERNS = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 ***"),
    (re.compile(r"(://[^/\s:@]+:)[^@\s/]+@"), r"\1***@"),
    (re.compile(r"\b(sk|pk|rk|ghp|gho|ghs|xox[abpr]|AKIA|ASIA|AIza)[-_A-Za-z0-9]{12,}"), "***"),
    (re.compile(r"(?i)([?&](?:key|token|apikey|api_key|access_token|secret|password|sig|signature)=)[^&\s]+"), r"\1***"),
]


def log(msg):
    print(f"[codestory] {msg}", file=sys.stderr, flush=True)


def redact(text):
    if not isinstance(text, str):
        return text
    for pat, rep in SECRET_VALUE_PATTERNS:
        text = pat.sub(rep, text)
    return text


def short(text, n=120):
    text = str(text)
    return text if len(text) <= n else text[: n - 1] + "…"


def now_iso():
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


# ----------------------------------------------------------------------------
# Paths: what counts as "the project"
# ----------------------------------------------------------------------------

def _stdlib_dirs():
    dirs = set()
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        p = sysconfig.get_paths().get(key)
        if p:
            dirs.add(os.path.abspath(p))
    for p in (sys.prefix, sys.base_prefix, sys.exec_prefix):
        dirs.add(os.path.abspath(p))
    return tuple(sorted(dirs, key=len, reverse=True))


class Project:
    def __init__(self, entry=None, root=None, module=None):
        self.module = module
        if module:  # like `python -m module`: resolved from the root (default: the current folder), nothing imported
            self.root = os.path.abspath(root or os.getcwd())
            entry, self.entry_module = self._find_module(module)
        self.entry = os.path.abspath(entry)
        if not os.path.isfile(self.entry):
            raise SystemExit(f"Entry point not found: {entry}")
        self.entry_dir = os.path.dirname(self.entry)
        if module:
            self.entry_dir = self.root      # `python -m` puts the current folder first on sys.path
        elif root:
            self.root = os.path.abspath(root)
        else:
            cwd = os.path.abspath(os.getcwd())
            self.root = cwd if self.entry.startswith(cwd + os.sep) else self.entry_dir
        self.search_roots = []
        for r in (self.entry_dir, self.root):
            if r not in self.search_roots:
                self.search_roots.append(r)
        if not module:
            self.entry_module = os.path.splitext(os.path.basename(self.entry))[0]
        self._lib_dirs = _stdlib_dirs()
        self._cache = {}
        self.sandbox = None

    def _find_module(self, module):
        base = os.path.join(self.root, *module.split("."))
        if os.path.isfile(os.path.join(base, "__main__.py")):
            return os.path.join(base, "__main__.py"), module + ".__main__"
        if os.path.isfile(base + ".py"):
            return base + ".py", module
        raise SystemExit(f"Module not found: {module} (looked in {self.root}; use --root to point at the folder you run `python -m` from)")

    def label(self):
        return f"-m {self.module}" if self.module else self.rel(self.entry)

    def rel(self, path):
        try:
            return os.path.relpath(path, self.root)
        except ValueError:
            return path

    def is_project_file(self, filename):
        hit = self._cache.get(filename)
        if hit is not None:
            return hit
        ok = False
        if filename and not filename.startswith("<"):
            path = os.path.abspath(filename)
            if path != SELF_FILE and (path.startswith(self.root + os.sep) or path == self.entry):
                parts = set(os.path.relpath(path, self.root).split(os.sep)[:-1])
                ok = not (parts & EXCLUDED_DIR_NAMES)
                if ok and self.sandbox and path.startswith(self.sandbox):
                    ok = False
        self._cache[filename] = ok
        return ok

    def is_library_path(self, path):
        """Paths that belong to Python or installed packages (not user data)."""
        for d in self._lib_dirs:
            if path.startswith(d + os.sep):
                if path.startswith(self.root + os.sep) and not set(path[len(self.root) + 1:].split(os.sep)) & EXCLUDED_DIR_NAMES:
                    return False
                return True
        return False

    def module_name_for(self, path):
        path = os.path.abspath(path)
        if path == self.entry:
            return self.entry_module
        for base in self.search_roots:
            if path.startswith(base + os.sep):
                rel = os.path.relpath(path, base)
                mod = os.path.splitext(rel)[0].replace(os.sep, ".")
                if mod.endswith(".__init__"):
                    mod = mod[: -len(".__init__")]
                return mod
        return os.path.splitext(os.path.basename(path))[0]

    def resolve(self, modname):
        parts = modname.split(".")
        for base in self.search_roots:
            p = os.path.join(base, *parts)
            if os.path.isfile(p + ".py"):
                return p + ".py"
            if os.path.isfile(os.path.join(p, "__init__.py")):
                return os.path.join(p, "__init__.py")
        return None


# ----------------------------------------------------------------------------
# Static analysis
# ----------------------------------------------------------------------------

READ_CALLS = {
    "read_csv", "read_excel", "read_json", "read_parquet", "read_sql", "read_sql_query", "read_sql_table",
    "read_table", "read_feather", "read_pickle", "read_xml", "read_html", "read_fwf", "read_orc", "read_hdf",
    "load_workbook", "loadtxt", "genfromtxt", "read_text", "read_bytes", "urlopen", "fetchall", "fetchone",
    "fetchmany", "get_object", "download_file", "safe_load", "scan_csv", "scan_parquet",
}
WRITE_CALLS = {
    "to_csv", "to_excel", "to_parquet", "to_json", "to_sql", "to_pickle", "to_feather", "to_hdf", "to_orc",
    "to_xml", "write_text", "write_bytes", "savefig", "savetxt", "put_object", "upload_file", "send_message",
    "sendmail", "write_csv", "write_parquet", "commit", "dump",
}
HTTP_VERBS = {"get", "post", "put", "patch", "delete", "head", "request"}
HTTP_OWNERS = {"requests", "httpx", "session", "client", "s", "http"}
ENV_CALLS = {"getenv", "environ.get", "os.getenv", "os.environ.get", "load_dotenv"}
SQL_WRITE = re.compile(r"^\s*(insert|update|delete|merge|upsert|replace|create|drop|alter|truncate|grant|revoke|copy|call|exec|execute)\b", re.I)


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif isinstance(node, ast.Call):
        inner = dotted(node.func)
        parts.append((inner or "?") + "()")
    else:
        return None
    return ".".join(reversed(parts))


def literal_preview(node, src):
    try:
        val = ast.literal_eval(node)
        return {"value": redact(short(repr(val), 160)), "how": "literal"}
    except Exception:
        seg = ast.get_source_segment(src, node) or ""
        how = "expression"
        if re.search(r"\b(getenv|environ)\b", seg):
            how = "environment"
        elif re.search(r"\b(json\.load|yaml|toml|configparser|load_dotenv|read_text)\b", seg):
            how = "config file"
        return {"value": redact(short(seg, 160)), "how": how}


def classify_import(top, project):
    if project.resolve(top):
        return "project"
    std = getattr(sys, "stdlib_module_names", None)
    if std is not None and top in std:
        return "stdlib"
    try:
        spec = importlib.util.find_spec(top)
    except Exception:
        spec = None
    if spec is None:
        return "missing"
    origin = spec.origin or ""
    if std is None and origin in ("built-in", "frozen"):
        return "stdlib"
    stdlib_dir = sysconfig.get_paths().get("stdlib", "")
    if std is None and stdlib_dir and origin.startswith(stdlib_dir) and "site-packages" not in origin:
        return "stdlib"
    return "third_party"


class ModuleAnalyzer(ast.NodeVisitor):
    def __init__(self, project, modname, path, src):
        self.p = project
        self.mod = modname
        self.path = path
        self.src = src
        self.lines = src.splitlines()
        self.imports = []
        self.constants = []
        self.functions = {}
        self.classes = {}
        self.names = {}       # local alias -> fully qualified target ("mod:qual" or "mod")
        self.main_flow = []
        self.env_vars = set()
        self._scope = []      # stack of (kind, name)

    # -- helpers
    def qual(self, name):
        parts = []
        for kind, n in self._scope:
            parts.append(n)
            if kind == "def":
                parts.append("<locals>")
        parts.append(name)
        return ".".join(parts)

    def seg(self, node, n=160):
        text = (ast.get_source_segment(self.src, node) or "").strip()
        return short(redact(text.splitlines()[0] if text else ""), n)

    def resolve_from(self, node):
        if node.level:
            base = self.mod.split(".")
            if not self.path.endswith("__init__.py"):
                base = base[:-1]
            if node.level > 1:
                base = base[: len(base) - (node.level - 1)]
            mod = ".".join(base + ([node.module] if node.module else []))
            return mod
        return node.module or ""

    # -- imports
    def visit_Import(self, node):
        for a in node.names:
            top = a.name.split(".")[0]
            kind = classify_import(top, self.p)
            self.imports.append({"module": a.name, "names": [], "alias": a.asname, "line": node.lineno, "kind": kind,
                                 "scope": self.qual("") if self._scope else "module"})
            self.names[a.asname or top] = a.name if a.asname else top
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        mod = self.resolve_from(node)
        top = mod.split(".")[0] if mod else ""
        kind = "project" if node.level else classify_import(top, self.p) if top else "project"
        names = [a.name for a in node.names]
        self.imports.append({"module": mod, "names": names, "alias": None, "line": node.lineno, "kind": kind,
                             "scope": self.qual("") if self._scope else "module"})
        for a in node.names:
            local = a.asname or a.name
            sub = f"{mod}.{a.name}" if mod else a.name
            if kind == "project" and self.p.resolve(sub):
                self.names[local] = sub                     # imported a submodule
            else:
                self.names[local] = f"{mod}:{a.name}"       # imported a name from a module
        self.generic_visit(node)

    # -- definitions
    def _func(self, node):
        q = self.qual(node.name)
        a = node.args
        args = [x.arg for x in getattr(a, "posonlyargs", [])] + [x.arg for x in a.args]
        if a.vararg:
            args.append("*" + a.vararg.arg)
        args += [x.arg for x in a.kwonlyargs]
        if a.kwarg:
            args.append("**" + a.kwarg.arg)
        info = {
            "id": f"{self.mod}:{q}", "name": node.name, "qualname": q, "line": node.lineno,
            "end": getattr(node, "end_lineno", node.lineno), "args": args,
            "returns": self.seg(node.returns, 80) if node.returns else None,
            "doc": short(ast.get_docstring(node) or "", 300) or None,
            "decorators": [self.seg(d, 80) for d in node.decorator_list],
            "async": isinstance(node, ast.AsyncFunctionDef),
            "calls": [], "io": [], "branches": [], "loops": [], "env": [],
            "class": self._scope[-1][1] if self._scope and self._scope[-1][0] == "class" else None,
        }
        self.functions[q] = info
        self._scope.append(("def", node.name))
        collector = BodyCollector(self, info)
        for stmt in node.body:
            collector.visit(stmt)
        # nested defs/classes
        for stmt in ast.walk(node):
            if stmt is node:
                continue
        self._visit_nested(node)
        self._scope.pop()

    def _visit_nested(self, node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._func(child)
            elif isinstance(child, ast.ClassDef):
                self.visit_ClassDef(child)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                self.visit(child)
            elif not isinstance(child, (ast.expr,)):
                self._visit_nested(child)

    def visit_FunctionDef(self, node):
        self._func(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        q = self.qual(node.name)
        self.classes[q] = {"id": f"{self.mod}:{q}", "name": node.name, "line": node.lineno,
                           "end": getattr(node, "end_lineno", node.lineno),
                           "bases": [self.seg(b, 60) for b in node.bases],
                           "doc": short(ast.get_docstring(node) or "", 300) or None}
        self._scope.append(("class", node.name))
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._func(child)
            elif isinstance(child, ast.ClassDef):
                self.visit_ClassDef(child)
        self._scope.pop()

    # -- module level
    def analyze(self):
        tree = ast.parse(self.src, filename=self.path)
        for stmt in tree.body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                self.visit(stmt)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.visit(stmt)
            else:
                self._module_stmt(stmt)
                self._visit_nested(stmt)
        return self

    def _module_stmt(self, stmt):
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            value = stmt.value
            for t in targets:
                if isinstance(t, ast.Name) and value is not None:
                    prev = literal_preview(value, self.src)
                    if SECRET_NAME.search(t.id):
                        prev["value"] = "***"
                        prev["redacted"] = True
                    self.constants.append({"name": t.id, "line": stmt.lineno, **prev,
                                           "upper": t.id.isupper()})
        flow_item = {"line": stmt.lineno, "kind": type(stmt).__name__.lower(), "code": self.seg(stmt)}
        info = {"calls": [], "io": [], "branches": [], "loops": [], "env": []}
        BodyCollector(self, info).visit(stmt)
        flow_item["calls"] = info["calls"]
        flow_item["refs"] = info.get("refs", [])
        if info["io"]:
            flow_item["io"] = info["io"]
        if info["branches"]:
            flow_item["branches"] = info["branches"]
        if isinstance(stmt, ast.If) and "__name__" in (self.seg(stmt.test) or ""):
            flow_item["kind"] = "main_guard"
            flow_item["body"] = []
            for s in stmt.body:
                inner = {"calls": [], "io": [], "branches": [], "loops": [], "env": []}
                BodyCollector(self, inner).visit(s)
                flow_item["body"].append({"line": s.lineno, "code": self.seg(s), "calls": inner["calls"], "refs": inner.get("refs", [])})
        self.main_flow.append(flow_item)


class BodyCollector(ast.NodeVisitor):
    def __init__(self, analyzer, info):
        self.a = analyzer
        self.info = info

    def visit_FunctionDef(self, node):
        return  # nested defs analysed separately

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Lambda(self, node):
        self.generic_visit(node)

    def visit_If(self, node):
        self.info["branches"].append({"line": node.lineno, "condition": self.a.seg(node.test, 140),
                                      "has_else": bool(node.orelse),
                                      "body_lines": [node.body[0].lineno, getattr(node.body[-1], "end_lineno", node.body[-1].lineno)]})
        self.generic_visit(node)

    def visit_Match(self, node):
        self.info["branches"].append({"line": node.lineno, "condition": "match " + self.a.seg(node.subject, 100),
                                      "has_else": any(isinstance(c.pattern, ast.MatchAs) and c.pattern.name is None for c in node.cases)})
        self.generic_visit(node)

    def visit_For(self, node):
        self.info["loops"].append({"line": node.lineno, "code": self.a.seg(node, 120)})
        self.generic_visit(node)

    visit_AsyncFor = visit_For

    def visit_While(self, node):
        self.info["loops"].append({"line": node.lineno, "code": self.a.seg(node, 120)})
        self.generic_visit(node)

    def visit_Name(self, node):
        # functions passed around as values (callbacks, pipelines of steps) count as possible calls
        if isinstance(node.ctx, ast.Load) and node.id not in self.info["calls"] and len(self.info.setdefault("refs", [])) < 60:
            if node.id not in self.info["refs"]:
                self.info["refs"].append(node.id)

    def visit_Subscript(self, node):
        d = dotted(node.value)
        if d in ("os.environ", "environ"):
            try:
                self.info["env"].append(ast.literal_eval(node.slice))
            except Exception:
                pass
        self.generic_visit(node)

    def visit_Call(self, node):
        name = dotted(node.func)
        if name:
            if name not in self.info["calls"] and len(self.info["calls"]) < 80:
                self.info["calls"].append(name)
            last = name.split(".")[-1]
            owner = name.split(".")[0].lower() if "." in name else ""
            first = node.args[0] if node.args else None
            if last == "dump" and len(node.args) > 1:      # json.dump(data, fh): the target is the file
                first = node.args[1]
            target = None
            if first is not None:
                try:
                    target = short(redact(str(ast.literal_eval(first))), 120)
                except Exception:
                    target = self.a.seg(first, 80)
            op = None
            if name in ("open", "io.open") or last == "open" and owner in ("path", "p", "file", "io"):
                mode = "r"
                if len(node.args) > 1:
                    try:
                        mode = ast.literal_eval(node.args[1])
                    except Exception:
                        mode = "?"
                for k in node.keywords:
                    if k.arg == "mode":
                        try:
                            mode = ast.literal_eval(k.value)
                        except Exception:
                            mode = "?"
                op = ("write" if any(c in str(mode) for c in "wax+") else "read", "file")
            elif last in READ_CALLS:
                op = ("read", "database" if "sql" in last or last.startswith("fetch") else "file")
            elif last in WRITE_CALLS:
                op = ("write", "database" if last in ("to_sql", "commit") else "email" if last in ("send_message", "sendmail") else "file")
            elif last in HTTP_VERBS and owner in HTTP_OWNERS:
                op = ("read" if last in ("get", "head") else "write", "api")
            elif last in ("execute", "executemany", "executescript"):
                sql = target or ""
                op = ("write" if SQL_WRITE.search(str(sql)) else "read", "database")
            elif last in ("load", "loads") and owner in ("json", "yaml", "pickle", "toml", "tomllib"):
                op = ("read", "file")
            elif last in ("getenv",) or name in ENV_CALLS:
                op = ("read", "config")
                if target:
                    self.info["env"].append(target.strip("'\""))
            elif last in ("connect", "create_engine"):
                op = ("connect", "database")
            if op:
                self.info["io"].append({"line": node.lineno, "call": name, "direction": op[0], "kind": op[1],
                                        "target": target})
        self.generic_visit(node)


def analyze_project(project, extra_files=()):
    """Follow imports from the entry point. Returns static index."""
    modules = {}
    queue = [(project.entry_module, project.entry)] + [(project.module_name_for(f), f) for f in extra_files]
    seen = set()
    while queue:
        modname, path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                src = fh.read()
            an = ModuleAnalyzer(project, modname, path, src).analyze()
        except SyntaxError as e:
            modules[modname] = {"name": modname, "path": project.rel(path), "error": f"SyntaxError: {e}"}
            continue
        modules[modname] = {
            "name": modname, "path": project.rel(path), "lines": len(an.lines),
            "imports": an.imports, "constants": an.constants,
            "functions": {k: v for k, v in an.functions.items()}, "classes": an.classes,
            "names": an.names, "main_flow": an.main_flow if path == project.entry else None,
            "_src": an.lines, "_abspath": path,
        }
        for imp in an.imports:
            if imp["kind"] != "project":
                continue
            cands = [imp["module"]] + [f"{imp['module']}.{n}" for n in imp["names"]]
            # parent packages too, so __init__ files are seen
            parts = imp["module"].split(".")
            cands += [".".join(parts[:i]) for i in range(1, len(parts))]
            for c in cands:
                p = project.resolve(c) if c else None
                if p and p not in seen:
                    queue.append((c, p))
    build_call_graph(modules)
    return modules


def build_call_graph(modules):
    func_ids = {}
    for m in modules.values():
        for q, f in (m.get("functions") or {}).items():
            func_ids[f["id"]] = f
        for q, c in (m.get("classes") or {}).items():
            func_ids.setdefault(c["id"], None)

    def resolve(mod, call, cls=None):
        m = modules.get(mod)
        if not m:
            return None
        head, _, rest = call.partition(".")
        if head == "self" and cls and rest and "." not in rest:
            cand = f"{mod}:{cls}.{rest}"
            return cand if cand in func_ids else None
        if f"{mod}:{call}" in func_ids:
            return f"{mod}:{call}"
        tgt = m["names"].get(head)
        if not tgt:
            return None
        if ":" in tgt:
            tmod, tname = tgt.split(":", 1)
            cand = f"{tmod}:{tname}" + (f".{rest}" if rest else "")
            if cand in func_ids:
                return cand
            # 'from pkg import mod' resolved as name
            if rest and f"{tmod}.{tname}:{rest}" in func_ids:
                return f"{tmod}.{tname}:{rest}"
            return None
        if rest:
            cand = f"{tgt}:{rest}"
            if cand in func_ids:
                return cand
            sub, _, fn = rest.rpartition(".")
            if sub and f"{tgt}.{sub}:{fn}" in func_ids:
                return f"{tgt}.{sub}:{fn}"
        return None

    for mname, m in modules.items():
        for f in (m.get("functions") or {}).values():
            f["calls_project"] = sorted({r for c in f["calls"] if (r := resolve(mname, c, f.get("class")))})
            refs = sorted({r for c in f.pop("refs", []) if (r := resolve(mname, c)) and r not in f["calls_project"] and r != f["id"]})
            if refs:
                f["references_project"] = refs
                f["calls_project"] = sorted(set(f["calls_project"]) | set(refs))
        if m.get("main_flow"):
            for item in m["main_flow"]:
                item["calls_project"] = sorted({r for c in item["calls"] + item.pop("refs", []) if (r := resolve(mname, c))})
                for b in item.get("body", []):
                    b["calls_project"] = sorted({r for c in b["calls"] + b.pop("refs", []) if (r := resolve(mname, c))})

    # reachability from the entry module's top-level code
    entry = next((m for m in modules.values() if m.get("main_flow") is not None), None)
    frontier = []
    if entry:
        for item in entry["main_flow"]:
            frontier += item.get("calls_project", [])
            for b in item.get("body", []):
                frontier += b.get("calls_project", [])
    reach = {}
    depth = 0
    while frontier and depth < 50:
        nxt = []
        for fid in frontier:
            if fid in reach:
                continue
            reach[fid] = depth
            f = func_ids.get(fid)
            if f:
                nxt += f.get("calls_project", [])
            else:  # class: constructor + methods it reaches
                mod, _, cls = fid.partition(":")
                init = func_ids.get(f"{mod}:{cls}.__init__")
                if init:
                    nxt.append(init["id"])
        frontier = nxt
        depth += 1
    for f in func_ids.values():
        if f:
            f["reach_depth"] = reach.get(f["id"])


# ----------------------------------------------------------------------------
# Value summaries (what the data looked like, never the full data)
# ----------------------------------------------------------------------------

def _cell(v, n=24):
    try:
        s = v if isinstance(v, str) else str(v)
    except Exception:
        s = "?"
    return short(redact(s), n)


def summarize(v, depth=0, name=None):
    if name and SECRET_NAME.search(str(name)):
        return {"type": type(v).__name__, "value": "***"}
    t = type(v)
    tname = t.__name__
    mod = getattr(t, "__module__", "") or ""
    try:
        if v is None or isinstance(v, (bool, int, float, complex)):
            return {"type": tname, "value": short(repr(v), 60)}
        if isinstance(v, str):
            out = {"type": "str", "len": len(v), "value": short(redact(v), 100)}
            return out
        if isinstance(v, (bytes, bytearray)):
            return {"type": tname, "len": len(v)}
        if mod.startswith("pandas") and tname == "DataFrame":
            cols = [str(c) for c in list(v.columns)[:40]]
            out = {"type": "DataFrame", "rows": int(v.shape[0]), "cols": int(v.shape[1]), "columns": cols,
                   "dtypes": {str(c): str(d) for c, d in list(v.dtypes.items())[:40]}}
            head = v.head(3)
            show = list(head.columns)[:10]
            out["sample"] = {"columns": [str(c) for c in show],
                             "rows": [[_cell(x) for x in row] for row in head[show].itertuples(index=False, name=None)]}
            return out
        if mod.startswith("pandas") and tname == "Series":
            return {"type": "Series", "rows": int(len(v)), "name": str(v.name), "dtype": str(v.dtype),
                    "sample": [_cell(x) for x in list(v.head(5))]}
        if mod.startswith("polars") and tname in ("DataFrame", "LazyFrame"):
            if tname == "LazyFrame":
                return {"type": "LazyFrame", "columns": [str(c) for c in v.collect_schema().names()][:40]}
            cols = [str(c) for c in v.columns[:40]]
            return {"type": "polars.DataFrame", "rows": v.height, "cols": v.width, "columns": cols,
                    "sample": {"columns": cols[:10], "rows": [[_cell(x) for x in r[:10]] for r in v.head(3).rows()]}}
        if mod.startswith("numpy") and tname == "ndarray":
            flat = v.ravel()[:5].tolist() if v.size else []
            return {"type": "ndarray", "shape": list(v.shape), "dtype": str(v.dtype), "sample": [_cell(x) for x in flat]}
        if mod.startswith(("requests", "httpx")) and tname == "Response":
            out = {"type": f"{mod.split('.')[0]}.Response", "status": getattr(v, "status_code", None),
                   "url": redact(short(str(getattr(v, "url", "")), 140)),
                   "content_type": (getattr(v, "headers", {}) or {}).get("content-type")}
            return out
        if isinstance(v, dict):
            keys = list(v.keys())
            out = {"type": tname, "len": len(v), "keys": [_cell(k, 40) for k in keys[:25]]}
            if depth < 2:
                out["values"] = {_cell(k, 40): summarize(v[k], depth + 1, name=k) for k in keys[:6]}
            return out
        if isinstance(v, (list, tuple, set, frozenset)) or tname == "deque":
            seq = list(v)[:3] if not isinstance(v, (list, tuple)) else v[:3]
            out = {"type": tname, "len": len(v)}
            if depth < 2:
                out["sample"] = [summarize(x, depth + 1) for x in seq]
            return out
        if hasattr(v, "__dataclass_fields__"):
            fields = list(v.__dataclass_fields__)[:12]
            out = {"type": f"{mod}.{tname}" if mod not in ("__main__", "builtins") else tname, "fields": fields}
            if depth < 2:
                out["values"] = {f: summarize(getattr(v, f, None), depth + 1, name=f) for f in fields[:6]}
            return out
        if callable(v) and hasattr(v, "__qualname__"):
            return {"type": "callable", "name": getattr(v, "__qualname__", tname)}
        out = {"type": f"{mod}.{tname}" if mod not in ("builtins",) else tname}
        d = getattr(v, "__dict__", None)
        if isinstance(d, dict) and d:
            out["attrs"] = list(d)[:12]
        return out
    except Exception:
        return {"type": tname}


# ----------------------------------------------------------------------------
# Tracer
# ----------------------------------------------------------------------------

DETAIL_PER_PARENT = 3      # first N calls of the same function under the same parent are kept in detail
MAX_NODES = 4000


class Tracer:
    def __init__(self, project, lines=None):
        self.p = project
        self.lines = lines           # LineRecorder when the walkthrough view is recorded
        self.nodes = []
        self.stats = {}              # fn -> {"calls", "total_ms"}
        self.stacks = {}             # thread id -> list of frames
        self.busy = threading.local()
        self.t0 = None
        self.agg = {}                # (parent_id, fn) -> count
        self.code_ids = {}
        self.tool = None
        self.truncated = False

    # code object -> function id or None
    def fid(self, code):
        # key by location: equal-looking code objects (e.g. empty __init__.py files) compare equal across files
        key = (code.co_filename, code.co_firstlineno, code.co_name)
        hit = self.code_ids.get(key, False)
        if hit is not False:
            return hit
        res = None
        if self.p.is_project_file(code.co_filename):
            name = getattr(code, "co_qualname", code.co_name)
            if not (name.endswith(("<genexpr>", "<listcomp>", "<dictcomp>", "<setcomp>")) or "<genexpr>" in name):
                res = f"{self.p.module_name_for(code.co_filename)}:{name}"
        self.code_ids[key] = res
        return res

    def _stack(self):
        tid = threading.get_ident()
        st = self.stacks.get(tid)
        if st is None:
            st = self.stacks[tid] = []
        return st

    def current_node(self):
        st = self.stacks.get(threading.get_ident()) or []
        for fr in reversed(st):
            if fr[1] is not None:
                return fr[1]
        return None

    def on_start(self, fid, frame, resumed=False):
        st = self._stack()
        parent = self.current_node()
        parent_id = parent["id"] if parent else None
        silent_parent = bool(st) and st[-1][1] is None and st[-1][2]
        s = self.stats.setdefault(fid, {"calls": 0, "total_ms": 0.0})
        s["calls"] += 1
        now = time.perf_counter()
        node = None
        if not silent_parent:
            key = (parent_id, fid)
            n = self.agg.get(key, 0) + 1
            self.agg[key] = n
            if n <= DETAIL_PER_PARENT and len(self.nodes) < MAX_NODES:
                node = {"id": len(self.nodes) + 1, "fn": fid, "parent": parent_id,
                        "t_ms": round((now - self.t0) * 1000, 2), "dur_ms": None}
                if frame is not None and not resumed:
                    node["args"] = self._args(frame)
                self.nodes.append(node)
            else:
                if len(self.nodes) >= MAX_NODES:
                    self.truncated = True
                if parent is not None:
                    rep = parent.setdefault("repeats", {})
                    rep[fid] = rep.get(fid, 0) + 1
        line_state = None
        if self.lines is not None and frame is not None and self.lines.focused(frame.f_code):
            line_state = self.lines.new_state()
        st.append([fid, node, node is None, now, line_state])

    def on_end(self, fid, retval=None, exc=None, has_ret=True, frame=None, yielded=False):
        st = self.stacks.get(threading.get_ident())
        if not st:
            return
        # pop until matching fid (defensive against missed events)
        while st:
            top = st.pop()
            if top[0] == fid:
                break
        if self.lines is not None and top[4] is not None:
            self.lines.finish(top, frame if top[0] == fid else None, exc)
        dur = (time.perf_counter() - top[3]) * 1000
        self.stats[fid]["total_ms"] += dur
        node = top[1]
        if node is not None:
            node["dur_ms"] = round(dur, 2)
            if exc is not None:
                node["raised"] = f"{type(exc).__name__}: {short(redact(str(exc)), 200)}"
            elif yielded:
                node["yielded"] = summarize(retval)
            elif has_ret and not fid.endswith(":<module>"):
                node["ret"] = summarize(retval)

    def on_line(self, frame, line):
        st = self.stacks.get(threading.get_ident())
        if not st:
            return
        top = st[-1]
        if top[4] is None or top[0] != self.fid(frame.f_code):
            return
        self.lines.on_line(self, top, frame, line)

    def _args(self, frame):
        code = frame.f_code
        n = code.co_argcount + code.co_kwonlyargcount
        flags = code.co_flags
        if flags & 0x04:
            n += 1
        if flags & 0x08:
            n += 1
        out = {}
        loc = frame.f_locals
        for name in code.co_varnames[:n][:12]:
            if name not in loc:
                continue
            v = loc[name]
            if name in ("self", "cls"):
                out[name] = {"type": getattr(v, "__name__", type(v).__name__)}
            else:
                out[name] = summarize(v, name=name)
        return out

    # ---- backends
    def start(self):
        self.t0 = time.perf_counter()
        use_monitoring = hasattr(sys, "monitoring") and not os.environ.get("CODESTORY_FORCE_SETPROFILE")
        if use_monitoring:
            self._start_monitoring()
        else:
            self._start_profile()

    def stop(self):
        if self.tool is not None:
            mon = sys.monitoring
            mon.set_events(self.tool, 0)
            for ev in ("PY_START", "PY_RETURN", "PY_UNWIND", "PY_YIELD", "PY_RESUME", "LINE"):
                mon.register_callback(self.tool, getattr(mon.events, ev), None)
            mon.free_tool_id(self.tool)
            self.tool = None
        else:
            sys.setprofile(None)
            threading.setprofile(None)
            if self.lines is not None:
                sys.settrace(None)

    def _guard(self):
        if getattr(self.busy, "on", False):
            return False
        self.busy.on = True
        return True

    def _release(self):
        self.busy.on = False

    def _start_monitoring(self):
        mon = sys.monitoring
        tool = None
        for t in (3, 4, 5, 2):
            try:
                mon.use_tool_id(t, "codestory")
                tool = t
                break
            except ValueError:
                continue
        if tool is None:
            log("sys.monitoring busy (debugger/profiler attached?) - falling back to setprofile")
            return self._start_profile()
        self.tool = tool
        E = mon.events
        DISABLE = mon.DISABLE

        def py_start(code, offset):
            fid = self.fid(code)
            if fid is None:
                return DISABLE
            if not self._guard():
                return None
            try:
                self.on_start(fid, sys._getframe(1))
            finally:
                self._release()

        def py_resume(code, offset):
            fid = self.fid(code)
            if fid is None:
                return DISABLE
            if not self._guard():
                return None
            try:
                self.on_start(fid, sys._getframe(1), resumed=True)
            finally:
                self._release()

        def py_return(code, offset, retval):
            fid = self.fid(code)
            if fid is None:
                return DISABLE
            if not self._guard():
                return None
            try:
                self.on_end(fid, retval, frame=sys._getframe(1))
            finally:
                self._release()

        def py_yield(code, offset, retval):
            fid = self.fid(code)
            if fid is None:
                return DISABLE
            if not self._guard():
                return None
            try:
                self.on_end(fid, retval, has_ret=False, frame=sys._getframe(1), yielded=True)
            finally:
                self._release()

        def py_unwind(code, offset, exc):
            fid = self.fid(code)
            if fid is None:
                return None
            if not self._guard():
                return None
            try:
                self.on_end(fid, exc=exc, has_ret=False, frame=sys._getframe(1))
            finally:
                self._release()

        lines = self.lines
        main_thread = threading.main_thread().ident

        def line(code, line_number):
            if not lines.focused(code):
                return DISABLE
            if threading.get_ident() != main_thread or not self._guard():
                return None
            try:
                self.on_line(sys._getframe(1), line_number)
            finally:
                self._release()

        mon.register_callback(tool, E.PY_START, py_start)
        mon.register_callback(tool, E.PY_RESUME, py_resume)
        mon.register_callback(tool, E.PY_RETURN, py_return)
        mon.register_callback(tool, E.PY_YIELD, py_yield)
        mon.register_callback(tool, E.PY_UNWIND, py_unwind)
        events = E.PY_START | E.PY_RESUME | E.PY_RETURN | E.PY_YIELD | E.PY_UNWIND
        if lines is not None:
            mon.register_callback(tool, E.LINE, line)
            events |= E.LINE
        mon.set_events(tool, events)

    def _start_profile(self):
        # Python < 3.12. The profile hook doesn't say why a frame exits, so with line tracing on we infer it:
        # an "exception" event not followed by another line in that frame means the exception propagated,
        # and a generator frame that is resumed later had yielded rather than returned.
        pending_exc = {}
        gen_frames = {}
        GEN_FLAGS = 0x20 | 0x200          # CO_GENERATOR | CO_ASYNC_GENERATOR

        def prof(frame, event, arg):
            if event not in ("call", "return"):
                return
            fid = self.fid(frame.f_code)
            if fid is None or not self._guard():
                return
            try:
                if event == "call":
                    prev = gen_frames.pop(id(frame), None)
                    if prev is not None and "ret" in prev:
                        prev["yielded"] = prev.pop("ret")
                    self.on_start(fid, frame, resumed=prev is not None)
                else:
                    st = self.stacks.get(threading.get_ident()) or []
                    node = st[-1][1] if st and st[-1][0] == fid else None
                    exc = pending_exc.pop(id(frame), None)
                    if exc is not None:
                        self.on_end(fid, exc=exc, has_ret=False, frame=frame)
                    else:
                        self.on_end(fid, arg, frame=frame)
                        if node is not None and frame.f_code.co_flags & GEN_FLAGS:
                            gen_frames[id(frame)] = node
            finally:
                self._release()
        sys.setprofile(prof)
        threading.setprofile(prof)
        if self.lines is not None:      # Python < 3.12: line events through settrace (main thread only)
            lines = self.lines

            def local(frame, event, arg):
                if event == "exception":
                    pending_exc[id(frame)] = arg[1]
                elif event == "line":
                    pending_exc.pop(id(frame), None)
                    if self._guard():
                        try:
                            self.on_line(frame, frame.f_lineno)
                        finally:
                            self._release()
                return local

            def trace(frame, event, arg):
                if event == "call" and lines.focused(frame.f_code):
                    return local
                return None
            sys.settrace(trace)


# ----------------------------------------------------------------------------
# I/O observation and safe mode
# ----------------------------------------------------------------------------

READ_METHODS = {"GET", "HEAD", "OPTIONS"}
SQL_READ_FIRST = {"select", "show", "describe", "desc", "explain", "pragma", "set", "begin", "start", "commit",
                  "rollback", "use", "savepoint", "release", "values", "table"}
SQL_TABLE = re.compile(r"""(?ix)^\s*(?:
    insert\s+(?:or\s+\w+\s+)?into\s+([\w."`\[\]]+)
  | replace\s+into\s+([\w."`\[\]]+)
  | update\s+(?:or\s+\w+\s+)?([\w."`\[\]]+)
  | delete\s+from\s+([\w."`\[\]]+)
  | merge\s+into\s+([\w."`\[\]]+)
  | (?:create|drop|alter|truncate)\s+(?:table\s+)?(?:if\s+(?:not\s+)?exists\s+)?(?:table\s+)?([\w."`\[\]]+)
  | copy\s+([\w."`\[\]]+)
)""")
WATCHED_LIBS = {
    "boto3": "AWS SDK calls (S3 uploads, etc.)", "google.cloud.storage": "Google Cloud Storage",
    "google.cloud.bigquery": "BigQuery", "azure.storage.blob": "Azure Blob Storage",
    "pyarrow": "pyarrow native file writes (e.g. parquet)", "snowflake.connector": "Snowflake",
    "pymongo": "MongoDB", "redis": "Redis", "kafka": "Kafka", "confluent_kafka": "Kafka",
    "paramiko": "SSH/SFTP", "ftplib": "FTP", "mysql.connector": "MySQL (connector)",
    "pyodbc": "ODBC databases", "sqlalchemy": "SQLAlchemy (writes are intercepted at the driver level)",
}


def _sql_text(q):
    if isinstance(q, (bytes, bytearray)):
        q = q.decode("utf-8", "replace")
    q = str(getattr(q, "text", q) if not isinstance(q, str) else q)
    q = re.sub(r"^\s*(--[^\n]*\n|/\*.*?\*/\s*)*", "", q, flags=re.S)
    return q.strip()


def sql_kind(q):
    text = _sql_text(q)
    first = (text.split(None, 1) or [""])[0].lower()
    if first == "with":
        return ("write" if re.search(r"\)\s*(insert|update|delete|merge)\b", text, re.I) else "read"), text
    if first in SQL_READ_FIRST or first == "":
        return "read", text
    return "write", text


def sql_table(text):
    m = SQL_TABLE.search(text)
    if not m:
        return None
    t = next((g for g in m.groups() if g), None)
    return t.strip('"`[]') if t else None


def _jsonable(v):
    try:
        json.dumps(v)
        return v
    except Exception:
        if isinstance(v, dict):
            return {str(k): _jsonable(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [_jsonable(x) for x in v]
        return repr(v)


class IOWatcher:
    """Observes reads/writes; in safe mode redirects or blocks writes."""

    def __init__(self, project, tracer, sandbox, safe=True, allow_subprocess=False):
        self.p = project
        self.tracer = tracer
        self.sandbox = sandbox
        self.safe = safe
        self.allow_subprocess = allow_subprocess
        self.events = {}         # key -> event
        self.order = 0
        self.redirects = {}      # real abs path -> sandbox path
        self.shadow_tables = {}  # table -> {"rows": n, "file": path}
        self.patches = []
        self.env_vars = {}
        self.import_hook = None
        self._lock = threading.RLock()
        self._orig = {}
        self.files_dir = os.path.join(sandbox, "files")
        self.db_dir = os.path.join(sandbox, "db_writes")

    # ---------- recording
    def record(self, kind, op, target, **detail):
        node = self.tracer.current_node() if self.tracer else None
        fn = node["fn"] if node else None
        key = (kind, op, str(target), fn, detail.get("handled"))
        with self._lock:
            ev = self.events.get(key)
            if ev is None:
                self.order += 1
                ev = {"seq": self.order, "kind": kind, "op": op, "target": target, "fn": fn,
                      "node": node["id"] if node else None, "count": 0,
                      "t_ms": round((time.perf_counter() - self.tracer.t0) * 1000, 2) if self.tracer and self.tracer.t0 else None}
                ev.update({k: v for k, v in detail.items() if v is not None})
                self.events[key] = ev
                if node is not None:
                    node.setdefault("io", []).append(ev["seq"])
            ev["count"] += 1
            for k in ("rows", "bytes"):
                if k in detail and isinstance(detail[k], int) and ev["count"] > 1:
                    ev[k] = ev.get(k, 0) + detail[k]
            return ev

    def _patch(self, obj, attr, new):
        self.patches.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, new)

    def uninstall(self):
        for obj, attr, old in reversed(self.patches):
            try:
                setattr(obj, attr, old)
            except Exception:
                pass
        self.patches.clear()
        if self.import_hook in sys.meta_path:
            sys.meta_path.remove(self.import_hook)

    def copy(self, src, dst):
        """Copy without being observed by our own patches."""
        os.makedirs(os.path.dirname(dst), exist_ok=True) if not self.patches else self._orig["makedirs"](os.path.dirname(dst), exist_ok=True)
        opener = self._orig.get("open", builtins.open)
        with opener(src, "rb") as a, opener(dst, "wb") as b:
            shutil.copyfileobj(a, b)

    def sandbox_path(self, real):
        drive, rest = os.path.splitdrive(real)
        rest = rest.lstrip("\\/")
        return os.path.join(self.files_dir, (drive.rstrip(":") + os.sep if drive else "") + rest)

    def is_user_path(self, abspath):
        if abspath.startswith(self.sandbox):
            return False
        if self.p.is_library_path(abspath):
            return False
        if abspath.startswith(("/proc/", "/sys/", "/dev/")):
            return False
        return not abspath.endswith((".pyc", ".pyo"))

    # ---------- install
    def install(self):
        self._install_files()
        self._install_env()
        self._install_subprocess()
        self._install_urllib()
        self._install_smtp()
        self._install_sqlite()
        hooks = {
            "requests": self._hook_requests, "httpx": self._hook_httpx, "pandas": self._hook_pandas,
            "psycopg2": self._hook_psycopg2, "psycopg": self._hook_psycopg, "pymysql": self._hook_pymysql,
        }
        for name, fn in list(hooks.items()):
            if name in sys.modules:
                fn(sys.modules[name])
                hooks.pop(name)
        self.import_hook = PostImportHook(hooks)
        sys.meta_path.insert(0, self.import_hook)

    # ---------- files
    def _install_files(self):
        orig_open = builtins.open
        orig_stat = os.stat
        self._orig.update(open=orig_open, makedirs=os.makedirs, mkdir=os.mkdir, stat=orig_stat)
        w = self

        def resolve_open(file, mode):
            if isinstance(file, int):
                return file, None
            try:
                path = os.fspath(file)
            except TypeError:
                return file, None
            if isinstance(path, bytes):
                path = os.fsdecode(path)
            absp = os.path.abspath(path)
            if not w.is_user_path(absp):
                return file, None
            writing = any(c in mode for c in "wax+")
            rel = w.p.rel(absp)
            if writing:
                if w.safe:
                    target = w.redirects.get(absp) or w.sandbox_path(absp)
                    w._orig["makedirs"](os.path.dirname(target), exist_ok=True)
                    if absp not in w.redirects and ("a" in mode or "+" in mode) and "w" not in mode and os.path.exists(absp):
                        w.copy(absp, target)
                    w.redirects[absp] = target
                    return target, ("write", rel, True, target)
                return file, ("write", rel, False, None)
            if absp in w.redirects:
                return w.redirects[absp], ("read", rel, True, w.redirects[absp])
            return file, ("read", rel, False, None)

        def patched_open(file, mode="r", *args, **kwargs):
            target, info = resolve_open(file, mode)
            fh = orig_open(target, mode, *args, **kwargs)
            if info:
                op, rel, handled, sb = info
                size = None
                if op == "read":
                    try:
                        size = orig_stat(target).st_size
                    except Exception:
                        pass
                w.record("file", op, rel, mode=mode, bytes=size,
                         handled=("redirected" if op == "write" else "read-redirected") if handled else None,
                         sandbox=sb)
            return fh

        def patched_stat(path, *args, **kwargs):
            if not isinstance(path, int) and w.redirects:
                try:
                    absp = os.path.abspath(os.fspath(path))
                    if absp in w.redirects:
                        path = w.redirects[absp]
                except Exception:
                    pass
            return orig_stat(path, *args, **kwargs)

        self._patch(builtins, "open", patched_open)
        self._patch(io, "open", patched_open)
        self._patch(os, "stat", patched_stat)

        def guard_mutation(name, fn, n_paths=1):
            def wrapper(*args, **kwargs):
                paths = []
                for a in args[:n_paths]:
                    try:
                        paths.append(os.path.abspath(os.fspath(a)))
                    except Exception:
                        return fn(*args, **kwargs)
                if not any(w.is_user_path(p) for p in paths):
                    return fn(*args, **kwargs)
                rels = " -> ".join(w.p.rel(p) for p in paths)
                if not w.safe:
                    w.record("file", name, rels)
                    return fn(*args, **kwargs)
                src = paths[0]
                if name in ("rename", "replace", "move") and len(paths) > 1:
                    dst = paths[1]
                    sb_dst = w.sandbox_path(dst)
                    if src in w.redirects:
                        w.copy(w.redirects.pop(src), sb_dst)
                    elif os.path.isfile(src):
                        w.copy(src, sb_dst)
                    w.redirects[dst] = sb_dst
                    w.record("file", name, rels, handled="redirected")
                    return dst if name == "move" else None
                if src in w.redirects:
                    try:
                        os.unlink(w.redirects.pop(src))
                    except Exception:
                        pass
                    w.record("file", name, rels, handled="redirected")
                    return None
                w.record("file", name, rels, handled="blocked")
                return None
            return wrapper

        for name in ("remove", "unlink", "rmdir"):
            self._patch(os, name, guard_mutation(name, getattr(os, name)))
        for name in ("rename", "replace"):
            self._patch(os, name, guard_mutation(name, getattr(os, name), 2))
        self._patch(shutil, "rmtree", guard_mutation("rmtree", shutil.rmtree))
        self._patch(shutil, "move", guard_mutation("move", shutil.move, 2))

        orig_makedirs = os.makedirs
        orig_mkdir = os.mkdir
        orig_listdir = os.listdir
        orig_scandir = os.scandir
        state = threading.local()

        def mk(fn, name):
            def wrapper(path, *a, **k):
                if getattr(state, "inside", False):
                    return fn(path, *a, **k)
                try:
                    absp = os.path.abspath(os.fspath(path))
                except Exception:
                    return fn(path, *a, **k)
                if not w.is_user_path(absp) or os.path.isdir(absp):
                    return fn(path, *a, **k)
                state.inside = True
                try:
                    if w.safe:   # create the folder in the sandbox; exists()/listdir() see it there
                        sb = w.sandbox_path(absp)
                        orig_makedirs(sb, exist_ok=True)
                        w.redirects[absp] = sb
                        w.record("file", "mkdir", w.p.rel(absp), handled="redirected")
                        return None
                    w.record("file", "mkdir", w.p.rel(absp))
                    return fn(path, *a, **k)
                finally:
                    state.inside = False
            return wrapper
        self._patch(os, "makedirs", mk(orig_makedirs, "mkdir"))
        self._patch(os, "mkdir", mk(orig_mkdir, "mkdir"))

        def lister(fn):
            def wrapper(path=".", *a, **k):
                if not isinstance(path, int) and w.redirects:
                    try:
                        absp = os.path.abspath(os.fspath(path))
                        if absp in w.redirects:
                            path = w.redirects[absp]
                    except Exception:
                        pass
                return fn(path, *a, **k)
            return wrapper
        self._patch(os, "listdir", lister(orig_listdir))
        self._patch(os, "scandir", lister(orig_scandir))

    # ---------- environment
    def _install_env(self):
        orig = os.getenv
        w = self

        def getenv(key, default=None):
            val = orig(key, default)
            w.env_vars[key] = {"set": key in os.environ, "secret": bool(SECRET_NAME.search(key))}
            return val
        self._patch(os, "getenv", getenv)

    def called_from_project(self):
        f = sys._getframe(2)
        while f is not None:
            fn = f.f_code.co_filename
            if os.path.abspath(fn) == SELF_FILE or fn.endswith(("subprocess.py", "contextlib.py")):
                f = f.f_back
                continue
            return self.p.is_project_file(fn)
        return False

    # ---------- subprocess
    def _install_subprocess(self):
        import subprocess
        w = self
        Orig = subprocess.Popen

        class Popen(Orig):
            def __init__(self, args, *a, **k):
                cmd = args if isinstance(args, str) else " ".join(map(str, args))
                if not w.called_from_project():
                    super().__init__(args, *a, **k)
                    return
                if w.safe and not w.allow_subprocess:
                    w.record("process", "run", short(redact(cmd), 160), handled="blocked")
                    args = [sys.executable, "-c", ""]
                    k.pop("shell", None)
                    k.pop("executable", None)
                else:
                    w.record("process", "run", short(redact(cmd), 160))
                super().__init__(args, *a, **k)
        self._patch(subprocess, "Popen", Popen)
        orig_system = os.system

        def system(cmd):
            if not w.called_from_project():
                return orig_system(cmd)
            if w.safe and not w.allow_subprocess:
                w.record("process", "run", short(redact(cmd), 160), handled="blocked")
                return 0
            w.record("process", "run", short(redact(cmd), 160))
            return orig_system(cmd)
        self._patch(os, "system", system)

    # ---------- http
    def _http(self, method, url, status=None, ctype=None, size=None, handled=None):
        u = redact(short(str(url), 200))
        self.record("api", method.upper(), u, status=status, content_type=ctype, bytes=size, handled=handled)

    def _install_urllib(self):
        import urllib.request
        import urllib.response
        import email.message
        orig = urllib.request.urlopen
        w = self

        def urlopen(url, data=None, *a, **k):
            if isinstance(url, urllib.request.Request):
                method, full = url.get_method(), url.full_url
            else:
                method, full = ("POST" if data is not None else "GET"), url
            if w.safe and method.upper() not in READ_METHODS:
                w._http(method, full, status=200, handled="blocked")
                return urllib.response.addinfourl(io.BytesIO(b"{}"), email.message.Message(), full, 200)
            resp = orig(url, data, *a, **k)
            w._http(method, full, status=getattr(resp, "status", None), ctype=resp.headers.get("content-type"))
            return resp
        self._patch(urllib.request, "urlopen", urlopen)

    def _hook_requests(self, requests):
        w = self
        orig = requests.Session.request

        def request(sess, method, url, *a, **k):
            if w.safe and str(method).upper() not in READ_METHODS:
                w._http(method, url, status=200, handled="blocked")
                r = requests.Response()
                r.status_code = 200
                r.reason = "OK (blocked by codestory safe mode)"
                r._content = b"{}"
                r.url = str(url)
                r.encoding = "utf-8"
                r.headers["Content-Type"] = "application/json"
                try:
                    r.request = requests.Request(method, url).prepare()
                except Exception:
                    pass
                return r
            resp = orig(sess, method, url, *a, **k)
            size = None if k.get("stream") else len(resp.content or b"")
            w._http(method, url, status=resp.status_code, ctype=resp.headers.get("content-type"), size=size)
            return resp
        self._patch(requests.Session, "request", request)

    def _hook_httpx(self, httpx):
        w = self
        orig_send = httpx.Client.send
        orig_asend = httpx.AsyncClient.send

        def fake(request):
            w._http(request.method, request.url, status=200, handled="blocked")
            return httpx.Response(200, json={}, request=request)

        def send(client, request, *a, **k):
            if w.safe and request.method.upper() not in READ_METHODS:
                return fake(request)
            resp = orig_send(client, request, *a, **k)
            w._http(request.method, request.url, status=resp.status_code, ctype=resp.headers.get("content-type"))
            return resp

        async def asend(client, request, *a, **k):
            if w.safe and request.method.upper() not in READ_METHODS:
                return fake(request)
            resp = await orig_asend(client, request, *a, **k)
            w._http(request.method, request.url, status=resp.status_code, ctype=resp.headers.get("content-type"))
            return resp
        self._patch(httpx.Client, "send", send)
        self._patch(httpx.AsyncClient, "send", asend)

    # ---------- email
    def _install_smtp(self):
        import smtplib
        if not self.safe:
            orig = smtplib.SMTP.sendmail
            w = self

            def sendmail(s, from_addr, to_addrs, msg, *a, **k):
                w.record("email", "send", ", ".join(to_addrs) if isinstance(to_addrs, (list, tuple)) else str(to_addrs))
                return orig(s, from_addr, to_addrs, msg, *a, **k)
            self._patch(smtplib.SMTP, "sendmail", sendmail)
            return
        w = self

        class FakeSMTP:
            def __init__(self, host="", port=0, *a, **k):
                self.host = host
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
            def __getattr__(self, name):
                return lambda *a, **k: (250, b"OK")
            def sendmail(self, from_addr, to_addrs, msg, *a, **k):
                to = ", ".join(to_addrs) if isinstance(to_addrs, (list, tuple)) else str(to_addrs)
                w.record("email", "send", to, handled="blocked", server=str(self.host))
                return {}
            def send_message(self, msg, from_addr=None, to_addrs=None, *a, **k):
                to = to_addrs or msg.get("To", "")
                w.record("email", "send", str(to), handled="blocked", server=str(self.host),
                         subject=short(str(msg.get("Subject", "")), 100))
                return {}
        self._patch(smtplib, "SMTP", FakeSMTP)
        self._patch(smtplib, "SMTP_SSL", FakeSMTP)

    # ---------- databases
    def _install_sqlite(self):
        import sqlite3
        orig = sqlite3.connect
        w = self

        def connect(database, *a, **k):
            label = str(database)
            target = database
            handled = None
            if isinstance(database, (str, bytes, os.PathLike)) and str(database) != ":memory:" and not k.get("uri"):
                absp = os.path.abspath(os.fspath(database))
                if w.is_user_path(absp):
                    label = w.p.rel(absp)
                    if w.safe:
                        copy = w.redirects.get(absp) or w.sandbox_path(absp)
                        if absp not in w.redirects:
                            if os.path.exists(absp):
                                w.copy(absp, copy)
                            w.redirects[absp] = copy
                        target = copy
                        handled = "working-copy"
            conn = orig(target, *a, **k)
            w.record("database", "connect", f"sqlite:{label}", handled=handled)
            db = f"sqlite:{label}"

            def trace(stmt):
                kind, text = sql_kind(stmt)
                if sql_is_noise(text):
                    return
                table = sql_table(text) if kind == "write" else _first_from(text)
                w.record("database", sql_verb(text) if kind == "write" else "read", f"{db}" + (f" / {table}" if table else ""),
                         sql=short(redact(" ".join(text.split())), 160), handled=handled, rows=1 if kind == "write" else None)
            try:
                conn.set_trace_callback(trace)
            except Exception:
                pass
            return conn
        self._patch(sqlite3, "connect", connect)

    def shadow_execute(self, cursor, real, query, params, many, db):
        kind, text = sql_kind(query)
        if kind == "read" or not self.safe:
            if kind == "read" and self.shadow_tables:
                hit = [t for t in self.shadow_tables if re.search(rf"\b{re.escape(t.split('.')[-1])}\b", text, re.I)]
                if hit:
                    self.record("database", "read-after-write", f"{db} / {', '.join(hit)}",
                                note="this read does not include rows held in the sandbox")
            if sql_is_noise(text):
                return real(query, params) if params is not None else real(query)
            table = sql_table(text) if kind == "write" else _first_from(text)
            rows = len(params) if (many and kind == "write" and hasattr(params, "__len__")) else (1 if kind == "write" else None)
            self.record("database", sql_verb(text) if kind == "write" else "read", f"{db}" + (f" / {table}" if table else ""),
                        sql=short(redact(" ".join(text.split())), 160), rows=rows)
            return real(query, params) if params is not None else real(query)
        table = sql_table(text) or "unknown"
        os.makedirs(self.db_dir, exist_ok=True)
        fname = os.path.join(self.db_dir, re.sub(r"[^\w.-]", "_", f"{db}__{table}") + ".jsonl")
        batch = list(params) if many and params is not None else [params]
        with builtins.open(fname, "a", encoding="utf-8") as fh:
            for row in batch:
                fh.write(json.dumps({"sql": " ".join(text.split()), "params": _jsonable(row)}) + "\n")
        st = self.shadow_tables.setdefault(table, {"rows": 0, "file": fname})
        st["rows"] += len(batch)
        self.record("database", sql_verb(text), f"{db} / {table}", sql=short(redact(" ".join(text.split())), 160),
                    rows=len(batch), handled="shadowed", sandbox=fname)
        return None

    def _cursor_subclass(self, base, db):
        w = self
        cache = self.__dict__.setdefault("_cursor_cache", {})
        key = (base, db)
        if key in cache:
            return cache[key]

        def execute(cur, query, params=None, *a, **k):
            def real(q, p=None):
                return base.execute(cur, q, p, *a, **k) if p is not None else base.execute(cur, q, *a, **k)
            return w.shadow_execute(cur, real, query, params, False, db)

        def executemany(cur, query, seq, *a, **k):
            seq = list(seq)
            return w.shadow_execute(cur, lambda q, p=None: base.executemany(cur, q, p, *a, **k), query, seq, True, db)
        sub = type("Codestory" + base.__name__, (base,), {"execute": execute, "executemany": executemany})
        cache[key] = sub
        return sub

    def _hook_psycopg2(self, psycopg2):
        import importlib
        ext = importlib.import_module("psycopg2.extensions")
        w = self
        orig = psycopg2.connect

        def connect(*a, **k):
            db = "postgres:" + str(k.get("dbname") or k.get("database") or (a[0] if a else "?")).split(" ")[0][:60]
            db = redact(db)
            base_conn = k.pop("connection_factory", None) or ext.connection
            default_cur = k.pop("cursor_factory", None)

            class Conn(base_conn):
                def cursor(self, *ca, **ck):
                    base = ck.pop("cursor_factory", None) or default_cur or ext.cursor
                    ck["cursor_factory"] = w._cursor_subclass(base, db)
                    return super().cursor(*ca, **ck)
            conn = orig(*a, connection_factory=Conn, **k)
            w.record("database", "connect", db, handled="shadowed" if w.safe else None)
            return conn
        self._patch(psycopg2, "connect", connect)

    def _hook_psycopg(self, psycopg):
        w = self
        orig = psycopg.connect

        def connect(*a, **k):
            db = redact("postgres:" + str(k.get("dbname") or (a[0] if a else "?")).split(" ")[0][:60])
            conn = orig(*a, **k)
            try:
                conn.cursor_factory = w._cursor_subclass(conn.cursor_factory or psycopg.Cursor, db)
            except Exception as e:
                w.record("database", "connect", db, note=f"not intercepted: {e}")
                return conn
            w.record("database", "connect", db, handled="shadowed" if w.safe else None)
            return conn
        self._patch(psycopg, "connect", connect)

    def _hook_pymysql(self, pymysql):
        import importlib
        cursors = importlib.import_module("pymysql.cursors")
        w = self
        orig = pymysql.connect

        def connect(*a, **k):
            db = redact("mysql:" + str(k.get("database") or k.get("db") or "?"))
            k["cursorclass"] = w._cursor_subclass(k.get("cursorclass") or cursors.Cursor, db)
            conn = orig(*a, **k)
            w.record("database", "connect", db, handled="shadowed" if w.safe else None)
            return conn
        self._patch(pymysql, "connect", connect)

    # ---------- pandas native writers (parquet/feather bypass Python's open)
    def _hook_pandas(self, pd):
        w = self

        def wrap_writer(name):
            orig = getattr(pd.DataFrame, name, None)
            if orig is None:
                return

            def writer(df, path=None, *a, **k):
                try:
                    absp = os.path.abspath(os.fspath(path))
                except Exception:
                    return orig(df, path, *a, **k)
                if not w.is_user_path(absp):
                    return orig(df, path, *a, **k)
                if w.safe:
                    target = w.sandbox_path(absp)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    w.redirects[absp] = target
                    w.record("file", "write", w.p.rel(absp), rows=int(df.shape[0]), handled="redirected", via=name)
                    return orig(df, target, *a, **k)
                w.record("file", "write", w.p.rel(absp), rows=int(df.shape[0]), via=name)
                return orig(df, path, *a, **k)
            self._patch(pd.DataFrame, name, writer)

        def wrap_reader(name):
            orig = getattr(pd, name, None)
            if orig is None:
                return

            def reader(path, *a, **k):
                try:
                    absp = os.path.abspath(os.fspath(path))
                    if absp in w.redirects:
                        w.record("file", "read", w.p.rel(absp), handled="read-redirected", via=name)
                        return orig(w.redirects[absp], *a, **k)
                    if w.is_user_path(absp):
                        w.record("file", "read", w.p.rel(absp), via=name)
                except Exception:
                    pass
                return orig(path, *a, **k)
            self._patch(pd, name, reader)

        for n in ("to_parquet", "to_feather", "to_orc", "to_hdf"):
            wrap_writer(n)
        for n in ("read_parquet", "read_feather", "read_orc", "read_hdf"):
            wrap_reader(n)

    # ---------- summary
    def report(self):
        events = sorted(self.events.values(), key=lambda e: e["seq"])
        intercepted = [e for e in events if e.get("handled") in ("redirected", "blocked", "shadowed", "working-copy")
                       and e["op"] not in ("read", "connect", "mkdir")]
        real = [e for e in events if e["op"] not in ("read", "connect", "read-after-write")
                and e.get("handled") not in ("redirected", "blocked", "shadowed", "working-copy", "read-redirected")]
        watched = []
        for mod, label in WATCHED_LIBS.items():
            if mod in sys.modules and mod not in ("sqlalchemy",):
                watched.append({"library": mod, "what": label})
        return {
            "events": events,
            "intercepted": [{"seq": e["seq"], "kind": e["kind"], "op": e["op"], "target": e["target"],
                             "handled": e["handled"], "count": e["count"]} for e in intercepted],
            "real_effects": [{"seq": e["seq"], "kind": e["kind"], "op": e["op"], "target": e["target"],
                              "count": e["count"]} for e in real],
            "not_intercepted_libraries": watched,
            "shadow_tables": self.shadow_tables,
            "env_vars": self.env_vars,
        }


def sql_verb(text):
    return (text.split(None, 1) or ["write"])[0].lower()


def sql_is_noise(text):
    first = (text.split(None, 1) or [""])[0].lower()
    if first in ("begin", "commit", "rollback", "savepoint", "release", "pragma", "set", "start", "end", "use", ""):
        return True
    return bool(re.search(r"\b(sqlite_master|sqlite_schema|information_schema|pg_catalog)\b", text, re.I))


def _first_from(text):
    m = re.search(r"\bfrom\s+([\w.\"`\[\]]+)", text, re.I)
    return m.group(1).strip('"`[]') if m else None


class PostImportHook(importlib.abc.MetaPathFinder):
    """Runs a patch function right after selected third-party modules finish importing."""

    def __init__(self, hooks):
        self.hooks = dict(hooks)
        self._busy = set()

    def find_spec(self, name, path=None, target=None):
        if name not in self.hooks or name in self._busy:
            return None
        self._busy.add(name)
        try:
            spec = importlib.util.find_spec(name)
        except Exception:
            spec = None
        finally:
            self._busy.discard(name)
        if spec is None or spec.loader is None or not hasattr(spec.loader, "exec_module"):
            return spec
        hook = self.hooks.pop(name)
        loader = spec.loader
        orig_exec = loader.exec_module

        def exec_module(module):
            orig_exec(module)
            try:
                hook(module)
            except Exception as e:
                log(f"could not attach to {name}: {e}")
        try:
            loader.exec_module = exec_module
        except Exception:
            pass
        return spec


# ----------------------------------------------------------------------------
# Walkthrough view: focus, statement map, line recording, step plan
# ----------------------------------------------------------------------------

MAX_LINE_EVENTS = 20_000
MAX_PLAN_STEPS = 5_000
MAX_STEPS_DEFAULT = 150
_BUILTIN_NAMES = set(dir(builtins))


class Focus:
    """Which code the walkthrough covers: everything, or chosen files and functions."""

    def __init__(self, project, modules, spec=None):
        self.p = project
        self.spec = spec
        self.all = not spec
        self.files, self.funcs, self.items = set(), set(), []
        self._cache = {}
        if self.all:
            return
        by_path = {m["_abspath"]: m for m in modules.values() if "_abspath" in m}
        problems = []
        for item in [x.strip() for x in spec.split(",") if x.strip()]:
            hit = False
            if item.endswith(".py") or "/" in item or os.sep in item:
                for base in (project.root, os.getcwd()):
                    path = os.path.abspath(os.path.join(base, item))
                    if path in by_path:
                        self.files.add(path)
                        self.items.append({"file": project.rel(path)})
                        hit = True
                        break
            elif ":" in item:
                mod, q = item.split(":", 1)
                m = modules.get(mod)
                if m and q in (m.get("functions") or {}):
                    self.funcs.add((m["_abspath"], q))
                    self.items.append({"function": item})
                    hit = True
            else:
                for m in modules.values():
                    if m.get("name") == item and "_abspath" in m:
                        self.files.add(m["_abspath"])
                        self.items.append({"file": project.rel(m["_abspath"])})
                        hit = True
                    for q, f in (m.get("functions") or {}).items():
                        if f["name"] == item or q == item:
                            self.funcs.add((m["_abspath"], q))
                            self.items.append({"function": f["id"]})
                            hit = True
            if not hit:
                problems.append(item)
        if problems:
            raise SystemExit("--focus: not found among the files reachable from the entry point: " + ", ".join(problems))

    def matches(self, filename, qualname):
        key = (filename, qualname)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        if not self.p.is_project_file(filename):
            res = False
        elif self.all:
            res = True
        else:
            path = os.path.abspath(filename)
            res = path in self.files or any(
                f == path and (qualname == q or qualname.startswith(q + ".<locals>.")) for f, q in self.funcs)
        self._cache[key] = res
        return res

    def matches_fid(self, fid, modules):
        mod, _, q = fid.partition(":")
        m = modules.get(mod)
        return bool(m and "_abspath" in m and self.matches(m["_abspath"], q))

    def files_in_scope(self, modules):
        out = []
        for m in modules.values():
            if "_abspath" not in m:
                continue
            if self.all or m["_abspath"] in self.files or any(f == m["_abspath"] for f, _ in self.funcs):
                out.append(m)
        return out

    def describe(self):
        return "whole program" if self.all else self.items


# ---------- statement map ----------

def _stmt_kind(node, scope_is_module):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return "import"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "def"
    if isinstance(node, ast.ClassDef):
        return "class"
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if scope_is_module and all(isinstance(t, ast.Name) and t.id.isupper() for t in targets) and node.value is not None:
            try:
                ast.literal_eval(node.value)
                return "constant"
            except Exception:
                pass
        return "assign"
    if isinstance(node, ast.AugAssign):
        return "assign"
    if isinstance(node, ast.Return):
        return "return"
    if isinstance(node, ast.If):
        return "if"
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return "for"
    if isinstance(node, ast.While):
        return "while"
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return "with"
    if isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
        return "try"
    if isinstance(node, ast.Raise):
        return "raise"
    if isinstance(node, ast.Assert):
        return "assert"
    if isinstance(node, (ast.Break, ast.Continue, ast.Pass)):
        return type(node).__name__.lower()
    if isinstance(node, ast.Delete):
        return "delete"
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return "scope"
    if type(node).__name__ == "Match":
        return "match"
    if isinstance(node, ast.Expr):
        if isinstance(node.value, (ast.Yield, ast.YieldFrom)):
            return "yield"
        return "call" if isinstance(node.value, (ast.Call, ast.Await)) else "expr"
    return type(node).__name__.lower()


def _header_parts(node):
    """The parts of a statement that belong to its own line(s): for compound statements, not the body."""
    if isinstance(node, ast.If) or isinstance(node, ast.While):
        return [node.test]
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return [node.target, node.iter]
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return list(node.items)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        a = node.args
        parts = list(node.decorator_list) + list(a.defaults) + [d for d in a.kw_defaults if d is not None]
        parts += [x.annotation for x in a.posonlyargs + a.args + a.kwonlyargs if x.annotation is not None]
        if node.returns is not None:
            parts.append(node.returns)
        return parts
    if isinstance(node, ast.ClassDef):
        return list(node.decorator_list) + list(node.bases) + [k.value for k in node.keywords]
    if type(node).__name__ == "Match":
        return [node.subject]
    if isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
        return []
    return [node]


_BLOCK_FIELDS = ("body", "orelse", "finalbody")


def _blocks(node):
    out = {}
    for f in _BLOCK_FIELDS:
        v = getattr(node, f, None)
        if isinstance(v, list) and v and isinstance(v[0], ast.stmt):
            out[f] = v
    if hasattr(node, "handlers") and node.handlers:
        for i, h in enumerate(node.handlers):
            out[f"handler{i}"] = h.body
    if type(node).__name__ == "Match":
        for i, c in enumerate(node.cases):
            out[f"case{i}"] = c.body
    return out


def _is_docstring(stmt):
    return isinstance(stmt, ast.Expr) and isinstance(getattr(stmt, "value", None), ast.Constant) and isinstance(stmt.value.value, str)


def _calls_in_eval_order(node):
    """Call nodes in the order Python finishes them: arguments before the call that receives them."""
    out = []

    def visit(n):
        if isinstance(n, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n is not node:
            return
        for child in ast.iter_child_nodes(n):
            visit(child)
        if isinstance(n, ast.Call):
            out.append(n)
    visit(node)
    return out


def _is_generator(fn_node):
    stack = list(fn_node.body)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.Yield, ast.YieldFrom)):
            return True
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(n))
    return False


def _is_trivial_assign(stmt):
    """x = 1, x = y, x = obj.attr: plain names on the left, nothing computed on the right."""
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [getattr(stmt, "target", None)]
    if isinstance(stmt, ast.AugAssign) or not all(isinstance(t, ast.Name) for t in targets):
        return False
    v = stmt.value
    if v is None:
        return True
    if isinstance(v, (ast.Name, ast.Attribute)):
        return True
    try:
        ast.literal_eval(v)
        return True
    except Exception:
        return False


class StatementMapper:
    """Builds the statement map for one module: every statement, its kind, names and where they come from."""

    def __init__(self, project, modules, m):
        self.p = project
        self.modules = modules
        self.m = m
        self.mod = m["name"]
        self.rel = m["path"]
        self.src = "\n".join(m["_src"])
        self.lines = m["_src"]
        self.helper = ModuleAnalyzer(project, self.mod, m["_abspath"], self.src)
        self.out = {}
        self.order = []
        self.line_map = {}
        self.comments = self._comments()
        self.module_names = self._module_names()
        self.func_ids = {f["id"]: f for mm in modules.values() for f in (mm.get("functions") or {}).values()}

    def _comments(self):
        import tokenize
        out = {}
        try:
            for tok in tokenize.generate_tokens(io.StringIO(self.src).readline):
                if tok.type == tokenize.COMMENT:
                    out[tok.start[0]] = tok.string.lstrip("#").strip()
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass
        return out

    def _module_names(self):
        names = {}
        for c in self.m.get("constants", []):
            names[c["name"]] = {"kind": "constant" if c.get("upper") else "global", "where": f"{self.rel}:{c['line']}",
                                "value": c.get("value")}
        for q, f in (self.m.get("functions") or {}).items():
            if "." not in q:
                names[f["name"]] = {"kind": "function", "where": f"{self.rel}:{f['line']}", "id": f["id"]}
        for q, c in (self.m.get("classes") or {}).items():
            if "." not in q:
                names[c["name"]] = {"kind": "class", "where": f"{self.rel}:{c['line']}", "id": c["id"]}
        imports_by_alias = {}
        for imp in self.m.get("imports", []):
            if imp.get("scope") != "module":
                continue
            if imp["names"]:
                for n in imp["names"]:
                    imports_by_alias[n] = imp
            else:
                imports_by_alias[imp["alias"] or imp["module"].split(".")[0]] = imp
        for alias, target in (self.m.get("names") or {}).items():
            imp = imports_by_alias.get(alias) or {}
            kind = imp.get("kind", "project")
            info = {"kind": {"project": "import_project", "stdlib": "import_stdlib",
                             "third_party": "import_package", "missing": "import_package"}.get(kind, "import_project"),
                    "from": target.replace(":", ".")}
            if kind == "project":
                if ":" in target:
                    tm, tn = target.split(":", 1)
                    fid = f"{tm}:{tn}"
                    mm = self.modules.get(tm)
                    if mm:
                        f = (mm.get("functions") or {}).get(tn)
                        c = (mm.get("classes") or {}).get(tn)
                        cst = next((x for x in mm.get("constants", []) if x["name"] == tn), None)
                        if f:
                            info.update(where=f"{mm['path']}:{f['line']}", id=fid, what="function")
                        elif c:
                            info.update(where=f"{mm['path']}:{c['line']}", id=fid, what="class")
                        elif cst:
                            info.update(where=f"{mm['path']}:{cst['line']}", what="constant", value=cst.get("value"))
                        else:
                            info.update(where=mm["path"])
                else:
                    mm = self.modules.get(target)
                    if mm:
                        info.update(where=mm["path"], what="module")
            else:
                info["package"] = target.split(":")[0].split(".")[0]
            names[alias] = info
        return names

    def resolve_name(self, name, fn):
        if fn is not None:
            if name in fn["params"]:
                return {"kind": "parameter"}
            if name in fn["locals"]:
                return {"kind": "local"}
        if name in self.module_names:
            return self.module_names[name]
        if name in _BUILTIN_NAMES:
            return {"kind": "builtin"}
        return {"kind": "unknown"}

    def resolve_call(self, call, fn, cls):
        head, _, rest = call.partition(".")
        if head == "self" and cls and rest and "." not in rest:
            fid = f"{self.mod}:{cls}.{rest}"
            if fid in self.func_ids:
                return {"call": call, "origin": "project", "id": fid, "where": f"{self.rel}:{self.func_ids[fid]['line']}"}
        info = self.resolve_name(head, fn)
        k = info["kind"]
        if k in ("function", "class") and not rest:
            fid = info.get("id")
            if k == "class":
                init = fid + ".__init__"
                fid = init if init in self.func_ids else fid
            return {"call": call, "origin": "project", "id": fid, "where": info.get("where")}
        if k == "import_project":
            if info.get("what") in ("function", "class") and not rest:
                return {"call": call, "origin": "project", "id": info.get("id"), "where": info.get("where")}
            if info.get("what") == "module" and rest:
                target = info["from"]
                sub, _, name = rest.rpartition(".")
                mod = f"{target}.{sub}" if sub else target
                fid = f"{mod}:{name}"
                f = self.func_ids.get(fid)
                if f:
                    mm = self.modules.get(mod)
                    return {"call": call, "origin": "project", "id": fid, "where": f"{mm['path']}:{f['line']}" if mm else None}
            return {"call": call, "origin": "project", "where": info.get("where")}
        if k in ("import_package", "import_stdlib"):
            full = info["from"] + (("." + rest) if rest else "")
            return {"call": call, "origin": "package" if k == "import_package" else "stdlib",
                    "package": info.get("package"), "qualified": full}
        if k == "builtin":
            return {"call": call, "origin": "builtin"}
        if k in ("local", "parameter", "global", "constant") and rest:
            return {"call": call, "origin": "method", "on": head}
        return {"call": call, "origin": k}

    def _fn_context(self, node, qual):
        a = node.args
        params = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
        if a.vararg:
            params.append(a.vararg.arg)
        if a.kwarg:
            params.append(a.kwarg.arg)
        local = set()
        stack = list(node.body)
        while stack:
            n = stack.pop()
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                local.add(n.name)
                continue
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                local.add(n.id)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for al in n.names:
                    local.add((al.asname or al.name).split(".")[0])
            elif isinstance(n, ast.arg):
                local.add(n.arg)
            stack.extend(ast.iter_child_nodes(n))
        return {"params": set(params), "locals": local - set(params), "qual": qual,
                "id": f"{self.mod}:{qual}"}

    def build(self):
        tree = ast.parse(self.src, filename=self.rel)
        self._walk(tree.body, scope=f"{self.mod}:<module>", fn=None, cls=None, parent=None, block=None, prefix="")
        return self

    def _walk(self, body, scope, fn, cls, parent, block, prefix):
        sids = []
        for i, stmt in enumerate(body):
            if i == 0 and _is_docstring(stmt):
                self.out.setdefault("_docstrings", {})[scope] = short(stmt.value.value.strip(), 400)
                continue
            sid = self._statement(stmt, scope, fn, cls, parent, block, prefix)
            sids.append(sid)
        return sids

    def _statement(self, stmt, scope, fn, cls, parent, block, prefix):
        start = min([stmt.lineno] + [d.lineno for d in getattr(stmt, "decorator_list", [])])
        sid = f"{self.rel}:{start}"
        k = 2
        while sid in self.out:
            sid = f"{self.rel}:{start}#{k}"
            k += 1
        blocks = _blocks(stmt)
        first_child = min((b[0].lineno for b in blocks.values() if b), default=None)
        if first_child is not None:
            # header ends on the last line before the body (or at the colon line for one-liners)
            own_end = max(stmt.lineno, first_child - 1) if first_child > stmt.lineno else stmt.lineno
        else:
            own_end = getattr(stmt, "end_lineno", stmt.lineno)
        kind = _stmt_kind(stmt, fn is None and cls is None)
        info = {"id": sid, "file": self.rel, "line": start, "end": own_end,
                "full_end": getattr(stmt, "end_lineno", own_end), "kind": kind, "scope": scope}
        if parent:
            info["parent"] = parent
            info["block"] = block
        # names and calls from the statement's own part
        reads, writes, mutates, calls = [], [], [], []
        comp_vars = set()
        for part in _header_parts(stmt):
            for n in ast.walk(part):
                if isinstance(n, ast.comprehension):
                    comp_vars.update(x.id for x in ast.walk(n.target) if isinstance(x, ast.Name))
        for part in _header_parts(stmt):
            for n in ast.walk(part):
                if isinstance(n, ast.Name):
                    (reads if isinstance(n.ctx, ast.Load) else writes).append(n.id)
                elif isinstance(n, (ast.Subscript, ast.Attribute)) and isinstance(n.ctx, ast.Store):
                    base = n
                    while isinstance(base, (ast.Subscript, ast.Attribute)):
                        base = base.value
                    if isinstance(base, ast.Name):
                        mutates.append(base.id)
        for part in _header_parts(stmt):
            for n in _calls_in_eval_order(part):
                d = dotted(n.func)
                if d and d not in calls:
                    calls.append(d)
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            writes.append(stmt.name)
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for al in stmt.names:
                writes.append((al.asname or al.name).split(".")[0])
        dedupe = lambda xs: list(dict.fromkeys(xs))
        reads = [x for x in dedupe(reads) if x not in comp_vars]
        writes = [x for x in dedupe(writes) if x not in comp_vars]
        mutates = dedupe(mutates)
        if reads:
            info["reads"] = reads[:30]
        if writes:
            info["writes"] = writes[:30]
        if mutates:
            info["mutates"] = mutates[:10]
        names = {}
        for n in (reads + writes + mutates)[:30]:
            r = self.resolve_name(n, fn)
            if r["kind"] != "unknown" or n not in writes:
                names[n] = r
        if names:
            info["names"] = names
        if calls:
            info["calls"] = [self.resolve_call(c, fn, cls) for c in calls[:20]]
        # project functions used as values (passed, stored, looped over) rather than called here
        called = {c.split(".")[0] for c in calls}
        refs = []
        for n in reads:
            if n in called:
                continue
            r = names.get(n) or self.resolve_name(n, fn)
            fid = r.get("id") if r.get("kind") in ("function", "import_project") and r.get("what", "function") == "function" else None
            if fid and fid in self.func_ids:
                refs.append(fid)
        if refs:
            info["references"] = refs
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            mods = []
            for imp in self.m.get("imports", []):
                if imp["line"] != stmt.lineno or imp["kind"] != "project":
                    continue
                cands = [imp["module"]] + [f"{imp['module']}.{x}" for x in imp["names"]]
                parts = imp["module"].split(".")
                cands = [".".join(parts[:i]) for i in range(1, len(parts))] + cands
                for c in cands:
                    if c and c in self.modules and c not in mods:
                        mods.append(c)
            if mods:
                info["imports_modules"] = mods
        # I/O visible in the source
        collector_info = {"calls": [], "io": [], "branches": [], "loops": [], "env": []}
        bc = BodyCollector(self.helper, collector_info)
        for part in _header_parts(stmt):
            bc.visit(part)
        if collector_info["io"]:
            info["io"] = collector_info["io"]
        # type hints and values
        if isinstance(stmt, ast.AnnAssign):
            info["hint"] = self.helper.seg(stmt.annotation, 80)
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            hints = {x.arg: self.helper.seg(x.annotation, 60) for x in stmt.args.posonlyargs + stmt.args.args + stmt.args.kwonlyargs if x.annotation}
            if stmt.returns is not None:
                hints["return"] = self.helper.seg(stmt.returns, 60)
            if hints:
                info["hints"] = hints
            info["defines"] = f"{self.mod}:{(fn['qual'] + '.<locals>.') if fn else (cls + '.') if cls else ''}{stmt.name}"
            doc = ast.get_docstring(stmt)
            if doc:
                info["doc"] = short(doc, 300)
            if _is_generator(stmt):
                info["generator"] = True
        if kind == "constant":
            info["value"] = literal_preview(stmt.value, self.src)["value"]
            if any(SECRET_NAME.search(w) for w in writes):
                info["value"] = "***"
        # comments on or just above the statement
        com = [self.comments[ln] for ln in range(start, own_end + 1) if ln in self.comments]
        ln = start - 1
        above = []
        while ln > 0 and ln in self.comments and self.lines[ln - 1].strip().startswith("#"):
            above.insert(0, self.comments[ln])
            ln -= 1
        if above or com:
            info["comments"] = (above + com)[:6]
        # grouping key for consecutive simple statements
        if kind in ("import", "constant"):
            info["group"] = kind
        elif kind == "assign" and not calls and _is_trivial_assign(stmt):
            info["group"] = "simple"
        elif kind in ("def", "class") and fn is None and cls is None:
            info["group"] = "definition"
        self.out[sid] = info
        self.order.append(sid)
        for ln in range(start, own_end + 1):
            self.line_map.setdefault(ln, sid)
        # children
        if blocks:
            child_fn, child_cls, child_scope = fn, cls, scope
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = (fn["qual"] + ".<locals>." if fn else (cls + "." if cls else "")) + stmt.name
                child_fn = self._fn_context(stmt, qual)
                child_scope = f"{self.mod}:{qual}"
            elif isinstance(stmt, ast.ClassDef):
                child_cls = ((cls + ".") if cls else "") + stmt.name
                child_scope = f"{self.mod}:{child_cls}"
            info["blocks"] = {}
            for bname, body in blocks.items():
                info["blocks"][bname] = self._walk(body, child_scope, child_fn, child_cls, sid, bname, prefix)
        return sid


def build_statements(project, modules, files):
    statements, by_file, line_maps, sources, docstrings = {}, {}, {}, {}, {}
    for m in files:
        if "_src" not in m:
            continue
        sm = StatementMapper(project, modules, m).build()
        docstrings.update(sm.out.pop("_docstrings", {}))
        statements.update(sm.out)
        by_file[m["path"]] = sm.order
        line_maps[m["path"]] = sm.line_map
        sources[m["path"]] = sm.src
    top = {path: [sid for sid in order if "parent" not in statements[sid]] for path, order in by_file.items()}
    return {"statements": statements, "top": top, "line_maps": line_maps, "sources": sources, "docstrings": docstrings}


def _is_within(stmts, sid, ancestor):
    s = stmts.get(sid)
    while s is not None and "parent" in s:
        if s["parent"] == ancestor:
            return s.get("block")
        s = stmts.get(s["parent"])
    return None


# ---------- line recording ----------

def _fingerprint(v):
    t = type(v)
    extra = None
    try:
        if isinstance(v, (list, dict, set, tuple, str, bytes, bytearray, frozenset)):
            extra = len(v)
        else:
            name = t.__name__
            if name in ("DataFrame", "Series", "ndarray") and (t.__module__ or "").startswith(("pandas", "numpy", "polars")):
                extra = tuple(v.shape)
    except Exception:
        pass
    return (id(v), t, extra)


_SKIP_TYPES = (type(sys), type(_fingerprint), type, type(print))
_NOT_STEPPED = {"<lambda>", "<genexpr>", "<listcomp>", "<dictcomp>", "<setcomp>"}


class LineRecorder:
    """Records each executed line of focused project code, with the variables it changed."""

    def __init__(self, project, focus):
        self.p = project
        self.focus = focus
        self.events = []
        self.counted_only = 0
        self.truncated = False
        self.totals = {}
        self.main = threading.main_thread().ident
        self._rel = {}
        self._focused = {}
        self.mutations = {}      # (file, line) -> names a statement changes in place, e.g. df.loc[...] = ...

    def set_statements(self, smap):
        self.mutations = {}
        for st in smap["statements"].values():
            if st.get("mutates"):
                for ln in range(st["line"], st["end"] + 1):
                    self.mutations[(st["file"], ln)] = st["mutates"]

    def focused(self, code):
        key = (code.co_filename, code.co_firstlineno, code.co_name)
        hit = self._focused.get(key)
        if hit is None:
            q = getattr(code, "co_qualname", code.co_name)
            is_class_body = not (code.co_flags & 0x3) and code.co_name != "<module>"
            hit = self._focused[key] = (code.co_name not in _NOT_STEPPED and not is_class_body
                                        and self.focus.matches(code.co_filename, q))
        return hit

    def rel(self, filename):
        r = self._rel.get(filename)
        if r is None:
            r = self._rel[filename] = self.p.rel(os.path.abspath(filename))
        return r

    def _snap(self, frame):
        out = {}
        try:
            loc = frame.f_locals
        except Exception:
            return out
        for k, v in list(loc.items()):
            if k.startswith("__") or isinstance(v, _SKIP_TYPES):
                continue
            out[k] = _fingerprint(v)
        return out

    def _diff(self, frame, old, new):
        changes = {}
        loc = None
        for k, fp in new.items():
            if old.get(k) != fp:
                if loc is None:
                    loc = frame.f_locals
                if k in loc:
                    changes[k] = summarize(loc[k], name=k)
        for k in old:
            if k not in new:
                changes[k] = {"type": "deleted"}
        return changes

    def new_state(self):
        return {"ev": None, "snap": None, "counts": {}, "stale": True}

    def on_line(self, tracer, entry, frame, line):
        st = entry[4]
        if st is None:
            return
        filename = frame.f_code.co_filename
        if st["ev"] is not None:
            self._complete(st, frame)
        rel = self.rel(filename)
        key = (rel, line)
        self.totals[key] = self.totals.get(key, 0) + 1
        c = st["counts"][line] = st["counts"].get(line, 0) + 1
        node = entry[1]
        if node is None or c > DETAIL_PER_PARENT or len(self.events) >= MAX_LINE_EVENTS:
            if node is not None and len(self.events) >= MAX_LINE_EVENTS:
                self.truncated = True
            self.counted_only += 1
            st["stale"] = True
            return
        ev = {"seq": len(self.events) + 1, "node": node["id"], "file": rel, "line": line, "occ": c,
              "t_ms": round((time.perf_counter() - tracer.t0) * 1000, 3)}
        if st["stale"]:
            new = self._snap(frame)
            if st["snap"] is not None:
                unrec = self._diff(frame, st["snap"], new)
                if unrec:
                    ev["changes_unrecorded"] = unrec
            st["snap"] = new
            st["stale"] = False
        self.events.append(ev)
        st["ev"] = ev

    def _complete(self, st, frame):
        new = self._snap(frame)
        ch = self._diff(frame, st["snap"] or {}, new)
        ev = st["ev"]
        forced = self.mutations.get((ev["file"], ev["line"]))
        if forced:
            loc = frame.f_locals
            for k in forced:
                if k not in ch and k in loc:
                    ch[k] = dict(summarize(loc[k], name=k), in_place=True)
        if ch:
            st["ev"]["changes"] = ch
        st["snap"] = new
        st["ev"] = None

    def finish(self, entry, frame, exc):
        st = entry[4]
        if st is None:
            return
        if st["ev"] is not None:
            ev = st["ev"]
            if frame is not None:
                self._complete(st, frame)
            if exc is not None:
                ev["raised"] = f"{type(exc).__name__}: {short(redact(str(exc)), 200)}"
        if entry[1] is not None and st["counts"]:
            entry[1]["line_counts"] = {str(k): v for k, v in st["counts"].items()}

    def report(self):
        return {"events": self.events,
                "totals": [{"file": f, "line": ln, "count": n} for (f, ln), n in sorted(self.totals.items())],
                "stats": {"recorded": len(self.events), "counted_only": self.counted_only, "max_events": MAX_LINE_EVENTS},
                "truncated": self.truncated,
                "note": f"The first {DETAIL_PER_PARENT} executions of each line in each call are recorded with the "
                        "variables they changed; later executions are counted. In-place changes that keep a "
                        "value's identity, type and size are not detected."}


# ---------- plan ----------

def _merge_changes(a, b):
    out = dict(a or {})
    out.update(b or {})
    return out


def _rank_statements(steps, stmts, max_steps):
    score, first = {}, {}
    for i, s in enumerate(steps):
        for sid in s.get("stmts") or ([s["stmt"]] if s.get("stmt") else []):
            st = stmts.get(sid, {})
            v = 1
            if st.get("kind") in ("if", "while", "match"):
                v = 4
            if st.get("kind") in ("for", "while"):
                v = max(v, 3)
            if any(c.get("origin") == "project" for c in st.get("calls", [])):
                v = max(v, 4)
            if st.get("io"):
                v = max(v, 4)
            if st.get("kind") == "return":
                v = max(v, 3)
            ch = s.get("changes") or {}
            if any(isinstance(x, dict) and ("rows" in x or "shape" in x or (x.get("len") and x.get("type") != "str"))
                   for x in ch.values()):
                v = max(v, 5)
            elif ch:
                v = max(v, 2)
            if s.get("raised"):
                v = 6
            if st.get("kind") in ("import", "constant", "pass", "scope"):
                v = min(v, 1)
            score[sid] = max(score.get(sid, 0), v)
            first.setdefault(sid, i)
    ranked = sorted(score, key=lambda k: (-score[k], first[k]))
    return ranked[:max_steps]


def _group_steps(steps, stmts):
    """Merge consecutive simple statements of the same kind, in the same call and block."""
    out = []
    for s in steps:
        prev = out[-1] if out else None
        st = stmts.get(s.get("stmt"), {})
        g = st.get("group")
        if (prev and g and s["type"] == "statement" and prev["type"] in ("statement", "group")
                and prev.get("call") == s.get("call") and prev.get("_group") == g
                and stmts.get(prev["stmts"][-1] if prev["type"] == "group" else prev["stmt"], {}).get("parent") == st.get("parent")
                and not s.get("raised")):
            if prev["type"] == "statement":
                prev["type"] = "group"
                prev["stmts"] = [prev.pop("stmt")]
                prev.pop("occurrence", None)
            prev.setdefault("_aliases", []).append(s.get("_key"))
            prev["stmts"].append(s["stmt"])
            prev["lines"] = [prev["lines"][0], max(prev["lines"][1], s["lines"][1])]
            if s.get("changes"):
                prev["changes"] = _merge_changes(prev.get("changes"), s["changes"])
            for k in ("io", "unfocused_calls"):
                if s.get(k):
                    prev.setdefault(k, []).extend(s[k])
            continue
        s["_group"] = g if s["type"] == "statement" else None
        out.append(s)
    for s in out:
        s.pop("_group", None)
    return out


def _finalize_plan(steps, stmts, mode, focus, max_steps, extra=None):
    truncated = len(steps) > MAX_PLAN_STEPS
    steps = steps[:MAX_PLAN_STEPS]
    idmap = {}
    for i, s in enumerate(steps, 1):
        s["id"] = f"s{i}"
        for k in [s.get("_key")] + s.get("_aliases", []):
            if k:
                idmap[k] = s["id"]
    for s in steps:   # links between steps use internal keys until now
        for k in ("hidden_by", "from_step", "to_step", "changes_of"):
            if s.get(k):
                s[k] = idmap.get(s[k])
        if s.get("see"):
            s["see"] = [idmap.get(x) for x in s["see"] if x]
        s.pop("_key", None)
        s.pop("_aliases", None)
        for k in [k for k, v in s.items() if v is None]:
            del s[k]
    plan = {"view": "walkthrough", "mode": mode, "focus": focus.describe(), "max_steps": max_steps,
            "steps": steps, "explain_first": _rank_statements([s for s in steps if not s.get("hidden_by")], stmts, max_steps),
            "truncated": truncated,
            "counts": {"steps": len(steps), "visible_steps": sum(1 for s in steps if not s.get("hidden_by")),
                       "statements": len({x for s in steps for x in (s.get("stmts") or [s.get("stmt")]) if x})}}
    if extra:
        plan.update(extra)
    return plan


def build_plan_run(project, modules, smap, tracer, lines, io_report, focus, max_steps):
    stmts, line_maps = smap["statements"], smap["line_maps"]
    nodes = {n["id"]: n for n in tracer.nodes}
    class_ids = {st["defines"] for st in stmts.values() if st.get("kind") == "class" and st.get("defines")}
    focused_node = {nid: focus.matches_fid(n["fn"], modules) and not n["fn"].endswith(tuple(_NOT_STEPPED))
                    and n["fn"] not in class_ids for nid, n in nodes.items()}

    def depth(nid):
        d, n = 0, nodes.get(nid)
        while n and n.get("parent"):
            n = nodes.get(n["parent"])
            if n and focused_node.get(n["id"]):
                d += 1
        return d

    def chain(nid):
        out, n = [], nodes.get(nid)
        while n:
            out.append(n["id"])
            n = nodes.get(n.get("parent"))
        return out[::-1]

    # map line events to statements; merge consecutive events of the same statement in the same call
    merged = []
    for ev in lines.events:
        sid = line_maps.get(ev["file"], {}).get(ev["line"])
        if sid is None:
            continue
        last = merged[-1] if merged else None
        if last and last["node"] == ev["node"] and last["stmt"] == sid:
            last["changes"] = _merge_changes(last.get("changes"), ev.get("changes"))
            if ev.get("raised"):
                last["raised"] = ev["raised"]
            last["end_seq"] = ev["seq"]
            continue
        merged.append({"stmt": sid, "node": ev["node"], "occ": ev["occ"], "t_ms": ev["t_ms"], "seq": ev["seq"],
                       "changes": ev.get("changes"), "changes_unrecorded": ev.get("changes_unrecorded"),
                       "raised": ev.get("raised")})
    occ = {}
    for e in merged:   # occurrence of each statement within its call
        k = (e["node"], e["stmt"])
        occ[k] = e["occ"] = occ.get(k, 0) + 1
    # drop header events that only mark the end of a block: a loop's final check, a with-statement's exit
    keep = []
    for i, e in enumerate(merged):
        st = stmts[e["stmt"]]
        if st["kind"] in ("for", "while") and e["occ"] > 1:
            nxt = next((x for x in merged[i + 1:] if x["node"] == e["node"]), None)
            if not nxt or _is_within(stmts, nxt["stmt"], e["stmt"]) is None:
                continue
        if st["kind"] == "with":
            prv = next((x for x in reversed(keep) if x["node"] == e["node"]), None)
            if prv and _is_within(stmts, prv["stmt"], e["stmt"]) is not None:
                continue
        keep.append(e)
    merged = keep

    # time window of each event in its call, for I/O and unfocused calls
    nxt_t = {}
    last_in_node = {}
    for i in range(len(merged) - 1, -1, -1):
        e = merged[i]
        nxt_t[i] = last_in_node.get(e["node"])
        last_in_node[e["node"]] = e["t_ms"]
    io_by_node = {}
    for ev in io_report.get("events", []):
        if ev.get("node") is not None:
            io_by_node.setdefault(ev["node"], []).append(ev)
    children = {}
    for n in tracer.nodes:
        children.setdefault(n.get("parent"), []).append(n)

    def node_end(nid):
        n = nodes[nid]
        return n["t_ms"] + (n.get("dur_ms") or 0)

    steps = []
    last_step_in_node = {}
    changes_holder = {}          # statement step key -> the step that currently shows its changes
    prev_node = None
    root_node = None

    def emit(step):
        step["_key"] = f"k{len(steps)}"
        steps.append(step)
        return step

    for i, e in enumerate(merged):
        nid = e["node"]
        if prev_node is None:
            root_node = nid
            n = nodes[nid]
            if not n["fn"].endswith(":<module>") or n.get("parent"):
                parent = nodes.get(n.get("parent"))
                emit({"type": "enter", "fn": n["fn"], "call": nid, "depth": depth(nid),
                      "caller": parent["fn"] if parent else None, "args": n.get("args")})
        elif nid != prev_node:
            a, b = chain(prev_node), chain(nid)
            k = 0
            while k < min(len(a), len(b)) and a[k] == b[k]:
                k += 1
            for pop in reversed(a[k:]):
                if not focused_node.get(pop):
                    continue
                n = nodes[pop]
                parent = nodes.get(n.get("parent"))
                to_step = None
                p = n.get("parent")
                while p is not None and to_step is None:
                    to_step = last_step_in_node.get(p)
                    p = nodes[p].get("parent") if p in nodes else None
                r = emit({"type": "return", "fn": n["fn"], "call": pop, "depth": depth(pop),
                          "to": parent["fn"] if parent else None, "to_step": to_step["_key"] if to_step else None,
                          "value": n.get("yielded", n.get("ret")), "raised": n.get("raised"),
                          "yield": True if "yielded" in n else None})
                if to_step is not None and to_step["type"] == "statement":
                    holder = changes_holder.get(to_step["_key"], to_step)
                    if holder.get("changes"):
                        r["changes"] = holder.pop("changes")
                        r["changes_of"] = to_step["_key"]
                    changes_holder[to_step["_key"]] = r
            for push in b[k:]:
                if not focused_node.get(push):
                    continue
                n = nodes[push]
                parent = nodes.get(n.get("parent"))
                site = None
                p = n.get("parent")
                while p is not None and site is None:
                    site = last_step_in_node.get(p)
                    p = nodes[p].get("parent") if p in nodes else None
                emit({"type": "enter", "fn": n["fn"], "call": push, "depth": depth(push),
                      "caller": parent["fn"] if parent else None, "from_step": site["_key"] if site else None,
                      "args": n.get("args")})
        st = stmts[e["stmt"]]
        step = {"type": "statement", "stmt": e["stmt"], "file": st["file"], "lines": [st["line"], st["end"]],
                "call": nid, "depth": depth(nid), "occurrence": e["occ"]}
        if e.get("changes") and st["kind"] not in ("import", "def", "class"):
            used = set(st.get("reads", [])) | set(st.get("writes", [])) | set(st.get("mutates", []))
            e["changes"] = {k: v for k, v in e["changes"].items() if k in used} or None
        n = nodes[nid]
        total = (n.get("line_counts") or {}).get(str(st["line"]))
        if total:
            step["executions"] = total
        for k2 in ("changes", "changes_unrecorded", "raised"):
            if e.get(k2):
                step[k2] = e[k2]
        t_end = nxt_t[i] if nxt_t[i] is not None else node_end(nid)
        evs = [x for x in io_by_node.get(nid, []) if x.get("t_ms") is not None and e["t_ms"] <= x["t_ms"] <= t_end]
        if evs:
            step["io"] = [{k3: x[k3] for k3 in ("seq", "kind", "op", "target", "handled", "rows", "count") if x.get(k3) is not None} for x in evs]
        if st["kind"] == "return" and n.get("ret") is not None:
            step["value"] = n["ret"]
        if st["kind"] == "yield" and n.get("yielded") is not None:
            step["value"] = n["yielded"]
        emit(step)
        last_step_in_node[nid] = step
        # calls into code outside the focus, made while this statement ran
        if not focus.all:
            for c in children.get(nid, []):
                if not focused_node.get(c["id"]) and e["t_ms"] <= c["t_ms"] <= t_end:
                    emit({"type": "unfocused_call", "fn": c["fn"], "call": c["id"], "depth": depth(nid) + 1,
                          "from_step": step["_key"], "args": c.get("args"), "value": c.get("ret"),
                          "raised": c.get("raised"), "repeats": (n.get("repeats") or {}).get(c["fn"])})
        prev_node = nid
    if prev_node is not None:
        for pop in reversed(chain(prev_node)):
            if not focused_node.get(pop) or (nodes[pop]["fn"].endswith(":<module>") and not nodes[pop].get("parent")):
                break
            n = nodes[pop]
            to_step, p = None, n.get("parent")
            while p is not None and to_step is None:
                to_step = last_step_in_node.get(p)
                p = nodes[p].get("parent") if p in nodes else None
            emit({"type": "return", "fn": n["fn"], "call": pop, "depth": depth(pop), "value": n.get("ret"),
                  "raised": n.get("raised"), "to": nodes[n["parent"]]["fn"] if n.get("parent") in nodes else None,
                  "to_step": to_step["_key"] if to_step else None})

    # branches: which side ran
    for i, s in enumerate(steps):
        if s["type"] != "statement" or stmts[s["stmt"]]["kind"] not in ("if", "match"):
            continue
        nxt = next((x for x in steps[i + 1:] if x.get("call") == s["call"] and x["type"] == "statement"), None)
        side = _is_within(stmts, nxt["stmt"], s["stmt"]) if nxt else None
        s["branch"] = {"taken": side or "none"}

    # loops with more than 3 iterations: first iteration in full, then a summary
    out, i = [], 0
    while i < len(steps):
        s = steps[i]
        st = stmts.get(s.get("stmt"), {})
        if s["type"] == "statement" and st.get("kind") in ("for", "while") and s.get("occurrence") == 1:
            body_first = (st.get("blocks") or {}).get("body", [None])[0]
            n = nodes[s["call"]]
            iters = (n.get("line_counts") or {}).get(str(stmts[body_first]["line"])) if body_first else None
            # the loop instance: steps until the next statement of this call outside the loop
            j = i + 1
            starts = [i]
            while j < len(steps):
                x = steps[j]
                if x.get("call") == s["call"] and x["type"] == "statement":
                    if x["stmt"] == s["stmt"]:
                        starts.append(j)
                    elif _is_within(stmts, x["stmt"], s["stmt"]) is None:
                        break
                j += 1
            s["loop"] = {"iterations": iters or 0}
            if iters and iters > DETAIL_PER_PARENT and len(starts) > 1:
                out.extend(steps[i:starts[1]])
                after = steps[j] if j < len(steps) else None
                summary = {"type": "loop_summary", "stmt": s["stmt"], "file": s["file"], "lines": s["lines"],
                           "call": s["call"], "depth": s["depth"], "iterations": iters,
                           "detailed_iterations": len(starts), "_key": f"loop{i}"}
                # combined effect of iterations 2+: latest value of each variable the loop changed
                combined = {}
                for x in steps[starts[1]:j]:
                    if x.get("call") == s["call"]:
                        combined.update(x.get("changes_unrecorded") or {})
                        combined.update(x.get("changes") or {})
                if after is not None and after.get("call") == s["call"] and after.get("changes_unrecorded"):
                    combined.update(after.pop("changes_unrecorded"))
                combined = {k: v for k, v in combined.items() if v.get("type") != "deleted"}
                if combined:
                    summary["changes"] = combined
                out.append(summary)
                for x in steps[starts[1]:j]:
                    x["hidden_by"] = summary["_key"]
                    out.append(x)
                i = j
                continue
        out.append(s)
        i += 1
    steps = _group_steps(out, stmts)
    return _finalize_plan(steps, stmts, "run", focus, max_steps,
                          {"line_stats": lines.report()["stats"], "lines_truncated": lines.truncated})


def build_plan_scan(project, modules, smap, focus, max_steps, entry_module):
    stmts, top = smap["statements"], smap["top"]
    funcs = {}
    for sid, st in stmts.items():
        if st.get("defines"):
            funcs[st["defines"]] = sid
    steps, visited, visited_mods = [], set(), set()
    first_step_of_fn = {}
    in_scope = {m["name"] for m in focus.files_in_scope(modules)}

    def emit(step):
        step["_key"] = f"k{len(steps)}"
        steps.append(step)
        return step

    def walk(sids, depth, possible, repeats):
        for sid in sids:
            st = stmts[sid]
            step = {"type": "statement", "stmt": sid, "file": st["file"], "lines": [st["line"], st["end"]], "depth": depth}
            if possible:
                step["possible"] = True
            if repeats:
                step["repeats"] = True
            emit(step)
            for mod in st.get("imports_modules", []):
                if mod in visited_mods or mod not in in_scope:
                    continue
                visited_mods.add(mod)
                mm = modules[mod]
                body = top.get(mm["path"], [])
                if body:
                    emit({"type": "enter", "fn": f"{mod}:<module>", "depth": depth + 1, "from_step": step["_key"],
                          "via": "import"})
                    walk(body, depth + 1, False, False)
                    emit({"type": "return", "fn": f"{mod}:<module>", "depth": depth + 1, "to_step": step["_key"]})
            targets = [(c.get("id"), None) for c in st.get("calls", []) if c.get("origin") == "project"]
            targets += [(fid, "reference") for fid in st.get("references", [])]
            for fid, via in targets:
                if not fid or fid not in funcs:
                    continue
                if not focus.matches_fid(fid, modules):
                    emit({"type": "unfocused_call", "fn": fid, "depth": depth + 1, "from_step": step["_key"]})
                elif fid in visited:
                    step.setdefault("see", []).append(fid)
                else:
                    enter_fn(fid, depth + 1, step["_key"], via)
            if st["kind"] in ("def", "class") or "blocks" not in st:
                continue
            for bname, body in st["blocks"].items():
                branchy = st["kind"] in ("if", "match", "try") and bname != "body" or st["kind"] in ("if", "match")
                walk(body, depth, possible or branchy, repeats or st["kind"] in ("for", "while"))
            if st["kind"] in ("if", "match"):
                step["branch"] = {"taken": "possible"}
            if st["kind"] in ("for", "while"):
                step["loop"] = {"iterations": None}

    def enter_fn(fid, depth, from_key, via=None):
        visited.add(fid)
        def_sid = funcs[fid]
        e = emit({"type": "enter", "fn": fid, "depth": depth, "from_step": from_key, "def_stmt": def_sid, "via": via})
        first_step_of_fn[fid] = e["_key"]
        walk(stmts[def_sid].get("blocks", {}).get("body", []), depth, False, False)
        emit({"type": "return", "fn": fid, "depth": depth, "to_step": from_key})

    entry_m = modules.get(entry_module)
    if entry_m and (focus.all or entry_m["_abspath"] in focus.files):
        visited_mods.add(entry_module)
        walk(top.get(entry_m["path"], []), 0, False, False)
    # focused code not reached from the entry's flow
    for m in focus.files_in_scope(modules):
        if m["name"] == entry_module:
            continue
        if not focus.all and m["_abspath"] in focus.files and m["name"] not in visited_mods:
            mod_sids = [s for s in top.get(m["path"], [])]
            if mod_sids:
                emit({"type": "enter", "fn": f"{m['name']}:<module>", "depth": 0, "from_step": None})
                walk(mod_sids, 0, False, False)
    for fid, def_sid in funcs.items():
        if fid not in visited and focus.matches_fid(fid, modules) and not focus.all and "<locals>" not in fid:
            enter_fn(fid, 0, None)
    # 'see' points at the first step of a function already walked through
    for s in steps:
        if "see" in s:
            s["see"] = [first_step_of_fn.get(f) for f in s["see"]]
    steps = _group_steps(steps, stmts)
    return _finalize_plan(steps, stmts, "scan", focus, max_steps)


# ----------------------------------------------------------------------------
# Bundle assembly
# ----------------------------------------------------------------------------

def function_source(m, f):
    lines = m["_src"][f["line"] - 1: f["end"]]
    return "\n".join(lines)


def attach_sources(modules, wanted, budget):
    """Full source for important functions within a character budget; signatures for the rest."""
    used = 0
    priority = []
    for m in modules.values():
        for f in (m.get("functions") or {}).values():
            if f["id"] in wanted:
                priority.append((wanted[f["id"]], f["line"], m, f))
    priority.sort(key=lambda x: (x[0], x[1]))
    trimmed = 0
    for _, _, m, f in priority:
        src = function_source(m, f)
        if used + len(src) <= budget:
            f["source"] = src
            used += len(src)
        else:
            f["source"] = m["_src"][f["line"] - 1].strip() + "\n    ..."
            f["source_trimmed"] = True
            trimmed += 1
    # top-level code of each module (non-function lines), entry first
    for m in sorted(modules.values(), key=lambda m: m.get("main_flow") is None):
        if "_src" not in m:
            continue
        covered = set()
        for f in (m.get("functions") or {}).values():
            covered.update(range(f["line"], f["end"] + 1))
        for c in (m.get("classes") or {}).values():
            covered.update(range(c["line"], c["end"] + 1))
        top = [f"{i + 1}: {ln}" for i, ln in enumerate(m["_src"]) if (i + 1) not in covered and ln.strip()]
        text = "\n".join(top[:300])
        if used + len(text) <= budget or m.get("main_flow") is not None:
            m["module_code"] = text
            used += len(text)
    return used, trimmed


def finalize_modules(modules):
    out = {}
    for name, m in modules.items():
        m = {k: v for k, v in m.items() if not k.startswith("_")}
        m.pop("names", None)
        for f in (m.get("functions") or {}).values():
            for k in ("calls", "io", "branches", "loops", "env", "decorators"):
                if not f.get(k):
                    f.pop(k, None)
            for k in ("doc", "returns", "class"):
                if f.get(k) is None:
                    f.pop(k, None)
            if not f.get("async"):
                f.pop("async", None)
        out[name] = m
    return out


def import_summary(modules):
    libs = {}
    for m in modules.values():
        for imp in m.get("imports", []):
            if imp["kind"] == "project":
                continue
            top = imp["module"].split(".")[0]
            e = libs.setdefault(top, {"name": top, "kind": imp["kind"], "used_by": []})
            if m["name"] not in e["used_by"]:
                e["used_by"].append(m["name"])
    return sorted(libs.values(), key=lambda x: (x["kind"], x["name"]))


def write_json(obj, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False, default=str)


# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------

def walkthrough_sections(smap, plan, focus, budget):
    """Bundle sections added by --view walkthrough."""
    size = sum(len(x) for x in smap["sources"].values())
    if size > max(budget, 1):
        raise SystemExit(f"The code in focus is {size:,} characters, over the budget of {budget:,}. "
                         "Narrow it with --focus (a file or function), or raise --budget.")
    return {"view": "walkthrough", "focus": focus.describe(), "sources": smap["sources"],
            "statements": smap["statements"], "docstrings": smap["docstrings"], "plan": plan}


def _walk_log(plan):
    c = plan["counts"]
    log(f"walkthrough: {c['visible_steps']} steps ({c['steps']} including hidden loop iterations) "
        f"over {c['statements']} statements; {len(plan['explain_first'])} suggested for explanation")
    if plan.get("truncated") or plan.get("lines_truncated"):
        log("warning: the walkthrough was cut short by a size limit; narrow it with --focus")


def cmd_scan(a):
    project = Project(a.entry, a.root, a.module)
    log(f"scanning {project.rel(project.entry)} (project root: {project.root})")
    modules = analyze_project(project)
    wanted = {}
    for m in modules.values():
        for f in (m.get("functions") or {}).values():
            d = f.get("reach_depth")
            wanted[f["id"]] = d if d is not None else 99
    used, trimmed = attach_sources(modules, wanted, a.budget)
    fns = sum(len(m.get("functions") or {}) for m in modules.values())
    unreached = sorted(f["id"] for m in modules.values() for f in (m.get("functions") or {}).values()
                       if f.get("reach_depth") is None and not f["name"].startswith("__"))
    walk = None
    if a.view == "walkthrough":
        focus = Focus(project, modules, a.focus)
        smap = build_statements(project, modules, focus.files_in_scope(modules))
        plan = build_plan_scan(project, modules, smap, focus, a.max_steps, project.entry_module)
        walk = walkthrough_sections(smap, plan, focus, a.budget)
        _walk_log(plan)
    bundle = {
        "schema": BUNDLE_SCHEMA, "tool_version": VERSION, "mode": "scan", "created": now_iso(),
        "entry": project.label(), "entry_module": project.entry_module,
        "root": os.path.basename(project.root) or project.root,
        "python": sys.version.split()[0],
        "libraries": import_summary(modules),
        "modules": finalize_modules(modules),
        "unreached_functions": unreached,
        "notes": [
            "Static scan: nothing was executed. Order follows the source; branches are possibilities.",
            "Functions called dynamically (getattr, registries, config-driven dispatch) may be missing.",
        ],
        "budget": {"chars_used": used, "functions_trimmed": trimmed},
    }
    if walk:
        bundle.update(walk)
    write_json(bundle, a.out)
    log(f"{len(modules)} modules, {fns} functions -> {a.out} ({os.path.getsize(a.out) // 1024} KB)")
    _next_steps(a.out)


def cmd_run(a, script_args):
    project = Project(a.entry, a.root, a.module)
    sandbox = tempfile.mkdtemp(prefix="codestory_")
    project.sandbox = sandbox
    log(f"static scan of {project.rel(project.entry)}")
    modules = analyze_project(project)

    mode_txt = "LIVE (side effects are real)" if a.live else "safe mode (writes go to the sandbox)"
    log(f"running {project.label()} {' '.join(script_args)}  [{mode_txt}]")
    if not a.live:
        log(f"sandbox: {sandbox}")
    focus = lines = None
    if a.view == "walkthrough":
        focus = Focus(project, modules, a.focus)
        lines = LineRecorder(project, focus)
        lines.set_statements(build_statements(project, modules, focus.files_in_scope(modules)))
        log(f"recording line by line ({'whole program' if focus.all else a.focus}); this run will be slower than usual")
    tracer = Tracer(project, lines=lines)
    watcher = IOWatcher(project, tracer, sandbox, safe=not a.live, allow_subprocess=a.allow_subprocess)

    old_argv, old_path = sys.argv[:], sys.path[:]
    sys.argv = [project.entry] + list(script_args)
    sys.path.insert(0, project.entry_dir)
    if project.root not in sys.path:
        sys.path.insert(1, project.root)
    outcome = {"status": "ok"}
    globals_after = None
    started = now_iso()
    watcher.install()
    tracer.start()
    t_start = time.perf_counter()
    try:
        if project.module:
            globals_after = runpy.run_module(project.module, run_name="__main__", alter_sys=True)
        else:
            globals_after = runpy.run_path(project.entry, run_name="__main__")
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) or e.code is None else 1
        outcome = {"status": "ok" if not code else "exit", "exit_code": code or 0}
        if e.code not in (None, 0) and not isinstance(e.code, int):
            outcome["message"] = short(redact(str(e.code)), 300)
    except BaseException as e:  # noqa: BLE001 - we report every failure
        tb = traceback.extract_tb(e.__traceback__)
        frames = [{"file": project.rel(fr.filename), "line": fr.lineno, "function": fr.name,
                   "code": short(redact(fr.line or ""), 160)}
                  for fr in tb if project.is_project_file(fr.filename)]
        outcome = {"status": "error", "error": f"{type(e).__name__}: {short(redact(str(e)), 400)}", "traceback": frames}
    finally:
        elapsed = (time.perf_counter() - t_start) * 1000
        tracer.stop()
        watcher.uninstall()
        sys.argv, sys.path[:] = old_argv, old_path
    outcome["duration_ms"] = round(elapsed, 1)

    # modules discovered only at runtime (dynamic imports)
    seen_paths = {m["_abspath"] for m in modules.values() if "_abspath" in m}
    extra = []
    for mod in list(sys.modules.values()):
        f = getattr(mod, "__file__", None)
        if f and project.is_project_file(f) and os.path.abspath(f) not in seen_paths and f.endswith(".py"):
            extra.append(os.path.abspath(f))
    if extra:
        more = analyze_project(project, extra)
        for k, v in more.items():
            modules.setdefault(k, v)

    # runtime values of constants
    runtime_consts = {}
    for name, m in modules.items():
        g = globals_after if m.get("main_flow") is not None else None
        if g is None:
            mod = sys.modules.get(name)
            g = getattr(mod, "__dict__", None) if mod else None
        if not g:
            continue
        for c in m.get("constants", []):
            if c["name"] in g and not c.get("redacted"):
                runtime_consts[f"{name}.{c['name']}"] = summarize(g[c["name"]], name=c["name"])

    # source priority: executed functions by call depth, then everything else
    depth, wanted = {}, {}
    for n in tracer.nodes:
        d = depth[n["id"]] = depth[n["parent"]] + 1 if n["parent"] in depth else 0
        wanted[n["fn"]] = min(wanted.get(n["fn"], d), d)
    for m in modules.values():
        for f in (m.get("functions") or {}).values():
            wanted.setdefault(f["id"], 50 if f["id"] in tracer.stats else 99)
    used, trimmed = attach_sources(modules, wanted, a.budget)

    for m in modules.values():
        for f in (m.get("functions") or {}).values():
            s = tracer.stats.get(f["id"])
            f["executed"] = bool(s)
            if s:
                f["runtime"] = {"calls": s["calls"], "total_ms": round(s["total_ms"], 2)}
            for b in f.get("branches", []):
                b["note"] = "see trace to infer which side ran" if s else "function did not run"

    io_report = watcher.report()
    walk = None
    if lines is not None:
        smap = build_statements(project, modules, focus.files_in_scope(modules))
        plan = build_plan_run(project, modules, smap, tracer, lines, io_report, focus, a.max_steps)
        walk = walkthrough_sections(smap, plan, focus, a.budget)
        walk["lines"] = lines.report()
        _walk_log(plan)
    bundle = {
        "schema": BUNDLE_SCHEMA, "tool_version": VERSION, "mode": "run", "created": now_iso(),
        "entry": project.label(), "entry_module": project.entry_module,
        "root": os.path.basename(project.root) or project.root,
        "python": sys.version.split()[0],
        "run": {"started_at": started, "args": [redact(x) for x in script_args],
                "safe_mode": not a.live, "sandbox": sandbox if not a.live else None, **outcome},
        "libraries": import_summary(modules),
        "modules": finalize_modules(modules),
        "runtime_constants": runtime_consts,
        "trace": {"nodes": tracer.nodes, "function_stats": {k: {"calls": v["calls"], "total_ms": round(v["total_ms"], 2)}
                                                            for k, v in tracer.stats.items()},
                  "truncated": tracer.truncated,
                  "note": f"The first {DETAIL_PER_PARENT} calls of a function under the same parent are kept in detail; "
                          "further calls are counted in the parent's 'repeats'."},
        "io": io_report,
        "unexecuted_functions": sorted(f["id"] for m in modules.values() for f in (m.get("functions") or {}).values()
                                       if not f.get("executed") and not f["name"].startswith("__")),
        "budget": {"chars_used": used, "functions_trimmed": trimmed},
    }
    if walk:
        bundle.update(walk)
    write_json(bundle, a.out)

    log(f"finished: {outcome['status']} in {outcome['duration_ms'] / 1000:.2f}s; "
        f"{len(tracer.stats)} project functions ran, {len(io_report['events'])} I/O events")
    if io_report["intercepted"]:
        log(f"safe mode intercepted {len(io_report['intercepted'])} side effect(s); outputs are in {sandbox}")
    for e in io_report["real_effects"]:
        log(f"REAL side effect: {e['kind']} {e['op']} {e['target']}")
    for lib in io_report["not_intercepted_libraries"]:
        log(f"warning: {lib['library']} was used - {lib['what']} are not intercepted by safe mode")
    if outcome["status"] == "error":
        log(f"program raised {outcome['error']}")
    log(f"bundle -> {a.out} ({os.path.getsize(a.out) // 1024} KB)")
    _next_steps(a.out)


def _next_steps(out):
    log("next: give this bundle to your assistant with the codestory skill to get storyboard.json,")
    log("      then: python codestory.py build storyboard.json -o story.html")


def validate_storyboard(sb):
    problems = []
    if not isinstance(sb, dict):
        return ["storyboard must be a JSON object"]
    if sb.get("schema") != STORYBOARD_SCHEMA:
        problems.append(f"'schema' should be '{STORYBOARD_SCHEMA}'")
    for k in ("title", "mode", "scenes"):
        if k not in sb:
            problems.append(f"missing '{k}'")
    phases = {"setup", "imports", "constants", "definitions", "input", "transform", "branch", "output", "finish", "error"}
    ids = set()

    def walk(scenes, path):
        if not isinstance(scenes, list):
            problems.append(f"{path} must be a list")
            return
        for i, s in enumerate(scenes):
            p = f"{path}[{i}]"
            if not isinstance(s, dict):
                problems.append(f"{p} must be an object")
                continue
            for k in ("id", "phase", "title"):
                if k not in s:
                    problems.append(f"{p} missing '{k}'")
            if s.get("phase") not in phases:
                problems.append(f"{p} has unknown phase '{s.get('phase')}'")
            if s.get("id") in ids:
                problems.append(f"{p} duplicate id '{s.get('id')}'")
            ids.add(s.get("id"))
            if s.get("children"):
                walk(s["children"], p + ".children")
    walk(sb.get("scenes", []), "scenes")
    return problems


WALKTHROUGH_SCHEMA = "codestory.walkthrough/1"
PAYLOAD_SCHEMA = "codestory.walkthrough-payload/1"


def _embed(html, player_path, placeholder_id, data):
    """Put the data and the shared engine into a player, so the result is one self-contained file."""
    engine_tag = '<script src="engine.js"></script>'
    engine_path = os.path.join(os.path.dirname(player_path), "engine.js")
    if engine_tag in html:
        if not os.path.isfile(engine_path):
            raise SystemExit(f"engine.js not found next to {player_path}")
        with open(engine_path, encoding="utf-8") as fh:
            html = html.replace(engine_tag, "<script>" + fh.read().replace("</script", "<\\/script") + "</script>", 1)
    placeholder = f'<script id="{placeholder_id}" type="application/json">null</script>'
    if placeholder not in html:
        raise SystemExit(f"{os.path.basename(player_path)} is missing its data placeholder")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace(placeholder, f'<script id="{placeholder_id}" type="application/json">{payload}</script>', 1)
    title = re.sub(r"[<>&]", "", str(data.get("title", "Code story")))
    return re.sub(r"<title>.*?</title>", f"<title>{title}</title>", html, count=1)


_SID = re.compile(r"^.+:[0-9]+(#[0-9]+)?$")


def validate_walkthrough(doc, bundle):
    """Check walkthrough.json against its schema and against the bundle it will be combined with.
    Returns (problems, warnings): problems stop the build, warnings are printed."""
    problems, warnings = [], []
    if not isinstance(doc, dict):
        return ["walkthrough.json must be a JSON object"], warnings
    allowed = {"schema", "title", "subtitle", "entry", "explanations", "notes"}
    for k in doc:
        if k not in allowed:
            problems.append(f"unknown field '{k}' (allowed: {', '.join(sorted(allowed))})")
    if doc.get("schema") != WALKTHROUGH_SCHEMA:
        problems.append(f"'schema' should be '{WALKTHROUGH_SCHEMA}'")
    title = doc.get("title")
    if not isinstance(title, str) or not title.strip():
        problems.append("'title' is required")
    elif len(title) > 80:
        problems.append(f"'title' is {len(title)} characters; the limit is 80")
    for k, limit in (("subtitle", 200), ("entry", 200)):
        if k in doc and (not isinstance(doc[k], str) or len(doc[k]) > limit):
            problems.append(f"'{k}' must be text of at most {limit} characters")
    ex = doc.get("explanations")
    if not isinstance(ex, dict):
        problems.append("'explanations' is required: an object keyed by statement id")
        ex = {}
    stmts = bundle.get("statements") or {}
    plan = bundle.get("plan") or {}
    steps = plan.get("steps") or []
    shown = {sid for st in steps for sid in (st.get("stmts") or ([st["stmt"]] if st.get("stmt") else []))}
    group_tail = {sid for st in steps if st.get("stmts") for sid in st["stmts"][1:]}
    for sid, e in ex.items():
        where = f"explanations['{sid}']"
        if not _SID.match(sid):
            problems.append(f"{where}: not a statement id (expected file:line, e.g. 'main.py:12')")
            continue
        if sid not in stmts:
            near = [x for x in stmts if x.split(":")[0] == sid.split(":")[0]]
            hint = f"; statements in that file start at lines {', '.join(x.split(':', 1)[1] for x in near[:12])}" if near else ""
            problems.append(f"{where}: no such statement in the bundle (was the code changed after recording?){hint}")
            continue
        if not isinstance(e, dict):
            problems.append(f"{where}: must be an object with 'title' and 'text'")
            continue
        for k in e:
            if k not in ("title", "text"):
                problems.append(f"{where}: unknown field '{k}'")
        for k, limit in (("title", 60), ("text", 700)):
            v = e.get(k)
            if not isinstance(v, str) or not v.strip():
                problems.append(f"{where}.{k} is required")
            elif len(v) > limit:
                problems.append(f"{where}.{k} is {len(v)} characters; the limit is {limit}")
        if sid not in shown:
            warnings.append(f"{where}: this statement isn't a step in the walkthrough, so the explanation won't be shown")
        elif sid in group_tail:
            warnings.append(f"{where}: this statement is shown inside a grouped step; key the explanation to the group's first statement")
    notes = doc.get("notes", {})
    if not isinstance(notes, dict):
        problems.append("'notes' must be an object keyed by step id")
        notes = {}
    step_ids = {st.get("id") for st in steps}
    for k, v in notes.items():
        if k not in step_ids:
            problems.append(f"notes['{k}']: no such step in the plan")
        elif not isinstance(v, str) or not v.strip() or len(v) > 300:
            problems.append(f"notes['{k}'] must be text of at most 300 characters")
    first = plan.get("explain_first") or []
    max_steps = plan.get("max_steps") or MAX_STEPS_DEFAULT
    if len(ex) > max_steps:
        warnings.append(f"{len(ex)} explanations, more than --max-steps ({max_steps}); that's fine if the user asked for it")
    top = first[:min(len(first), 20)]
    missing = [x for x in top if x not in ex and x not in group_tail]
    if top and len(missing) > len(top) // 2:
        warnings.append(f"{len(missing)} of the {len(top)} most important statements have no explanation, e.g. {', '.join(missing[:4])}")
    return problems, warnings


def walkthrough_payload(doc, bundle):
    """Merge the assistant's walkthrough document with the bundle: source, statements and steps come from the
    bundle (measured), titles and explanations from the document (written)."""
    if bundle.get("view") != "walkthrough" or "plan" not in bundle:
        raise SystemExit("this bundle has no walkthrough; record it with --view walkthrough")
    run = bundle.get("run") or {}
    return {
        "schema": PAYLOAD_SCHEMA, "tool_version": VERSION,
        "title": doc.get("title") or "Code walkthrough", "subtitle": doc.get("subtitle", ""),
        "mode": bundle["mode"], "entry": doc.get("entry") or bundle.get("entry"),
        "run": {k: run[k] for k in ("status", "started_at", "duration_ms", "args", "safe_mode", "error") if k in run},
        "focus": bundle.get("focus"), "files": bundle["sources"], "statements": bundle["statements"],
        "docstrings": bundle.get("docstrings", {}), "steps": bundle["plan"]["steps"],
        "explain_first": bundle["plan"].get("explain_first", []),
        "explanations": doc.get("explanations", {}), "notes": doc.get("notes", {}),
        "limits": {"truncated": bundle["plan"].get("truncated") or bundle["plan"].get("lines_truncated", False)},
        "side_effects": {k: (bundle.get("io") or {}).get(k, []) for k in ("intercepted", "real_effects", "not_intercepted_libraries")},
    }


def cmd_build(a):
    with open(a.storyboard, encoding="utf-8") as fh:
        sb = json.load(fh)
    if sb.get("schema") == WALKTHROUGH_SCHEMA:
        if not a.bundle:
            raise SystemExit("a walkthrough needs its bundle: add --bundle codestory_bundle.json")
        with open(a.bundle, encoding="utf-8") as fh:
            bundle = json.load(fh)
        if bundle.get("view") != "walkthrough" or "plan" not in bundle:
            raise SystemExit("this bundle has no walkthrough; record it with --view walkthrough")
        problems, warnings = validate_walkthrough(sb, bundle)
        for w in warnings:
            log(f"walkthrough: note: {w}")
        for p in problems:
            log(f"walkthrough: {p}")
        if problems and not a.force:
            raise SystemExit(f"walkthrough.json has {len(problems)} problem(s) (use --force to build anyway)")
        ex = sb.get("explanations") or {}
        log(f"walkthrough: {len(ex)} explanations for {bundle['plan']['counts']['statements']} statements in "
            f"{bundle['plan']['counts']['visible_steps']} steps")
        data = walkthrough_payload(sb, bundle)
        player = a.player or os.path.join(HERE, "walkthrough.html")
        placeholder_id, out = "walkthrough", a.out if a.out != "story.html" else "walkthrough.html"
    else:
        problems = validate_storyboard(sb)
        for p in problems:
            log(f"storyboard: {p}")
        if problems and not a.force:
            raise SystemExit("storyboard has problems (use --force to build anyway)")
        data, player, placeholder_id, out = sb, a.player or os.path.join(HERE, "player.html"), "storyboard", a.out
    with open(player, encoding="utf-8") as fh:
        html = fh.read()
    html = _embed(html, player, placeholder_id, data)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    log(f"{'walkthrough' if placeholder_id == 'walkthrough' else 'story'} -> {out} ({os.path.getsize(out) // 1024} KB). Open it in any browser.")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    script_args = []
    if "--" in argv:
        i = argv.index("--")
        argv, script_args = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(prog="codestory", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="read the code without running it")
    s.add_argument("entry", nargs="?", help="the script you normally run, e.g. main.py")
    s.add_argument("-m", "--module", help="run or scan a module, as with `python -m MODULE` (instead of a script)")
    s.add_argument("--view", choices=("story", "walkthrough"), default="story",
                       help="story (default) or walkthrough; walkthrough adds the statement map and step plan" +
                            ("" if "s" == "s" else ", and records line by line"))
    s.add_argument("--focus", help="walkthrough only: files or functions to cover, comma-separated (default: the whole program)")
    s.add_argument("--max-steps", type=int, default=MAX_STEPS_DEFAULT,
                       help=f"walkthrough only: statements to suggest for written explanations (default: {MAX_STEPS_DEFAULT})")
    s.add_argument("--root", help="project root (default: current folder if it contains the entry point)")
    s.add_argument("-o", "--out", default="codestory_bundle.json", help="bundle file name (default: codestory_bundle.json)")
    s.add_argument("--budget", type=int, default=240_000, help="max characters of source code in the bundle")

    r = sub.add_parser("run", help="run the program under the tracer; arguments for your program go after --")
    r.add_argument("entry", nargs="?", help="the script you normally run, e.g. main.py")
    r.add_argument("-m", "--module", help="run or scan a module, as with `python -m MODULE` (instead of a script)")
    r.add_argument("--view", choices=("story", "walkthrough"), default="story",
                       help="story (default) or walkthrough; walkthrough adds the statement map and step plan" +
                            ("" if "r" == "s" else ", and records line by line"))
    r.add_argument("--focus", help="walkthrough only: files or functions to cover, comma-separated (default: the whole program)")
    r.add_argument("--max-steps", type=int, default=MAX_STEPS_DEFAULT,
                       help=f"walkthrough only: statements to suggest for written explanations (default: {MAX_STEPS_DEFAULT})")
    r.add_argument("--root", help="project root (default: current folder if it contains the entry point)")
    r.add_argument("-o", "--out", default="codestory_bundle.json", help="bundle file name (default: codestory_bundle.json)")
    r.add_argument("--budget", type=int, default=240_000, help="max characters of source code in the bundle")
    r.add_argument("--live", action="store_true", help="turn safe mode off: writes, posts and emails really happen")
    r.add_argument("--allow-subprocess", action="store_true", help="let the program start other processes in safe mode")

    b = sub.add_parser("build", help="embed a storyboard into the player")
    b.add_argument("storyboard", help="storyboard.json (story view) or walkthrough.json (walkthrough view)")
    b.add_argument("--bundle", help="walkthrough only: the bundle it was written from")
    b.add_argument("-o", "--out", default="story.html", help="story file name (default: story.html)")
    b.add_argument("--player", help="path to player.html (default: next to this script)")
    b.add_argument("--force", action="store_true", help="build even if the storyboard has problems")

    a = ap.parse_args(argv)
    if a.cmd in ("scan", "run") and bool(a.entry) == bool(a.module):
        ap.error(f"{a.cmd} needs exactly one of: a script (main.py) or -m MODULE")
    if a.cmd == "scan":
        a.out = os.path.abspath(a.out)
        cmd_scan(a)
    elif a.cmd == "run":
        a.out = os.path.abspath(a.out)
        cmd_run(a, script_args)
    else:
        cmd_build(a)


if __name__ == "__main__":
    main()
