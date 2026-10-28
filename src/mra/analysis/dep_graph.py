"""Build the in-repo import graph (FR-2).

Nodes are repo-relative module files; an edge ``importer -> imported`` means the
first file imports the second. Only in-repo modules become edges — stdlib and
third-party imports are dropped, because the migration cannot reorder what it
cannot edit.

Note the direction flip when this reaches the state: SRS §4.1 defines
``dep_graph`` as "file -> list of files that import it", which is the graph's
*predecessors*, not its successors. :func:`to_state_adjacency` does that.
"""

from __future__ import annotations

from pathlib import Path

import libcst as cst
import networkx as nx

#: Directories that never hold repo modules worth graphing.
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "build",
    "dist",
}


def python_files(repo: Path | str) -> list[Path]:
    """Every source file in the repo, in stable order, minus build/cache noise.

    Only parts *inside* the repo are checked: a repo that itself lives under a
    ``build/`` or ``venv/`` directory is still scanned.
    """
    repo = Path(repo)
    return sorted(
        path
        for path in repo.rglob("*.py")
        if not any(
            part in SKIP_DIRS or part.endswith(".egg-info") for part in path.relative_to(repo).parts
        )
    )


def _source_root(repo: Path) -> Path:
    """Where import paths start. A ``src/`` layout roots there, otherwise the repo."""
    src = repo / "src"
    return src if src.is_dir() else repo


def module_index(repo: Path | str) -> dict[str, Path]:
    """Map dotted module name -> file, for every importable module in the repo."""
    repo = Path(repo)
    root = _source_root(repo)
    index: dict[str, Path] = {}
    for path in python_files(repo):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue  # outside the source root (tests/, scripts/) — not importable
        parts = list(relative.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if parts:
            index[".".join(parts)] = path
    return index


def _module_name(node: cst.BaseExpression) -> str:
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        return f"{_module_name(node.value)}.{node.attr.value}"
    return ""


class _ImportCollector(cst.CSTVisitor):
    """Collects the dotted module names a file imports, including submodules."""

    def __init__(self, package: str) -> None:
        self.package = package
        self.imported: set[str] = set()

    def visit_Import(self, node: cst.Import) -> None:
        for alias in node.names:
            if dotted := _module_name(alias.name):
                self.imported.add(dotted)

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        module = _module_name(node.module) if node.module is not None else ""
        if node.relative:
            # `from . import x` / `from ..pkg import y`: walk up from this file's
            # own package by one level per leading dot.
            parts = self.package.split(".") if self.package else []
            climb = len(node.relative) - 1
            base = parts[: len(parts) - climb] if climb <= len(parts) else []
            module = ".".join([*base, module]) if module else ".".join(base)
        if not module:
            return
        self.imported.add(module)
        if not isinstance(node.names, cst.ImportStar):
            # `from pkg import core` may name a submodule rather than an attribute.
            for alias in node.names:
                self.imported.add(f"{module}.{alias.evaluated_name}")


def build(repo: Path | str) -> nx.DiGraph:
    """Return a DiGraph over repo files with ``importer -> imported`` edges."""
    repo = Path(repo)
    index = module_index(repo)
    by_file = {path: name for name, path in index.items()}
    graph = nx.DiGraph()

    for path in python_files(repo):
        importer = path.relative_to(repo).as_posix()
        graph.add_node(importer)
        own = by_file.get(path, "")
        # An __init__.py *is* its package; any other module sits one level below.
        package = own if path.name == "__init__.py" else own.rpartition(".")[0]
        collector = _ImportCollector(package=package)
        try:
            # Bytes, so an encoding cookie is honoured; an unparseable file has
            # no imports this graph can see (the run report lists it).
            cst.parse_module(path.read_bytes()).visit(collector)
        except cst.ParserSyntaxError:
            continue
        for dotted in collector.imported:
            target = index.get(dotted)
            if target is not None and target != path:
                graph.add_edge(importer, target.relative_to(repo).as_posix())
    return graph


def to_state_adjacency(graph: nx.DiGraph) -> dict[str, list[str]]:
    """Graph -> the ``MigrationState.dep_graph`` shape: file -> files importing it."""
    return {
        node: sorted(graph.predecessors(node))
        for node in sorted(graph.nodes)
        if graph.in_degree(node) > 0
    }


def from_state_adjacency(adjacency: dict[str, list[str]]) -> nx.DiGraph:
    """The inverse of :func:`to_state_adjacency`: rebuild the ``importer -> imported`` graph.

    Lets a node recover the graph from ``MigrationState.dep_graph`` instead of
    re-parsing the repo or stowing a ``DiGraph`` in a checkpoint (it would have
    to be pickled, and it would be written again on every step). Files nothing
    imports and which import nothing are absent from the adjacency, but they
    are exactly the files with no ordering constraint, so no edge is lost.
    """
    graph = nx.DiGraph()
    for imported, importers in adjacency.items():
        graph.add_node(imported)
        for importer in importers:
            graph.add_edge(importer, imported)
    return graph
