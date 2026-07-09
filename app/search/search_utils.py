import ast
import glob
import re
from os.path import join as pjoin
from pathlib import Path

JAVASCRIPT_FILE_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx")
SKIPPED_SOURCE_PARTS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "bower_components",
    "dist",
    "build",
    "coverage",
    ".next",
    ".nuxt",
    ".turbo",
    ".cache",
    "vendor",
}


def is_test_file(file_path: str) -> bool:
    """Check if a file is a test file.

    This is a simple heuristic to check if a file is a test file.
    """
    path = Path(file_path)
    parts = {p.lower() for p in path.parts}
    name = path.name.lower()
    return (
        "test" in parts
        or "tests" in parts
        or name.endswith("_test.py")
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )


def is_skipped_source_file(file_path: str) -> bool:
    parts = {p.lower() for p in Path(file_path).parts}
    return bool(parts.intersection(SKIPPED_SOURCE_PARTS))


def find_python_files(dir_path: str) -> list[str]:
    """Get all .py files recursively from a directory.

    Skips files that are obviously not from the source code, such third-party library code.

    Args:
        dir_path (str): Path to the directory.
    Returns:
        List[str]: List of .py file paths. These paths are ABSOLUTE path!
    """

    py_files = glob.glob(pjoin(dir_path, "**/*.py"), recursive=True)
    res = []
    for file in py_files:
        rel_path = file[len(dir_path) + 1 :]
        if is_test_file(rel_path):
            continue
        res.append(file)
    return res


def find_javascript_files(dir_path: str) -> list[str]:
    """Get all JS/TS source files recursively from a directory."""
    res = []
    for ext in JAVASCRIPT_FILE_EXTENSIONS:
        res.extend(glob.glob(pjoin(dir_path, f"**/*{ext}"), recursive=True))
    filtered = []
    for file in res:
        rel_path = file[len(dir_path) + 1 :]
        if is_test_file(rel_path) or is_skipped_source_file(rel_path):
            continue
        filtered.append(file)
    return filtered


def find_source_files(dir_path: str) -> list[str]:
    """Get all supported source files recursively from a directory."""
    files = find_python_files(dir_path)
    files.extend(find_javascript_files(dir_path))
    return sorted(dict.fromkeys(files))


def parse_class_def_args(source: str, node: ast.ClassDef) -> list[str]:
    # TODO this is simple enough to cover a lot of cases but can be improvied
    super_classes = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            if base.id in ["type", "object"]:
                continue
            super_classes.append(ast.get_source_segment(source, base))
        if (
            isinstance(base, ast.Call)
            and ast.get_source_segment(source, base.func) == "type"
        ):
            super_classes.append(ast.get_source_segment(source, base.args[0]))
    return super_classes


