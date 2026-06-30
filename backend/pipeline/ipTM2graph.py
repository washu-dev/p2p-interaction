# Usage: python plot_iptm.py complex_fasta/PDL1_l123_s488439_mpnn20_model2/PDL1_l123_s488439_mpnn20_model2_list.txt

import json
import os
import sys

import matplotlib.pyplot as plt

if len(sys.argv) != 2:
    print("Usage: python plot_iptm.py <list.txt>")
    sys.exit(1)

list_txt = sys.argv[1]
base_dir = os.path.dirname(list_txt)  # e.g. complex_fasta/PDL1_l123_s488439_mpnn20_model2
list_filename = os.path.basename(list_txt)
target = list_filename.split("_")[0]

with open(list_txt) as f:
    entries = [line.strip() for line in f if line.strip()]

labels = []
best_iptm = []
avg_iptm = []

for entry in entries:
    label = entry.split("_")[0]  # e.g. "Map4k4"
    iptm_file = os.path.join(base_dir, entry, "ipTM_data.txt")

    if not os.path.exists(iptm_file):
        print(f"Warning: {iptm_file} not found, skipping.")
        continue

    with open(iptm_file) as f:
        values = [float(line.strip()) for line in f if line.strip()]

    if len(values) < 1:
        print(f"Warning: {iptm_file} is empty, skipping.")
        continue

    labels.append(label)
    best_iptm.append(values[0])
    avg_iptm.append(sum(values) / len(values))

if not labels:
    print("No valid data found.")
    sys.exit(1)

# sort alphabetically by label
paired = sorted(zip(labels, best_iptm, avg_iptm), key=lambda x: x[0])
labels, best_iptm, avg_iptm = map(list, zip(*paired))

out_dir = base_dir

# Machine-readable selectivity for the results library (consumed by the backend).
with open(os.path.join(out_dir, "selectivity.json"), "w") as f:
    json.dump(
        [
            {"kinase": k, "best_iptm": b, "avg_iptm": a}
            for k, b, a in zip(labels, best_iptm, avg_iptm)
        ],
        f,
        indent=2,
    )

def make_plot(y_vals, ylabel, title, filename):
    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 0.6), 5))
    ax.plot(labels, y_vals, marker="o", linewidth=1.5, markersize=6, color="steelblue")
    ax.set_xlabel("Kinases", fontsize=12)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_title(title, fontsize=13)
    ax.set_ylim(0, 1)

    ax.axhspan(0.8, 1.0, color="green",  alpha=0.08, label="confident (>0.8)")
    ax.axhspan(0.6, 0.8, color="gray",   alpha=0.08, label="grey zone (0.6–0.8)")
    ax.axhspan(0.0, 0.6, color="red",    alpha=0.08, label="failed (<0.6)")

    ax.axhline(0.8, color="green", linestyle="--", linewidth=1)
    ax.axhline(0.6, color="red",   linestyle="--", linewidth=1)

    ax.legend(fontsize=9)
    plt.xticks(rotation=15, ha="right", fontsize=9)
    plt.tight_layout()
    out_path = os.path.join(out_dir, filename)
    fig.savefig(out_path, dpi=150)
    print(f"Saved: {out_path}")
    plt.close(fig)

make_plot(best_iptm, "ipTM (highest)", f"{target}_binder's highest ipTM to each kinase", f"iptm_best_{target}.png")
make_plot(avg_iptm,  "ipTM (average)",    f"{target}_binder's average ipTM to each kinase",     f"iptm_avg_{target}.png")

