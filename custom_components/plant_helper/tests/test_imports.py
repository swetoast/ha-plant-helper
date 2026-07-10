import ast, pathlib, sys
root = pathlib.Path(".").resolve()
problems = []

def symbols(pyfile):
    try: tree = ast.parse(pyfile.read_text())
    except Exception: return set()
    names=set()
    for n in ast.walk(tree):
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)): names.add(n.name)
        elif isinstance(n,ast.Assign):
            for t in n.targets:
                if isinstance(t,ast.Name): names.add(t.id)
        elif isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name): names.add(n.target.id)
        elif isinstance(n,ast.ImportFrom):
            for a in n.names: names.add(a.asname or a.name)
        elif isinstance(n,ast.Import):
            for a in n.names: names.add((a.asname or a.name).split(".")[0])
    return names

for pyfile in root.rglob("*.py"):
    if "__pycache__" in str(pyfile) or "/tests/" in str(pyfile): continue
    try: tree=ast.parse(pyfile.read_text())
    except Exception as e: problems.append(f"{pyfile}: parse {e}"); continue
    for node in ast.walk(tree):
        if not (isinstance(node,ast.ImportFrom) and node.level>0): continue
        base=pyfile.parent
        for _ in range(node.level-1): base=base.parent
        target=base
        if node.module:
            for mp in node.module.split("."): target=target/mp
        modfile=target.with_suffix(".py"); modpkg=target/"__init__.py"
        target_syms = symbols(modfile) if modfile.exists() else (symbols(modpkg) if modpkg.exists() else None)
        for a in node.names:
            if a.name=="*": continue
            # valid if a symbol in the target module/package OR a submodule file/package under target
            sub_file=(target/a.name).with_suffix(".py")
            sub_pkg=(target/a.name/"__init__.py")
            if node.module is None:
                # from . import name  -> name is a submodule
                if not (sub_file.exists() or sub_pkg.exists()):
                    problems.append(f"{pyfile.name}: `from {'.'*node.level} import {a.name}` -> SUBMODULE NOT FOUND")
            else:
                if target_syms is None:
                    problems.append(f"{pyfile.name}: `from {'.'*node.level}{node.module} import {a.name}` -> MODULE NOT FOUND"); continue
                if a.name not in target_syms and not sub_file.exists() and not sub_pkg.exists():
                    problems.append(f"{pyfile.name}: `from {'.'*node.level}{node.module} import {a.name}` -> SYMBOL NOT FOUND")

if problems:
    print("IMPORT PROBLEMS:")
    for p in problems: print("  ✗",p)
    print("FAILED")
    sys.exit(1)
print("  PASS  all relative imports resolve to real modules + symbols")
print("\nALL IMPORT TESTS PASSED")
