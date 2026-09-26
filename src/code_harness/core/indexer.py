"""Deterministic static repository indexer.

Extracts typed nodes and cross-boundary edges across:
- Python AST (Functions, Classes, Calls, Endpoints, ORM DBColumns, DTOs)
- JavaScript / TypeScript (fetch / axios consumers -> ConsumesRoute edges)
- SQL Migrations (DDL CREATE TABLE / ALTER TABLE -> DBColumn nodes, MigratesTo edges)

Enforces Invariants I1 & I2: all edges are static parser facts.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from code_harness.core.graph import (
    CodeGraph,
    CodeSpan,
    EdgeKind,
    GraphNode,
    NodeKind,
)


class RepositoryIndexer:
    """Deterministic parser extracting typed nodes and cross-boundary edges."""

    def __init__(self, repo_path: str | Path) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.graph = CodeGraph()
        self._defined_functions: Dict[str, str] = {}  # short_name -> node_id
        self._endpoints_by_route: Dict[str, str] = {}  # route_pattern -> node_id
        self._db_columns: Dict[str, str] = {}  # "table.col" -> node_id

    def index(self) -> CodeGraph:
        """Scan repository files and build deterministic graph."""
        self.graph = CodeGraph()
        self._defined_functions.clear()
        self._endpoints_by_route.clear()
        self._db_columns.clear()

        # Step 1: Collect files by extension
        py_files: List[Path] = []
        js_files: List[Path] = []
        sql_files: List[Path] = []

        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and d not in {"venv", ".venv", "node_modules", "__pycache__", "build", "dist"}
            ]
            for file in files:
                p = Path(root) / file
                ext = p.suffix.lower()
                if ext == ".py":
                    py_files.append(p)
                elif ext in {".js", ".ts", ".jsx", ".tsx"}:
                    js_files.append(p)
                elif ext == ".sql":
                    sql_files.append(p)

        # Step 2: Index SQL migrations first (DB schema lineage)
        for sql_file in sorted(sql_files):
            self._index_sql_file(sql_file)

        # Step 3: Parse Python ASTs
        parsed_py: List[Tuple[Path, str, ast.AST, List[str]]] = []
        for py_file in py_files:
            rel_path = str(py_file.relative_to(self.repo_path))
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content, filename=str(py_file))
                parsed_py.append((py_file, rel_path, tree, content.splitlines()))
            except Exception:
                self.graph.unresolved_refs += 1

        # Step 3a: Declarations pass (Classes, Functions, Endpoints, DB Columns)
        for _, rel_path, tree, lines in parsed_py:
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    self._process_py_class(node, rel_path, lines)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self._process_py_function(node, rel_path, lines)

        # Step 3b: Invocations pass (Calls, ReadsColumn)
        for _, rel_path, tree, _ in parsed_py:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self._process_py_calls(node, rel_path)

        # Step 4: Index JS/TS files (Client consumers)
        for js_file in js_files:
            self._index_js_file(js_file)

        # Step 5: Resolve cross-boundary edges (Endpoint -> ConsumesRoute, DBColumn -> Model)
        self._resolve_cross_boundaries()

        self.graph.increment_epoch()
        return self.graph

    # -------------------------------------------------------------------------
    # Python AST Indexing
    # -------------------------------------------------------------------------

    def _process_py_class(self, node: ast.ClassDef, rel_path: str, lines: List[str]) -> None:
        class_id = f"class:{rel_path}#{node.name}#L{node.lineno}"
        start_line = node.lineno
        end_line = getattr(node, "end_lineno", start_line)

        is_orm = False
        is_dto = False
        table_name = None

        for base in node.bases:
            base_name = ""
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute):
                base_name = base.attr
            if any(k in base_name for k in ("Base", "Model", "Table")):
                is_orm = True
            if any(k in base_name for k in ("Schema", "DTO", "BaseModel")):
                is_dto = True

        # Extract table name first
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == "__tablename__":
                        if isinstance(item.value, ast.Constant):
                            table_name = str(item.value.value)
                            is_orm = True

        # Extract attributes and Column declarations
        fields: Dict[str, str] = {}
        for item in node.body:
            if isinstance(item, ast.Assign):
                is_column_call = False
                col_type = "Any"
                nullable = True

                if isinstance(item.value, ast.Call):
                    func_name = ""
                    if isinstance(item.value.func, ast.Name):
                        func_name = item.value.func.id
                    elif isinstance(item.value.func, ast.Attribute):
                        func_name = item.value.func.attr
                    if func_name == "Column":
                        is_column_call = True
                        if item.value.args:
                            first_arg = item.value.args[0]
                            if isinstance(first_arg, (ast.Name, ast.Attribute)):
                                col_type = getattr(first_arg, "id", getattr(first_arg, "attr", "Any"))
                        for kw in item.value.keywords:
                            if kw.arg == "nullable" and isinstance(kw.value, ast.Constant):
                                nullable = bool(kw.value.value)

                for target in item.targets:
                    if isinstance(target, ast.Name):
                        col_name = target.id
                        if col_name == "__tablename__":
                            continue
                        fields[col_name] = col_type

                        if is_orm and is_column_call and table_name:
                            col_id = f"col:{table_name}.{col_name}"
                            col_node = GraphNode(
                                id=col_id,
                                name=col_name,
                                kind=NodeKind.DB_COLUMN,
                                file_path=rel_path,
                                span=CodeSpan(file_path=rel_path, start_line=item.lineno, end_line=getattr(item, "end_lineno", item.lineno)),
                                table=table_name,
                                col_type=col_type,
                                nullable=nullable,
                            )
                            self.graph.add_node(col_node)
                            self._db_columns[f"{table_name}.{col_name}"] = col_id

            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                field_name = item.target.id
                field_type = ast.unparse(item.annotation) if hasattr(ast, "unparse") else "Any"
                fields[field_name] = field_type

        kind = NodeKind.DTO if is_dto else NodeKind.CLASS
        class_node = GraphNode(
            id=class_id,
            name=node.name,
            kind=kind,
            file_path=rel_path,
            span=CodeSpan(file_path=rel_path, start_line=start_line, end_line=end_line),
            fields=fields,
            origin_language="python",
        )
        self.graph.add_node(class_node)

    def _process_py_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        rel_path: str,
        lines: List[str],
    ) -> None:
        fn_id = f"fn:{rel_path}#{node.name}#L{node.lineno}"
        start_line = node.lineno
        end_line = getattr(node, "end_lineno", start_line)

        param_types: Dict[str, str] = {}
        for arg in node.args.args:
            arg_type = "Any"
            if arg.annotation:
                arg_type = ast.unparse(arg.annotation) if hasattr(ast, "unparse") else "Any"
            param_types[arg.arg] = arg_type

        return_type = "Any"
        if node.returns:
            return_type = ast.unparse(node.returns) if hasattr(ast, "unparse") else "Any"

        body_slice = lines[start_line - 1 : min(end_line, start_line + 40)]
        body_source = "\n".join(body_slice)

        fn_node = GraphNode(
            id=fn_id,
            name=node.name,
            kind=NodeKind.FUNCTION,
            file_path=rel_path,
            span=CodeSpan(file_path=rel_path, start_line=start_line, end_line=end_line),
            signature=f"def {node.name}({', '.join(param_types.keys())})",
            return_type=return_type,
            param_types=param_types,
            body_source=body_source,
        )
        self.graph.add_node(fn_node)
        self._defined_functions[node.name] = fn_id

        # Route decorator check
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                dec_func = decorator.func
                method_name = ""
                if isinstance(dec_func, ast.Attribute):
                    method_name = dec_func.attr.upper()
                elif isinstance(dec_func, ast.Name):
                    method_name = dec_func.id.upper()

                if method_name in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                    if decorator.args and isinstance(decorator.args[0], ast.Constant):
                        route_path = str(decorator.args[0].value)
                        endpoint_id = f"endpoint:{method_name}:{route_path}"
                        endpoint_node = GraphNode(
                            id=endpoint_id,
                            name=f"{method_name} {route_path}",
                            kind=NodeKind.ENDPOINT,
                            file_path=rel_path,
                            span=CodeSpan(file_path=rel_path, start_line=start_line, end_line=end_line),
                            http_method=method_name,
                            route_pattern=route_path,
                            response_schema=return_type,
                        )
                        self.graph.add_node(endpoint_node)
                        self.graph.add_edge(fn_id, endpoint_id, EdgeKind.EXPOSES_ENDPOINT, confidence=1.0)
                        self._endpoints_by_route[route_path] = endpoint_id

    def _process_py_calls(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        rel_path: str,
    ) -> None:
        caller_id = f"fn:{rel_path}#{node.name}#L{node.lineno}"
        if not self.graph.has_node(caller_id):
            return

        # 1. Discover call sites
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                target_name = None
                if isinstance(child.func, ast.Name):
                    target_name = child.func.id
                elif isinstance(child.func, ast.Attribute):
                    target_name = child.func.attr

                if target_name and target_name in self._defined_functions:
                    callee_id = self._defined_functions[target_name]
                    if caller_id != callee_id and self.graph.has_node(callee_id):
                        if not self.graph.get_edge(caller_id, callee_id):
                            self.graph.add_edge(caller_id, callee_id, EdgeKind.CALLS, confidence=1.0)

            # 2. Discover DB Column reads (e.g. Order.discount_rate, order.discount_rate)
            elif isinstance(child, ast.Attribute):
                attr_name = child.attr
                for col_key, col_id in self._db_columns.items():
                    if col_key.endswith(f".{attr_name}"):
                        if not self.graph.get_edge(caller_id, col_id):
                            self.graph.add_edge(caller_id, col_id, EdgeKind.READS_COLUMN, confidence=1.0)

    # -------------------------------------------------------------------------
    # SQL Migration Indexing
    # -------------------------------------------------------------------------

    def _index_sql_file(self, file_path: Path) -> None:
        rel_path = str(file_path.relative_to(self.repo_path))
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return

        create_table_regex = re.compile(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_]+)\s*\((.*?)\);",
            re.IGNORECASE | re.DOTALL,
        )
        for match in create_table_regex.finditer(content):
            table_name = match.group(1).strip()
            columns_block = match.group(2)
            for line in columns_block.split(","):
                line = line.strip()
                if not line or line.upper().startswith(("PRIMARY", "FOREIGN", "KEY", "CONSTRAINT", "INDEX")):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    col_name = parts[0].strip('"`')
                    col_type = parts[1].upper()
                    nullable = "NOT NULL" not in line.upper()
                    col_id = f"col:{table_name}.{col_name}"
                    col_node = GraphNode(
                        id=col_id,
                        name=col_name,
                        kind=NodeKind.DB_COLUMN,
                        file_path=rel_path,
                        span=CodeSpan(file_path=rel_path, start_line=1, end_line=1),
                        table=table_name,
                        col_type=col_type,
                        nullable=nullable,
                    )
                    self.graph.add_node(col_node)
                    self._db_columns[f"{table_name}.{col_name}"] = col_id

        alter_regex = re.compile(
            r"ALTER\s+TABLE\s+([a-zA-Z0-9_]+)\s+ADD\s+(?:COLUMN\s+)?([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)(.*?);",
            re.IGNORECASE,
        )
        for match in alter_regex.finditer(content):
            table_name = match.group(1).strip()
            col_name = match.group(2).strip()
            col_type = match.group(3).upper()
            rest = match.group(4)
            nullable = "NOT NULL" not in rest.upper()
            col_id = f"col:{table_name}.{col_name}#migration"
            col_node = GraphNode(
                id=col_id,
                name=col_name,
                kind=NodeKind.DB_COLUMN,
                file_path=rel_path,
                span=CodeSpan(file_path=rel_path, start_line=1, end_line=1),
                table=table_name,
                col_type=col_type,
                nullable=nullable,
            )
            self.graph.add_node(col_node)
            base_col_id = f"col:{table_name}.{col_name}"
            if self.graph.has_node(base_col_id):
                self.graph.add_edge(col_id, base_col_id, EdgeKind.MIGRATES_TO, confidence=1.0)

    # -------------------------------------------------------------------------
    # JS/TS Client Fetcher Indexing
    # -------------------------------------------------------------------------

    def _index_js_file(self, file_path: Path) -> None:
        rel_path = str(file_path.relative_to(self.repo_path))
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return

        lines = content.splitlines()
        js_fn_regex = re.compile(
            r"(?:async\s+)?function\s+([a-zA-Z0-9_]+)\s*\((.*?)\)|const\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?\((.*?)\)\s*=>"
        )
        fetch_regex = re.compile(
            r"""(?:fetch|axios\.(?:get|post|put|delete))\s*\(\s*[`'"]([^`'"]+)[`'"]"""
        )

        for i, line in enumerate(lines, 1):
            fn_match = js_fn_regex.search(line)
            fn_name = None
            if fn_match:
                fn_name = fn_match.group(1) or fn_match.group(3)

            fetch_match = fetch_regex.search(line)
            if fetch_match:
                url_literal = fetch_match.group(1)
                consumer_name = fn_name or f"fetchSite#L{i}"
                consumer_id = f"js:{rel_path}#{consumer_name}#L{i}"
                consumer_node = GraphNode(
                    id=consumer_id,
                    name=consumer_name,
                    kind=NodeKind.FUNCTION,
                    file_path=rel_path,
                    span=CodeSpan(file_path=rel_path, start_line=i, end_line=i),
                    signature=f"{consumer_name}()",
                    origin_language="javascript",
                    metadata={"target_url": url_literal},
                )
                self.graph.add_node(consumer_node)

    # -------------------------------------------------------------------------
    # Cross-Boundary Linking Pass
    # -------------------------------------------------------------------------

    def _resolve_cross_boundaries(self) -> None:
        # 1. Match JS fetch calls to Backend Endpoints
        for node in self.graph.all_nodes():
            if node.id.startswith("js:") and "target_url" in node.metadata:
                target_url = node.metadata["target_url"]
                matched_endpoint_id = None
                for route_pat, ep_id in self._endpoints_by_route.items():
                    base_route = route_pat.split("{")[0].rstrip("/")
                    if base_route and target_url.startswith(base_route):
                        matched_endpoint_id = ep_id
                        break

                if matched_endpoint_id:
                    self.graph.add_edge(node.id, matched_endpoint_id, EdgeKind.CONSUMES_ROUTE, confidence=1.0)
                else:
                    self.graph.unresolved_refs += 1

        # 2. Check Type Drift between SQL Migrations and ORM Models
        for node in self.graph.all_nodes():
            if node.kind == NodeKind.DB_COLUMN and node.table:
                base_id = f"col:{node.table}.{node.name}"
                migration_id = f"col:{node.table}.{node.name}#migration"
                if self.graph.has_node(base_id) and self.graph.has_node(migration_id):
                    base_node = self.graph.get_node(base_id)
                    mig_node = self.graph.get_node(migration_id)
                    if base_node and mig_node:
                        if base_node.nullable != mig_node.nullable:
                            base_node.type_drift = True
                            mig_node.type_drift = True
