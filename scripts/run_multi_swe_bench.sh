#!/usr/bin/env bash

# 运行 Multi-SWE-bench 任务的便捷脚本。
# 用法示例：
#   bash scripts/run_multi_swe_bench.sh
#   MODEL=gpt-5.4 TASK=darkreader__darkreader-7241 bash scripts/run_multi_swe_bench.sh
#   TASK_LIST_FILE=test/test_cases/test_cases_darkreader.jsonl bash scripts/run_multi_swe_bench.sh

set -euo pipefail

# ACR 项目根目录。默认自动取本脚本所在目录的上一级。
if [[ -z "${ACR_ROOT:-}" ]]; then
  ACR_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

# Multi-SWE-bench 数据集根目录。
# 如果你的数据集放在别处，运行前设置：
#   MULTI_SWE_ROOT=/path/to/multi-swe-bench bash scripts/run_multi_swe_bench.sh
MULTI_SWE_ROOT="${MULTI_SWE_ROOT:-$ACR_ROOT}"

# 数据集文件。TypeScript 的 darkreader 数据集通常位于 data/ts 下。
DATASET_FILE="${DATASET_FILE:-$MULTI_SWE_ROOT/repos/darkreader__darkreader_dataset.jsonl}"

# 目标仓库根目录。ACR 会按 <org>/<repo> 结构查找或克隆仓库，
# 例如 darkreader 会放在：$REPO_DIR/darkreader/darkreader
REPO_DIR="${REPO_DIR:-$MULTI_SWE_ROOT/repos}"

# 输出目录。每次运行的中间文件、日志和最终 predictions 都会写到这里。
OUTPUT_DIR="${OUTPUT_DIR:-$ACR_ROOT/results/acr_darkreader_test}"

# 使用的模型名称。必须是 app/model/register.py 注册过、命令行 choices 支持的模型。
MODEL="${MODEL:-gpt-5.4}"

# 模型温度。补丁生成通常建议较低温度，保证输出稳定。
MODEL_TEMPERATURE="${MODEL_TEMPERATURE:-0.2}"

# 项目语言。留空时 ACR 会根据 dataset 路径中的 ts/js/py 自动推断。
LANGUAGE="${LANGUAGE:-typescript}"

# 可选验证命令。启用 --enable-validation 时会在应用补丁后运行。
# 对 darkreader 可按你的环境改成 npm test、npm run test、pnpm test 等。
TEST_CMD="${TEST_CMD:-npm test}"

# 单任务 id。格式通常是 org__repo-number，例如 darkreader__darkreader-7241。
# 如果 TASK 非空，会优先运行单任务。
TASK="${TASK:-}"

# 多任务列表文件。支持：
#   1. darkreader__darkreader-7241
#   2. darkreader/darkreader:pr-7241
#   3. {"instance_id": "darkreader__darkreader-7241"}
TASK_LIST_FILE="${TASK_LIST_FILE:-$ACR_ROOT/test/test_cases/test_cases_darkreader.jsonl}"

# 是否不克隆仓库。1 表示要求仓库已经存在于 $REPO_DIR/<org>/<repo>。
# 如果设为 0，仓库不存在时会从 GitHub 克隆。
NO_CLONE="${NO_CLONE:-1}"

# 是否开启验证。1 会追加 --enable-validation，并使用 TEST_CMD 验证 Plain/Multi-SWE 任务。
ENABLE_VALIDATION="${ENABLE_VALIDATION:-0}"

# 并发进程数。多任务时可以调大；同一个 repo 组内仍会顺序运行。
NUM_PROCESSES="${NUM_PROCESSES:-1}"

cd "$ACR_ROOT"

cmd=(
  python app/main.py multi-swe-bench
  --model "$MODEL"
  --model-temperature "$MODEL_TEMPERATURE"
  --output-dir "$OUTPUT_DIR"
  --dataset-file "$DATASET_FILE"
  --repo-dir "$REPO_DIR"
  --test-cmd "$TEST_CMD"
  --num-processes "$NUM_PROCESSES"
)

if [[ -n "$LANGUAGE" ]]; then
  cmd+=(--language "$LANGUAGE")
fi

if [[ -n "$TASK" ]]; then
  cmd+=(--task "$TASK")
else
  cmd+=(--task-list-file "$TASK_LIST_FILE")
fi

if [[ "$NO_CLONE" == "1" ]]; then
  cmd+=(--no-clone)
fi

if [[ "$ENABLE_VALIDATION" == "1" ]]; then
  cmd+=(--enable-validation)
fi

echo "即将运行 Multi-SWE-bench："
printf '  %q' PYTHONPATH=.
printf ' %q' "${cmd[@]}"
printf '\n'

PYTHONPATH=. "${cmd[@]}"
