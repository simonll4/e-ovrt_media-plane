from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="steelbench/SteelBench",
    repo_type="dataset",
    local_dir="data/raw/steelbench_sample",
    allow_patterns=["sample/**", "README.md", "LICENSE", "manifests/**"]
)
