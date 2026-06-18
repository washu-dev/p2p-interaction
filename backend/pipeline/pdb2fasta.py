import sys
import os
from Bio.PDB import PDBParser, is_aa
from Bio.SeqUtils import seq1

# example
# python pdb2fasta.py ../kinase_binder/PDL1/Accepted/PDL1_l123_s488439_mpnn20_model2.pdb ../kinase_sequence/ ./complex_fasta
if len(sys.argv) != 4:
    print("Usage: python pdb2fasta.py <binder.pdb> <target_fasta_dir> <output_dir>")
    sys.exit(1)

pdb_file = sys.argv[1]
pdb_base = os.path.splitext(os.path.basename(pdb_file))[0]
fasta_dir = sys.argv[2]
output_dir = sys.argv[3]
output_dir = f"{output_dir}/{pdb_base}"
print(output_dir)
print("\n")

os.makedirs(output_dir, exist_ok=True)

# extract binder sequence from chain B
parser = PDBParser(QUIET=True)
struct = parser.get_structure("s", pdb_file)

binder_seq = ""
for chain in struct.get_chains():
    if chain.id != "B":
        continue
    binder_seq = seq1("".join(r.resname for r in chain.get_residues() if is_aa(r, standard=True)))

if not binder_seq:
    print("Error: chain B not found in PDB")
    sys.exit(1)

pdb_base = os.path.splitext(os.path.basename(pdb_file))[0]
print(f"Binder: chain B from {pdb_file} ({len(binder_seq)} aa)\n")

binder_fasta = os.path.splitext(pdb_file)[0] + ".fasta"
with open(binder_fasta, "w") as f:
    f.write(f">{pdb_base}\n{binder_seq}\n")
print(f"Saved: {binder_fasta}")

fasta_files = [f for f in os.listdir(fasta_dir) if f.endswith(".fasta")]

if not fasta_files:
    print(f"Error: no .fasta files found in {fasta_dir}")
    sys.exit(1)

list_file = os.path.join(output_dir, f"{pdb_base}_list.txt")
with open(list_file, "w") as file:
    pass

for fasta_file in fasta_files:
    fasta_base = os.path.splitext(fasta_file)[0]
    target_fasta = os.path.join(fasta_dir, fasta_file)
    target_seq = ""
    target_name = ""

    with open(target_fasta, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                target_name = line[1:]
            else:
                target_seq += line

    if not target_seq:
        print(f"Warning: could not read sequence from {fasta_file}, skipping")
        continue

    output_file = os.path.join(output_dir, f"{fasta_base}_vs_{pdb_base}.fasta")

    with open(output_file, "w") as f:
        f.write(f">target_binder_complex\n")
        f.write(f"{target_seq}:{binder_seq}\n")

    with open(list_file, "a") as f:
        f.write(f"{fasta_base}_vs_{pdb_base}\n")

    print(f"Saved {output_file} — target: {target_name} ({len(target_seq)} aa), binder: {len(binder_seq)} aa")
