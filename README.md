# Sequence-to-Selective-Binder Platform

A Streamlit prototype for designing protein binders from FASTA sequences and
ranking them for selective binding to positive targets over negative/off-targets.

This version focuses on the user workflow and uses deterministic mock outputs.
It does **not** run ColabFold, AlphaFold2, BindCraft, ProteinMPNN, or
AF2-Multimer.

## Features

- Multiple positive and negative FASTA uploads
- FASTA validation, previews, and multi-record parsing
- Mock ColabFold / AlphaFold2 structure prediction progress
- Binder length, design count, and hotspot configuration
- Mock BindCraft and ProteinMPNN candidate generation
- Binder-by-target selectivity screening and ranking
- Interactive Plotly heatmap
- Placeholder for a future 3D molecular viewer
- CSV and text report downloads
- Session-state persistence across the workflow

## Run locally

```bash
cd protein_binder_gui
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Streamlit will print a local URL, typically `http://localhost:8501`.

## Publish the demo

The repository includes public-site resource limits and Streamlit configuration.
Follow [DEPLOYMENT.md](DEPLOYMENT.md) to publish it through GitHub and Streamlit
Community Cloud.

## Project structure

```text
protein_binder_gui/
├── app.py
├── requirements.txt
├── README.md
└── utils/
    ├── __init__.py
    ├── fasta_utils.py
    ├── mock_backend.py
    ├── scoring.py
    └── visualization.py
```

## Mock scoring

The prototype generates a score from 0 to 1 for every binder-target pair.
Positive-target scores are generally higher than negative-target scores.

```text
selectivity_score = average_positive_score - average_negative_score
```

Candidates with a mock selectivity score of at least `0.35` pass.

## Future backend integration

The demonstration workflow can later be connected to real jobs:

1. Submit FASTA sequences to ColabFold / AlphaFold2 and persist PDB outputs.
2. Generate BindCraft settings JSON and execute design jobs.
3. Replace mock binder sequences with ProteinMPNN outputs.
4. Run AF2 / AF2-Multimer validation for every binder-target pair.
5. Connect resulting PDB files to py3Dmol, Mol*, or NGL Viewer.
