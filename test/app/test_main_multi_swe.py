import json
import sys
import types

sys.modules.setdefault("emojis", types.SimpleNamespace())
from app.main import (
    infer_multi_swe_language,
    make_multi_swe_tasks,
    parse_task_list_entry,
    parse_task_list_file,
)


def test_infer_multi_swe_language_from_dataset_path(tmp_path):
    dataset_file = tmp_path / "ts" / "darkreader__darkreader_dataset.jsonl"
    dataset_file.parent.mkdir()

    assert infer_multi_swe_language(str(dataset_file)) == "typescript"


def test_make_multi_swe_tasks_passes_language_and_test_cmd(tmp_path):
    repo_dir = tmp_path / "repos"
    repo_dir.mkdir()
    (repo_dir / "darkreader" / "darkreader").mkdir(parents=True)

    dataset_dir = tmp_path / "ts"
    dataset_dir.mkdir()
    dataset_file = dataset_dir / "darkreader__darkreader_dataset.jsonl"
    instance = {
        "org": "darkreader",
        "repo": "darkreader",
        "number": 7241,
        "title": "Fix parser",
        "body": "Bug body",
        "base": {"sha": "abc123"},
        "fix_patch": "",
        "instance_id": "darkreader__darkreader-7241",
    }
    dataset_file.write_text(json.dumps(instance) + "\n")

    tasks = make_multi_swe_tasks(
        str(dataset_file),
        str(repo_dir),
        task_id=None,
        task_list_file=None,
        org=None,
        repo=None,
        clone=False,
        language=None,
        test_cmd="npm test",
    )

    task = tasks[0].to_task()
    assert task.language == "typescript"
    assert task.test_cmd == "npm test"


def test_parse_task_list_entry_supports_multi_swe_test_case_ids():
    assert (
        parse_task_list_entry("darkreader/darkreader:pr-6747")
        == "darkreader__darkreader-6747"
    )


def test_parse_task_list_file_supports_jsonl_and_plain_lines(tmp_path):
    task_list_file = tmp_path / "tasks.jsonl"
    task_list_file.write_text(
        "\n".join(
            [
                "darkreader/darkreader:pr-6747",
                '{"instance_id": "darkreader__darkreader-7241"}',
                '{"org": "django", "repo": "django", "number": 11133}',
                "sympy__sympy-12419",
                "",
            ]
        )
    )

    assert parse_task_list_file(str(task_list_file)) == [
        "darkreader__darkreader-6747",
        "darkreader__darkreader-7241",
        "django__django-11133",
        "sympy__sympy-12419",
    ]
