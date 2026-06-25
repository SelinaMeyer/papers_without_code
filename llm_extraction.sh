#!/bin/bash -l
#
#SBATCH --gres=gpu:a40:1
#SBATCH --output=llm_repo_extraction.out
#SBATCH --time=2:00:00
#SBATCH --job-name=llm_repo_extraction
#SBATCH --export=ALL,http_proxy=http://proxy:80,https_proxy=http://proxy:80,PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

set -euo pipefail

source venv/bin/activate
python3 -u pipeline.py llm-prepare "acl-2016"
python3 -u pipeline.py llm-run "acl-2016"
