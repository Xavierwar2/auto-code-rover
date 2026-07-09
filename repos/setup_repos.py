import os
import json
import subprocess
import shutil
import re
from tqdm import tqdm

REPOS_DIR = os.path.dirname(os.path.abspath(__file__))

# ================= 🚀 加速配置区域 =================
# 如果下载仍然卡顿，可以尝试取消注释切换其他镜像源

# 【推荐】github.chenc.dev (通常速度较快且稳定)
# MIRROR_URL = "https://github.chenc.dev/https://github.com"

# 【备选1】ghproxy.cxkpro.top
# MIRROR_URL = "https://ghproxy.cxkpro.top/https://github.com"

# 【备选2】gh.927223.xyz
# MIRROR_URL = "https://gh.927223.xyz/https://github.com"

# 【备选3】github.dpik.top
# MIRROR_URL = "https://github.dpik.top/https://github.com"

# 【备选4】KKGithub
# MIRROR_URL = "https://kgithub.com"

# 【备选5】官方源 (如果你的网络有魔法，可以用这个)
MIRROR_URL = "https://github.com"

# ================= 数据集配置 =================
DATASETS = [
    "darkreader__darkreader_dataset.jsonl",
    # "vuejs__core_dataset.jsonl",
    # "mui__material-ui_dataset.jsonl"
    # 在这里添加其他数据集文件
    # "anuraghazra__github-readme-stats_dataset.jsonl",
    # "axios__axios_dataset.jsonl",
    # "expressjs__express_dataset.jsonl",
    # "iamkun__dayjs_dataset.jsonl",
    # "Kong__insomnia_dataset.jsonl",
    # "sveltejs__svelte_dataset.jsonl"
]
# ===========================================

def run_command(command, cwd=None, capture_error=False):
    """运行 shell 命令"""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture_error else subprocess.DEVNULL
        )
        return True
    except subprocess.CalledProcessError as e:
        if capture_error and e.stderr:
            print(f"  [详细错误] {e.stderr.decode('utf-8', errors='replace').strip()}")
        return False

def ensure_cache(org, repo_name):
    """确保代码已下载到缓存目录，如果存在则更新"""
    
    # 根据镜像配置构造 URL
    if "gitclone.com" in MIRROR_URL:
        repo_url = f"{MIRROR_URL}/{org}/{repo_name}.git"
    elif "github.chenc.dev" in MIRROR_URL or "ghproxy.cxkpro.top" in MIRROR_URL or "gh.927223.xyz" in MIRROR_URL or "github.dpik.top" in MIRROR_URL:
        repo_url = f"{MIRROR_URL}/{org}/{repo_name}.git"
    else:
        repo_url = f"{MIRROR_URL}/{org}/{repo_name}.git"

    cache_dir = os.path.join(REPOS_DIR, org, repo_name, "_cache")
    git_dir = os.path.join(cache_dir, ".git")

    # 检查缓存是否存在且是有效的 git 仓库，否则清理重新克隆
    if os.path.exists(cache_dir) and not os.path.exists(git_dir):
        print(f"  [清理] 发现损坏的缓存目录（无 .git），正在删除后重新克隆...")
        shutil.rmtree(cache_dir)

    if not os.path.exists(cache_dir):
        print(f"  [下载] 正在克隆 {org}/{repo_name}...")
        print(f"  [URL] {repo_url}")
        os.makedirs(os.path.dirname(cache_dir), exist_ok=True)
        if not run_command(f"git clone {repo_url} {cache_dir}", capture_error=True):
            print(f"  [错误] 克隆失败，请检查网络或更换镜像源: {repo_url}")
            if os.path.exists(cache_dir):
                shutil.rmtree(cache_dir)
            return None
    else:
        # 缓存有效，更新
        run_command("git fetch --all", cwd=cache_dir)
    
    return cache_dir

def setup_repository(instance):
    # 1. 解析元数据
    org = instance.get('org', '')
    repo_name = instance.get('repo', '')
    
    if not org and '/' in repo_name:
        org, repo_name = repo_name.split('/')
    elif not org:
        org = repo_name
        
    instance_id = instance.get('instance_id', '')
    if not instance_id and 'number' in instance:
        instance_id = str(instance['number'])
    match = re.search(r'\d+', str(instance_id))
    if match:
        instance_id = match.group(0)
    else:
        instance_id = ""
        
    base_commit = instance.get('base_commit', '')
    if not base_commit and 'base' in instance:
        base_commit = instance['base'].get('sha', '')
        
    if not base_commit:
        return

    # 2. 准备目标路径
    target_dir = os.path.join(REPOS_DIR, org, repo_name, instance_id)
    
    if os.path.exists(target_dir):
        return

    # 3. 准备/更新缓存
    cache_dir = ensure_cache(org, repo_name)
    if not cache_dir:
        return

    # print(f"正在配置 {instance_id} (Commit: {base_commit[:7]})...")

    # 4. 从缓存复制副本
    try:
        shutil.copytree(cache_dir, target_dir, dirs_exist_ok=True)
    except Exception as e:
        print(f"  [错误] 复制文件失败: {e}")
        return

    # 5. 回滚代码
    success = run_command(f"git reset --hard {base_commit}", cwd=target_dir, capture_error=True)
    if not success:
        # 镜像源可能不完整，尝试从 GitHub 官方源 fetch 缺失的 commit
        github_url = f"https://github.com/{org}/{repo_name}.git"
        print(f"  [重试] 镜像缺失 commit，正在从 GitHub 官方源 fetch {base_commit[:7]}...")
        run_command(f"git remote set-url origin {github_url}", cwd=target_dir)
        run_command("git fetch --unshallow", cwd=target_dir)
        run_command(f"git fetch origin {base_commit}", cwd=target_dir)
        success = run_command(f"git reset --hard {base_commit}", cwd=target_dir, capture_error=True)
        if not success:
            print(f"  [错误] 无法切换到 Commit {base_commit}")
            shutil.rmtree(target_dir)

if __name__ == "__main__":
    print(f"当前使用镜像源: {MIRROR_URL}")
    print()
    for dataset_file in DATASETS:
        dataset_path = os.path.join(REPOS_DIR, dataset_file)
        if not os.path.exists(dataset_path):
            print(f"未找到数据集文件: {dataset_file}")
            continue
            
        print(f"正在处理数据集: {dataset_file}")
        with open(dataset_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        for line in tqdm(lines, desc="Setup Repos"):
            if not line.strip(): continue
            try:
                instance = json.loads(line)
                setup_repository(instance)
            except Exception as e:
                print(f"Error: {e}")

    print("\n所有仓库配置完成！请运行 run.sh")