def parse_python_file(
    file_full_path: str,
) -> (
    tuple[
        list[tuple[str, int, int]],
        dict[str, list[tuple[str, int, int]]],
        list[tuple[str, int, int]],
        dict[tuple[str, int, int], list[str]],
    ]
    | None
):
    """
    Main method to parse AST and build search index.
    Handles complication where python ast module cannot parse a file.
    """
    try:
        file_content = Path(file_full_path).read_text()
        tree = ast.parse(file_content)
    except Exception:
        # failed to read/parse one file, we should ignore it
        return None

    # (1) get all classes defined in the file
    classes: list[tuple[str, int, int]] = []
    # (2) for each class in the file, get all functions defined in the class.
    class_to_funcs: dict[str, list[tuple[str, int, int]]] = {}
    # (3) get top-level functions in the file (exclues functions defined in classes)
    top_level_funcs: list[tuple[str, int, int]] = []
    # (4) get class relations
    class_relation_map: dict[tuple[str, int, int], list[str]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            ## class part (1): collect class info
            class_name = node.name
            start_lineno = node.lineno
            end_lineno = node.end_lineno
            assert end_lineno is not None, "class should have end_lineno in AST."
            # line numbers are 1-based
            classes.append((class_name, start_lineno, end_lineno))
            class_relation_map[(class_name, start_lineno, end_lineno)] = (
                parse_class_def_args(file_content, node)
            )

            ## class part (2): collect function info inside this class
            class_funcs = [
                (n.name, n.lineno, n.end_lineno)
                for n in ast.walk(node)
                if isinstance(n, ast.FunctionDef) and n.end_lineno is not None
            ]
            class_to_funcs[class_name] = class_funcs

        elif isinstance(node, ast.FunctionDef):
            function_name = node.name
            start_lineno = node.lineno
            end_lineno = node.end_lineno
            assert end_lineno is not None, "function should have end_lineno in AST."
            # line numbers are 1-based
            top_level_funcs.append((function_name, start_lineno, end_lineno))

    return classes, class_to_funcs, top_level_funcs, class_relation_map


def _get_node_text(node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _node_line_range(node) -> tuple[int, int]:
    return node.start_point[0] + 1, node.end_point[0] + 1


def _iter_tree_nodes(node):
    yield node
    for child in node.named_children:
        yield from _iter_tree_nodes(child)


def _has_parent_type(node, parent_types: set[str]) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type in parent_types:
            return True
        parent = parent.parent
    return False


def _is_top_level_javascript_node(node) -> bool:
    parent = node.parent
    if parent is None:
        return False
    if parent.type == "program":
        return True
    if parent.type == "export_statement" and parent.parent is not None:
        return parent.parent.type == "program"
    return False


def _get_tree_sitter_parser(file_full_path: str):
    path = Path(file_full_path)
    is_tsx = path.suffix == ".tsx"
    is_ts = path.suffix in {".ts", ".tsx"}

    try:
        from tree_sitter_languages import get_parser

        if is_tsx:
            return get_parser("tsx")
        if is_ts:
            return get_parser("typescript")
        return get_parser("javascript")
    except Exception:
        pass

    try:
        from tree_sitter import Language, Parser

        parser = Parser()
        if is_tsx:
            import tree_sitter_typescript as ts_language

            raw_language = ts_language.language_tsx()
        elif is_ts:
            import tree_sitter_typescript as ts_language

            raw_language = ts_language.language_typescript()
        else:
            import tree_sitter_javascript as js_language

            raw_language = js_language.language()

        try:
            language = Language(raw_language)
        except TypeError:
            language = raw_language

        if hasattr(parser, "set_language"):
            parser.set_language(language)
        else:
            parser.language = language
        return parser
    except Exception:
        return None


def _parse_javascript_file_with_treesitter(
    file_full_path: str,
) -> tuple[
    list[tuple[str, int, int]],
    dict[str, list[tuple[str, int, int]]],
    list[tuple[str, int, int]],
    dict[tuple[str, int, int], list[str]],
] | None:
    parser = _get_tree_sitter_parser(file_full_path)
    if parser is None:
        return None

    try:
        source = Path(file_full_path).read_bytes()
        tree = parser.parse(source)
    except Exception:
        return None

    classes: list[tuple[str, int, int]] = []
    class_to_funcs: dict[str, list[tuple[str, int, int]]] = {}
    top_level_funcs: list[tuple[str, int, int]] = []
    class_relation_map: dict[tuple[str, int, int], list[str]] = {}

    for node in _iter_tree_nodes(tree.root_node):
        if node.type in {"class_declaration", "class"}:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            class_name = _get_node_text(name_node, source)
            start, end = _node_line_range(node)
            class_tuple = (class_name, start, end)
            classes.append(class_tuple)

            superclass_node = node.child_by_field_name("superclass")
            if superclass_node is None:
                heritage_node = next(
                    (
                        child
                        for child in node.named_children
                        if child.type == "class_heritage"
                    ),
                    None,
                )
                extends_node = (
                    next(
                        (
                            child
                            for child in heritage_node.named_children
                            if child.type == "extends_clause"
                        ),
                        None,
                    )
                    if heritage_node is not None
                    else None
                )
                superclass_node = (
                    extends_node.child_by_field_name("value")
                    if extends_node is not None
                    else None
                )
            if superclass_node is not None:
                class_relation_map[class_tuple] = [
                    _get_node_text(superclass_node, source)
                ]
            else:
                class_relation_map[class_tuple] = []

        elif node.type == "function_declaration":
            if not _is_top_level_javascript_node(node):
                continue
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            start, end = _node_line_range(node)
            top_level_funcs.append((_get_node_text(name_node, source), start, end))

        elif node.type == "variable_declarator":
            if _has_parent_type(node, {"class_body"}):
                continue
            if not _is_top_level_javascript_node(node.parent):
                continue
            name_node = node.child_by_field_name("name")
            value_node = node.child_by_field_name("value")
            if name_node is None or value_node is None:
                continue
            if value_node.type not in {"arrow_function", "function_expression"}:
                continue
            start, end = _node_line_range(node)
            top_level_funcs.append((_get_node_text(name_node, source), start, end))

    for class_name, class_start, class_end in classes:
        funcs: list[tuple[str, int, int]] = []
        for node in _iter_tree_nodes(tree.root_node):
            if node.type != "method_definition":
                continue
            if not (class_start <= node.start_point[0] + 1 <= class_end):
                continue
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            start, end = _node_line_range(node)
            funcs.append((_get_node_text(name_node, source), start, end))
        class_to_funcs[class_name] = funcs

    return classes, class_to_funcs, top_level_funcs, class_relation_map


def _brace_block_end(lines: list[str], start_line_no: int) -> int:
    """Best-effort end line for JS/TS brace-delimited declarations."""
    depth = 0
    saw_open = False
    for idx in range(start_line_no - 1, len(lines)):
        line = lines[idx]
        depth += line.count("{")
        if "{" in line:
            saw_open = True
        depth -= line.count("}")
        if saw_open and depth <= 0:
            return idx + 1
    return start_line_no


def _parse_javascript_file_with_regex(
    file_full_path: str,
) -> tuple[
    list[tuple[str, int, int]],
    dict[str, list[tuple[str, int, int]]],
    list[tuple[str, int, int]],
    dict[tuple[str, int, int], list[str]],
] | None:
    try:
        lines = Path(file_full_path).read_text(encoding="utf-8").splitlines()
    except Exception:
        return None

    classes: list[tuple[str, int, int]] = []
    class_to_funcs: dict[str, list[tuple[str, int, int]]] = {}
    top_level_funcs: list[tuple[str, int, int]] = []
    class_relation_map: dict[tuple[str, int, int], list[str]] = {}

    class_pattern = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)"
        r"(?:\s+extends\s+([A-Za-z_$][\w$\.]*))?"
    )
    function_patterns = [
        re.compile(
            r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*(?:<[^>{}]+>)?\s*\("
        ),
        re.compile(
            r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
        ),
        re.compile(
            r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?function\b"
        ),
    ]
    method_pattern = re.compile(
        r"^\s*(?:public\s+|private\s+|protected\s+|static\s+|async\s+|get\s+|set\s+)*"
        r"([A-Za-z_$][\w$]*)\s*\([^;{}]*\)\s*(?::\s*[^{]+)?\s*\{"
    )

    for idx, line in enumerate(lines, start=1):
        class_match = class_pattern.match(line)
        if class_match:
            class_name = class_match.group(1)
            end = _brace_block_end(lines, idx)
            classes.append((class_name, idx, end))
            extends = class_match.group(2)
            class_relation_map[(class_name, idx, end)] = [extends] if extends else []
            continue

        for pattern in function_patterns:
            match = pattern.match(line)
            if match:
                top_level_funcs.append(
                    (match.group(1), idx, _brace_block_end(lines, idx))
                )
                break

    for class_name, start, end in classes:
        funcs: list[tuple[str, int, int]] = []
        for idx in range(start, end + 1):
            if idx - 1 >= len(lines):
                break
            match = method_pattern.match(lines[idx - 1])
            if not match:
                continue
            method_name = match.group(1)
            if method_name in {"if", "for", "while", "switch", "catch", "function"}:
                continue
            funcs.append((method_name, idx, _brace_block_end(lines, idx)))
        class_to_funcs[class_name] = funcs

    return classes, class_to_funcs, top_level_funcs, class_relation_map


def parse_javascript_file(
    file_full_path: str,
) -> tuple[
    list[tuple[str, int, int]],
    dict[str, list[tuple[str, int, int]]],
    list[tuple[str, int, int]],
    dict[tuple[str, int, int], list[str]],
] | None:
    """Build a JS/TS symbol index with tree-sitter.

    Falls back to a lightweight regex parser only when tree-sitter or the
    relevant grammar package is unavailable in the runtime environment.
    """
    tree_sitter_result = _parse_javascript_file_with_treesitter(file_full_path)
    if tree_sitter_result is not None:
        return tree_sitter_result
    return _parse_javascript_file_with_regex(file_full_path)


def get_code_region_containing_code(
    file_full_path: str, code_str: str, with_lineno=True
) -> list[tuple[int, str]]:
    """In a file, get the region of code that contains a specific string.

    Args:
        - file_full_path: Path to the file. (absolute path)
        - code_str: The string that the function should contain.
    Returns:
        - A list of tuple, each of them is a pair of (line_no, code_snippet).
        line_no is the starting line of the matched code; code snippet is the
        source code of the searched region.
    """
    with open(file_full_path) as f:
        file_content = f.read()

    context_size = 3
    # since the code_str may contain multiple lines, let's not split the source file.

    # we want a few lines before and after the matched string. Since the matched string
    # can also contain new lines, this is a bit trickier.
    pattern = re.compile(re.escape(code_str))
    # each occurrence is a tuple of (line_no, code_snippet) (1-based line number)
    occurrences: list[tuple[int, str]] = []
    for match in pattern.finditer(file_content):
        matched_start_pos = match.start()
        # first, find the line number of the matched start position (0-based)
        matched_line_no = file_content.count("\n", 0, matched_start_pos)

        file_content_lines = file_content.splitlines()

        window_start_index = max(0, matched_line_no - context_size)
        window_end_index = min(
            len(file_content_lines), matched_line_no + context_size + 1
        )

        if with_lineno:
            context = ""
            for i in range(window_start_index, window_end_index):
                context += f"{i+1} {file_content_lines[i]}\n"
        else:
            context = "\n".join(file_content_lines[window_start_index:window_end_index])
        occurrences.append((matched_line_no, context))

    return occurrences


def get_func_snippet_with_code_in_file(file_full_path: str, code_str: str) -> list[str]:
    """In a file, get the function code, for which the function contains a specific string.

    Args:
        file_full_path (str): Path to the file. (absolute path)
        code_str (str): The string that the function should contain.

    Returns:
        A list of code snippets, each of them is the source code of the searched function.
    """
    with open(file_full_path) as f:
        file_content = f.read()

    tree = ast.parse(file_content)
    all_snippets = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        func_start_lineno = node.lineno
        func_end_lineno = node.end_lineno
        assert func_end_lineno is not None
        func_code = get_code_snippets(
            file_full_path, func_start_lineno, func_end_lineno
        )
        # This func code is a raw concatenation of source lines which contains new lines and tabs.
        # For the purpose of searching, we remove all spaces and new lines in the code and the
        # search string, to avoid non-match due to difference in formatting.
        stripped_func = " ".join(func_code.split())
        stripped_code_str = " ".join(code_str.split())
        if stripped_code_str in stripped_func:
            all_snippets.append(func_code)

    return all_snippets


def get_code_snippets(
    file_full_path: str, start: int, end: int, with_lineno=True
) -> str:
    """Get the code snippet in the range in the file, without line numbers.

    Args:
        file_path (str): Full path to the file.
        start (int): Start line number. (1-based)
        end (int): End line number. (1-based)
    """
    with open(file_full_path) as f:
        file_content = f.readlines()
    snippet = ""
    for i in range(start - 1, end):
        if with_lineno:
            snippet += f"{i+1} {file_content[i]}"
        else:
            snippet += file_content[i]
    return snippet


def extract_func_sig_from_ast(func_ast: ast.FunctionDef) -> list[int]:
    """Extract the function signature from the AST node.

    Includes the decorators, method name, and parameters.

    Args:
        func_ast (ast.FunctionDef): AST of the function.

    Returns:
        The source line numbers that contains the function signature.
    """
    func_start_line = func_ast.lineno
    if func_ast.decorator_list:
        # has decorators
        decorator_start_lines = [d.lineno for d in func_ast.decorator_list]
        decorator_first_line = min(decorator_start_lines)
        func_start_line = min(decorator_first_line, func_start_line)
    # decide end line from body
    if func_ast.body:
        # has body
        body_start_line = func_ast.body[0].lineno
        end_line = body_start_line - 1
    else:
        # no body
        end_line = func_ast.end_lineno
    assert end_line is not None
    return list(range(func_start_line, end_line + 1))


def extract_class_sig_from_ast(class_ast: ast.ClassDef) -> list[int]:
    """Extract the class signature from the AST.

    Args:
        class_ast (ast.ClassDef): AST of the class.

    Returns:
        The source line numbers that contains the class signature.
    """
    # STEP (1): extract the class signature
    sig_start_line = class_ast.lineno
    if class_ast.body:
        # has body
        body_start_line = class_ast.body[0].lineno
        sig_end_line = body_start_line - 1
    else:
        # no body
        sig_end_line = class_ast.end_lineno
    assert sig_end_line is not None
    sig_lines = list(range(sig_start_line, sig_end_line + 1))

    # STEP (2): extract the function signatures and assign signatures
    for stmt in class_ast.body:
        if isinstance(stmt, ast.FunctionDef):
            sig_lines.extend(extract_func_sig_from_ast(stmt))
        elif isinstance(stmt, ast.Assign):
            # for Assign, skip some useless cases where the assignment is to create docs
            stmt_str_format = ast.dump(stmt)
            if "__doc__" in stmt_str_format:
                continue
            # otherwise, Assign is easy to handle
            assert stmt.end_lineno is not None
            assign_range = list(range(stmt.lineno, stmt.end_lineno + 1))
            sig_lines.extend(assign_range)

    return sig_lines


def get_class_signature(file_full_path: str, class_name: str) -> str:
    """Get the class signature.

    Args:
        file_path (str): Path to the file.
        class_name (str): Name of the class.
    """
    with open(file_full_path) as f:
        file_content = f.read()

    tree = ast.parse(file_content)
    relevant_lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            # we reached the target class
            relevant_lines = extract_class_sig_from_ast(node)
            break
    if not relevant_lines:
        return ""
    else:
        with open(file_full_path) as f:
            file_content = f.readlines()
        result = ""
        for line in relevant_lines:
            line_content: str = file_content[line - 1]
            if line_content.strip().startswith("#"):
                # this kind of comment could be left until this stage.
                # reason: # comments are not part of func body if they appear at beginning of func
                continue
            result += line_content
        return result


def get_code_region_around_line(
    file_full_path: str, line_no: int, window_size: int = 10, with_lineno=True
) -> str | None:
    """Get the code region around a specific line number in a file.

    Args:
        file_full_path (str): Path to the file. (absolute path)
        line_no (int): The line number to search around. (1-based)
    Returns:
        str: The code snippet around the line number.
    """
    with open(file_full_path) as f:
        file_content = f.readlines()

    if line_no < 1 or line_no > len(file_content):
        return None

    # start and end should also be 1-based valid line numbers
    start = max(1, line_no - window_size)
    end = min(len(file_content) + 1, line_no + window_size)
    snippet = ""
    for i in range(start, end):
        if with_lineno:
            snippet += f"{i} {file_content[i - 1]}"
        else:
            snippet += file_content[i - 1]
    return snippet
