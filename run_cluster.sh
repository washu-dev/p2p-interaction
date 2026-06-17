#!/bin/bash
# Run on the cluster LOGIN node (real SLURM submission).
# Users then point their browser at http://<login-node-host>:8000
set -euo pipefail
cd "$(dirname "$0")"

python -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -q -r backend/requirements.txt

export BINDGUI_BACKEND=slurm
# --- adjust these to your cluster if the defaults in config.py are wrong ---
# export BINDGUI_SLURM_ACCOUNT=compute2-rmitra
# export BINDGUI_SLURM_PARTITION=general-gpu
# export BINDGUI_TARGET_FASTA_DIR=/path/to/kinase_sequence
# export BINDGUI_COLABFOLD_BIN=/path/to/localcolabfold/.pixi/envs/default/bin
# micromamba env name + root prefix for the design stage.
# MAMBA_ROOT defaults to $BINDGUI_BINDCRAFT_DIR/Y (matches your bindcraft.slurm CONDA_BASE).
# export BINDGUI_MICROMAMBA_ENV=BindCraft
# export BINDGUI_MAMBA_ROOT=/rdcw/fs2/rmitra/Active/minibinders/d.mingyue/BindCraft/Y

echo "BindCraft GUI (slurm mode) -> http://0.0.0.0:8000"
python -m uvicorn main:app --app-dir backend --host 0.0.0.0 --port 8000
