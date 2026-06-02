# P2P Interaction: A Digital Framework for Selective Targeting of Undruggable Protein–Protein Interactions

## Overview

This project develops an **AI-driven computational framework** that integrates structure prediction, interface modeling, and generative protein design to create **paralog-selective inhibitors** of disease-relevant protein–protein interactions (PPIs).

**Project ID**: #1961  
**Competition**: Digital Transformation Research Corps (AY2025-2026)

## Research Team

- **PI**: Robi Mitra, MD, PhD | School of Medicine | [rmitra@wustl.edu](mailto:rmitra@wustl.edu)
- **Co-PI**: Jeff Milbrandt, MD, PhD | School of Medicine | [jmilbrandt@wustl.edu](mailto:jmilbrandt@wustl.edu)
- **Mentoring Team**: McDonnell Genome Institute's Biominer computational biology team (2 PhD-level scientists + 1 software engineer)

---

## Project Abstract

Many disease-critical protein–protein interactions remain **undruggable** because they involve extended binding interfaces that are difficult to disrupt using conventional small-molecule approaches. This challenge is further compounded by the prevalence of closely related paralogous proteins that demand high target selectivity.

Recent advances in protein structure prediction (AlphaFold) and generative protein design now enable the computational design of peptide and miniprotein inhibitors that specifically bind their targets with high affinities. This project creates an AI-driven computational framework that enables **precise modulation of disease-relevant cellular signaling pathways** while minimizing off-target effects.

### Disease Focus: Amyotrophic Lateral Sclerosis (ALS)

As a biologically rigorous test case, we focus on the **LATS2–TDP-43 interaction** in ALS:
- Cytoplasmic mislocalization of TDP-43 is the central molecular defect in nearly all ALS cases
- LATS2 directly phosphorylates TDP-43, driving pathological mislocalization
- Selective disruption of LATS2 (but not its paralog LATS1) reverses neuronal pathology
- Provides demanding but highly relevant benchmark for paralog-selective inhibitor design

---

## Specific Aims

### Aim 1: Develop an AI-Driven Computational Framework for Paralog-Selective PPI Inhibition

**Objective**: Develop and implement a computational pipeline integrating:
1. Structure prediction
2. Interface modeling
3. Generative protein design

**Deliverables** (10-week timeline):
- ✅ Reusable computational pipeline for paralog-selective PPI inhibitor design
- ✅ Set of high-confidence peptide and miniprotein candidate inhibitors
- ✅ Quantitative in silico metrics supporting predicted specificity
- ✅ Top 30 designs synthesized and experimentally validated in established ALS models

---

## Research Plan: Four Main Tasks

### Task 1: Structure Prediction and Modeling
- Generate structural models of LATS2–TDP-43 interaction using **AlphaFold-Multimer** (ColabFold)
- Model LATS1 in parallel to explicitly address paralog selectivity
- Analyze interface properties (contact residues, buried surface area, energetic contributions) using **PyRosetta**
- **Outcome**: High-confidence interface models with residue-level annotations defining targetable regions

### Task 2: Generative Design of Inhibitory Peptides and Miniproteins
- Structure-guided design using **Rosetta-based** protocols (peptide docking, binder design)
- Sequence optimization using **ProteinMPNN** (neural network-based tool)
- Benchmark **RFdiffusion** diffusion-based approaches against Rosetta designs
- Generate multiple design families to mitigate model uncertainty
- **Outcome**: Diverse set of candidate peptide and miniprotein designs

### Task 3: In Silico Scoring and Paralog Selectivity Assessment
- Evaluate candidates using quantitative, structure-based scoring metrics
- Assess predicted binding affinity, interface stability, structural plausibility
- **Cross-dock** top candidates against LATS1 for direct LATS2 vs. LATS1 comparison
- Rank designs based on combined **affinity–selectivity criteria**
- Create "design cards" for each shortlisted candidate
- **Outcome**: Ranked shortlist with selectivity metrics and design rationales

### Task 4: Pipeline Packaging and Deliverables
- Package end-to-end workflow with tool versions, parameters, and data provenance
- **Deliverables**:
  - Documented, reproducible computational pipeline
  - Ranked shortlist of high-confidence inhibitors
  - Synthesis-ready sequences and specifications
- Experimental validation: Synthesize and evaluate ~30 top-ranked designs in human iPSC-derived motor neuron assays

---

## Timeline

| Weeks | Focus |
|-------|-------|
| 1–2 | Tool familiarization, benchmarking, interface modeling |
| 3–6 | Generative design and iteration |
| 7–9 | Scoring, selectivity analysis, prioritization |
| 10 | Pipeline finalization and experimental handoff |

---

## Key Innovation

This project is innovative at multiple levels:

1. **Conceptual**: Reframes paralog-selective PPI inhibition as a computational design problem
2. **Technical**: Integrates structure prediction, interface modeling, generative design, and selectivity-aware scoring into a unified AI-driven pipeline
3. **Translational**: Delivers experimentally testable peptide and miniprotein inhibitors evaluated in disease-relevant human neuron models

**Broader Impact**: Establishes a generalizable framework for selectively targeting previously undruggable protein–protein interactions beyond ALS.

---

## Student Learning Outcomes

Students will gain hands-on experience with:
- ✨ Modern AI and structure-based protein design tools
- 🔬 Reproducible computational research practices
- 🧬 Translation of computational predictions into experimentally testable hypotheses
- 💻 High-performance computing (HTCF cluster access)
- 🤝 Collaborative research in a mentored environment

---

## Mentoring & Resources

- **Weekly meetings** with PIs Rob Mitra and Jeff Milbrandt
- **Embedded support** from McDonnell Genome Institute's Biominer team:
  - 2 PhD-level computational biologists
  - 1 experienced software engineer and tool developer
- **High-performance compute access**: Center for Genome Science HTCF cluster
- **Domain expertise**: Milbrandt and Mitra lab biological expertise

---

## Future Directions & Funding

**External funding targets** upon program completion:
- 🏥 NIH grants
- 💰 Philanthropic funding sources

**Broader applications**: Framework can be applied to other disease-critical interactions where paralog selectivity has limited therapeutic progress, positioning us to pursue external funding and scale across biomedical applications.

---

## Computational Tools

- **AlphaFold-Multimer** / **ColabFold** — protein structure prediction
- **PyRosetta** — interface analysis and design
- **Rosetta** — structure-guided protein design
- **ProteinMPNN** — neural network-based sequence design
- **RFdiffusion** — diffusion-based generative design

## Experimental Assays

- Human iPSC-derived motor neuron models
- TDP-43 localization readouts
- Downstream splicing defect measurement
- Neuronal survival quantification

---

## Contact

For questions or collaboration inquiries:
- **Robi Mitra**: [rmitra@wustl.edu](mailto:rmitra@wustl.edu)
- **Jeff Milbrandt**: [jmilbrandt@wustl.edu](mailto:jmilbrandt@wustl.edu)

---

**Last Updated**: June 2, 2026  
**Submission Date**: January 15, 2026  
**Cycle**: AY2025-2026 Digital Transformation Research Corps
