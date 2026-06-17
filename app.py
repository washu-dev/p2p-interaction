"""Sequence-to-Selective-Binder Platform Streamlit prototype."""

from __future__ import annotations

import json
import time
from typing import Any

import pandas as pd
import streamlit as st

from utils.fasta_utils import (
    decode_uploaded_file,
    uploaded_files_to_targets,
    validate_fasta,
)
from utils.mock_backend import generate_binder_designs, predict_structures
from utils.scoring import screen_binders
from utils.visualization import create_interaction_heatmap


PAGES = [
    "Home",
    "Upload",
    "Structure Prediction",
    "Binder Design",
    "Selectivity Screening",
    "Visualization",
    "Download",
]
MAX_TARGETS_PER_CLASS = 20


st.set_page_config(
    page_title="Sequence-to-Selective-Binder Platform",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at 88% 5%, rgba(124, 58, 237, 0.08), transparent 24rem),
                radial-gradient(circle at 18% 0%, rgba(37, 99, 235, 0.08), transparent 27rem),
                #f8fafc;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f172a 0%, #172554 100%);
        }
        [data-testid="stSidebar"] * {
            color: #f8fafc;
        }
        [data-testid="stSidebar"] .stButton button {
            width: 100%;
            border: 1px solid rgba(255,255,255,0.14);
            background: rgba(255,255,255,0.06);
            text-align: left;
        }
        [data-testid="stSidebar"] .stButton button:hover {
            border-color: #818cf8;
            background: rgba(99,102,241,0.22);
        }
        .hero {
            padding: 2.4rem 2.6rem;
            border-radius: 24px;
            color: white;
            background: linear-gradient(120deg, #1d4ed8 0%, #6d28d9 100%);
            box-shadow: 0 18px 50px rgba(59, 70, 180, 0.22);
            margin-bottom: 1.5rem;
        }
        .hero h1 {
            margin: 0 0 0.55rem 0;
            font-size: clamp(2.1rem, 4vw, 3.5rem);
            line-height: 1.05;
        }
        .hero p {
            margin: 0;
            font-size: 1.15rem;
            opacity: 0.9;
        }
        .science-card {
            min-height: 135px;
            padding: 1.1rem;
            border: 1px solid #dbeafe;
            border-radius: 16px;
            background: rgba(255,255,255,0.88);
            box-shadow: 0 8px 24px rgba(30, 64, 175, 0.06);
        }
        .science-card h4 {
            color: #1e3a8a;
            margin: 0 0 0.45rem 0;
        }
        .step-chip {
            display: inline-block;
            padding: 0.24rem 0.55rem;
            border-radius: 999px;
            color: #4338ca;
            background: #eef2ff;
            font-size: 0.76rem;
            font-weight: 700;
            margin-bottom: 0.55rem;
        }
        .viewer-placeholder {
            display: flex;
            min-height: 390px;
            align-items: center;
            justify-content: center;
            text-align: center;
            padding: 2rem;
            border: 2px dashed #a5b4fc;
            border-radius: 18px;
            color: #475569;
            background: linear-gradient(145deg, #eff6ff, #f5f3ff);
        }
        .target-positive {
            border-left: 5px solid #2563eb;
            padding-left: 0.8rem;
        }
        .target-negative {
            border-left: 5px solid #7c3aed;
            padding-left: 0.8rem;
        }
        .small-muted {
            color: #64748b;
            font-size: 0.87rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def initialize_state() -> None:
    defaults: dict[str, Any] = {
        "active_page": "Home",
        "positive_targets": [],
        "negative_targets": [],
        "predicted_structures": {},
        "binder_designs": [],
        "bindcraft_settings": {},
        "screening_results": None,
        "score_matrix": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def navigate(page: str) -> None:
    st.session_state.active_page = page


def reset_workspace() -> None:
    """Clear all per-user data and return to the home page."""
    st.session_state.clear()
    st.session_state.active_page = "Home"


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("## Selective Binder")
        st.caption("Sequence-first design workspace")
        st.markdown("---")
        for index, page in enumerate(PAGES, start=1):
            label = f"{index}. {page}"
            st.button(
                label,
                key=f"nav_{page}",
                on_click=navigate,
                args=(page,),
                type="primary" if st.session_state.active_page == page else "secondary",
                width="stretch",
            )

        st.markdown("---")
        positive_count = len(st.session_state.positive_targets)
        negative_count = len(st.session_state.negative_targets)
        binder_count = len(st.session_state.binder_designs)
        st.caption("Workspace status")
        st.write(f"Positive targets: **{positive_count}**")
        st.write(f"Negative targets: **{negative_count}**")
        st.write(f"Binder designs: **{binder_count}**")
        st.caption("Prototype mode · Mock computation only")
        st.markdown("---")
        st.button(
            "Reset workspace",
            on_click=reset_workspace,
            width="stretch",
        )


def section_header(title: str, description: str, step: int) -> None:
    st.markdown(f'<span class="step-chip">STEP {step} OF 7</span>', unsafe_allow_html=True)
    st.title(title)
    st.caption(description)


def render_target_summary(targets: list[dict[str, Any]], target_type: str) -> None:
    css_class = "target-positive" if target_type == "Positive" else "target-negative"
    for target in targets:
        st.markdown(
            f"""
            <div class="{css_class}">
                <strong>{target["id"]}</strong>
                <div class="small-muted">
                    {target["filename"]} · {len(target["sequence"])} residues · {target_type}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write("")


def home_page() -> None:
    st.markdown(
        """
        <div class="hero">
            <h1>Sequence-to-Selective-Binder Platform</h1>
            <p>Design selective protein binders directly from FASTA sequences.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("### From sequence to ranked selective candidates")
    st.write(
        "A guided computational workflow for designing binders that favor desired "
        "protein targets while avoiding specified off-targets."
    )
    st.info(
        "Public demonstration: results are simulated and are not suitable for "
        "experimental decisions. Do not upload confidential or proprietary sequences."
    )
    pipeline = [
        ("01", "FASTA Upload", "Define positive and negative protein targets."),
        ("02", "Structure Prediction", "Predict target structures from sequence."),
        ("03", "Binder Design", "Generate and optimize candidate binders."),
        ("04", "Selectivity Screening", "Score every binder against every target."),
        ("05", "Visualization", "Inspect rankings, heatmaps, and structures."),
        ("06", "Download", "Export sequences, scores, and a summary report."),
    ]
    columns = st.columns(3)
    for index, (number, title, description) in enumerate(pipeline):
        with columns[index % 3]:
            st.markdown(
                f"""
                <div class="science-card">
                    <span class="step-chip">{number}</span>
                    <h4>{title}</h4>
                    <div class="small-muted">{description}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.write("")

    st.info(
        "Pipeline: FASTA Upload → Structure Prediction → Binder Design → "
        "Selectivity Screening → Visualization → Download"
    )
    st.button(
        "Start a new design",
        type="primary",
        on_click=navigate,
        args=("Upload",),
    )


def preview_uploads(uploaded_files: list[Any] | None, label: str) -> None:
    for uploaded_file in uploaded_files or []:
        with st.expander(f"{uploaded_file.name} · {label}", expanded=False):
            try:
                content = decode_uploaded_file(uploaded_file)
                valid, message = validate_fasta(content)
                if valid:
                    st.success(message)
                else:
                    st.error(message)
                preview = content[:1200]
                if len(content) > 1200:
                    preview += "\n... [preview truncated]"
                st.code(preview, language="text")
            except UnicodeDecodeError:
                st.error("This file is not valid UTF-8 text.")


def upload_page() -> None:
    section_header(
        "Upload FASTA Targets",
        "Add proteins to favor and off-targets to avoid.",
        2,
    )
    positive_column, negative_column = st.columns(2)
    with positive_column:
        st.markdown("#### Positive targets")
        st.caption("Binders should interact strongly with these proteins.")
        positive_uploads = st.file_uploader(
            "Upload positive target FASTA files",
            type=["fasta", "fa", "faa", "txt"],
            accept_multiple_files=True,
            key="positive_uploads",
        )
        preview_uploads(positive_uploads, "Positive")

    with negative_column:
        st.markdown("#### Negative / off-targets")
        st.caption("Binders should interact weakly or not at all with these proteins.")
        negative_uploads = st.file_uploader(
            "Upload negative target FASTA files",
            type=["fasta", "fa", "faa", "txt"],
            accept_multiple_files=True,
            key="negative_uploads",
        )
        preview_uploads(negative_uploads, "Negative")

    positive_targets, positive_errors = uploaded_files_to_targets(
        positive_uploads, "positive"
    )
    negative_targets, negative_errors = uploaded_files_to_targets(
        negative_uploads, "negative"
    )
    errors = positive_errors + negative_errors
    if len(positive_targets) > MAX_TARGETS_PER_CLASS:
        errors.append(
            f"Positive targets are limited to {MAX_TARGETS_PER_CLASS} per session."
        )
    if len(negative_targets) > MAX_TARGETS_PER_CLASS:
        errors.append(
            f"Negative targets are limited to {MAX_TARGETS_PER_CLASS} per session."
        )

    st.markdown("---")
    if positive_targets or negative_targets:
        st.write(
            f"Ready to import **{len(positive_targets)} positive** and "
            f"**{len(negative_targets)} negative** target record(s)."
        )
    if not negative_targets:
        st.warning(
            "No valid negative targets are selected. The prototype can continue, "
            "but selectivity is most informative when off-targets are provided."
        )
    st.caption(
        "Public demo limits: 5 MB per file, 5,000 residues per sequence, and "
        f"{MAX_TARGETS_PER_CLASS} targets per class. Uploaded data stays in the "
        "current Streamlit session and is not intentionally persisted by this app."
    )
    for error in errors:
        st.error(error)

    can_continue = bool(positive_targets) and not errors
    if st.button(
        "Continue to Structure Prediction",
        type="primary",
        disabled=not can_continue,
    ):
        st.session_state.positive_targets = positive_targets
        st.session_state.negative_targets = negative_targets
        st.session_state.predicted_structures = {}
        st.session_state.binder_designs = []
        st.session_state.bindcraft_settings = {}
        st.session_state.screening_results = None
        st.session_state.score_matrix = None
        navigate("Structure Prediction")
        st.rerun()


def structure_prediction_page() -> None:
    section_header(
        "Structure Prediction",
        "ColabFold / AlphaFold2 structure prediction",
        3,
    )
    targets = st.session_state.positive_targets + st.session_state.negative_targets
    if not targets:
        st.warning("Upload at least one valid positive FASTA target first.")
        st.button("Go to Upload", on_click=navigate, args=("Upload",))
        return

    st.markdown("#### Target queue")
    render_target_summary(st.session_state.positive_targets, "Positive")
    render_target_summary(st.session_state.negative_targets, "Negative")

    if st.button("Run Mock Structure Prediction", type="primary"):
        progress = st.progress(0, text="Preparing sequence inputs...")
        total_steps = max(1, len(targets) * 4)
        current_step = 0
        status = st.empty()
        for target in targets:
            for stage in ["MSA search", "Model inference", "Relaxation", "Saving PDB"]:
                current_step += 1
                status.write(f'**{target["id"]}** · {stage}')
                progress.progress(
                    current_step / total_steps,
                    text=f'Predicting {target["id"]}: {stage}',
                )
                time.sleep(0.08)
        st.session_state.predicted_structures = predict_structures(targets)
        status.success("Mock structure prediction complete.")

    predictions = st.session_state.predicted_structures
    if predictions:
        st.markdown("#### Predicted structures")
        prediction_df = pd.DataFrame(predictions.values()).rename(
            columns={
                "target_id": "Target",
                "pdb_filename": "Output PDB",
                "mean_plddt": "Mock mean pLDDT",
                "status": "Status",
            }
        )
        st.dataframe(prediction_df, width="stretch", hide_index=True)
        st.button(
            "Continue to Binder Design",
            type="primary",
            on_click=navigate,
            args=("Binder Design",),
        )
    else:
        st.info("Run the mock job to generate predicted PDB filenames.")


def binder_design_page() -> None:
    section_header(
        "Binder Design",
        "Configure mock BindCraft design and ProteinMPNN sequence optimization.",
        4,
    )
    if not st.session_state.predicted_structures:
        st.warning("Complete structure prediction before designing binders.")
        st.button(
            "Go to Structure Prediction",
            on_click=navigate,
            args=("Structure Prediction",),
        )
        return

    target_column, parameter_column = st.columns([1, 1.25])
    with target_column:
        st.markdown("#### Design targets")
        st.markdown("**Positive targets**")
        render_target_summary(st.session_state.positive_targets, "Positive")
        st.markdown("**Negative targets**")
        if st.session_state.negative_targets:
            render_target_summary(st.session_state.negative_targets, "Negative")
        else:
            st.caption("No negative targets supplied.")

    with parameter_column:
        st.markdown("#### Design parameters")
        length_columns = st.columns(2)
        with length_columns[0]:
            binder_length_min = st.number_input(
                "Binder length min", min_value=20, max_value=300, value=50, step=5
            )
        with length_columns[1]:
            binder_length_max = st.number_input(
                "Binder length max", min_value=20, max_value=300, value=80, step=5
            )
        number_of_designs = st.number_input(
            "Number of designs", min_value=1, max_value=100, value=12, step=1
        )
        hotspot_residues = st.text_input(
            "Target hotspot residues (optional)",
            placeholder="Example: A45,A48,A52 or 45,48,52",
        )
        st.caption(
            "The production backend will translate these values into BindCraft "
            "settings JSON files."
        )
        if binder_length_min > binder_length_max:
            st.error("Minimum binder length must not exceed maximum binder length.")

        run_disabled = binder_length_min > binder_length_max
        if st.button(
            "Run BindCraft Design",
            type="primary",
            disabled=run_disabled,
            width="stretch",
        ):
            stages = [
                "Target structure",
                "BindCraft",
                "ProteinMPNN",
                "AF2 validation",
                "Filtered binders",
            ]
            progress = st.progress(0, text="Starting mock design pipeline...")
            stage_status = st.empty()
            for index, stage in enumerate(stages, start=1):
                stage_status.write(f"Running: **{stage}**")
                progress.progress(index / len(stages), text=f"{stage} complete")
                time.sleep(0.18)

            designs, settings = generate_binder_designs(
                st.session_state.positive_targets,
                st.session_state.negative_targets,
                int(binder_length_min),
                int(binder_length_max),
                int(number_of_designs),
                hotspot_residues,
            )
            st.session_state.binder_designs = designs
            st.session_state.bindcraft_settings = settings
            st.session_state.screening_results = None
            st.session_state.score_matrix = None
            stage_status.success(f"Generated {len(designs)} mock binder candidates.")

    if st.session_state.bindcraft_settings:
        with st.expander("Generated BindCraft settings JSON", expanded=False):
            st.code(
                json.dumps(st.session_state.bindcraft_settings, indent=2),
                language="json",
            )

    if st.session_state.binder_designs:
        st.markdown("#### Mock binder candidates")
        design_df = pd.DataFrame(st.session_state.binder_designs).rename(
            columns={
                "binder_id": "Binder ID",
                "sequence": "Sequence",
                "length": "Length",
            }
        )
        st.dataframe(design_df, width="stretch", hide_index=True)
        st.button(
            "Continue to Selectivity Screening",
            type="primary",
            on_click=navigate,
            args=("Selectivity Screening",),
        )


def selectivity_screening_page() -> None:
    section_header(
        "Selectivity Screening",
        "Compare each candidate against positive targets and off-targets.",
        5,
    )
    if not st.session_state.binder_designs:
        st.warning("Generate binder candidates before running selectivity screening.")
        st.button("Go to Binder Design", on_click=navigate, args=("Binder Design",))
        return

    st.latex(
        r"\mathrm{selectivity\ score}="
        r"\mathrm{average\ positive\ score}-"
        r"\mathrm{average\ negative\ score}"
    )
    st.caption("Prototype pass threshold: selectivity score ≥ 0.35")

    if st.button("Run Mock Selectivity Screening", type="primary"):
        progress = st.progress(0, text="Preparing binder-target pairs...")
        binder_count = len(st.session_state.binder_designs)
        for index, binder in enumerate(st.session_state.binder_designs, start=1):
            progress.progress(
                index / binder_count,
                text=f'Scoring {binder["binder_id"]} against all targets',
            )
            time.sleep(0.04)
        results, score_matrix = screen_binders(
            st.session_state.binder_designs,
            st.session_state.positive_targets,
            st.session_state.negative_targets,
        )
        st.session_state.screening_results = results
        st.session_state.score_matrix = score_matrix

    results = st.session_state.screening_results
    if results is not None:
        pass_count = int((results["Status"] == "Pass").sum())
        metrics = st.columns(3)
        metrics[0].metric("Candidates screened", len(results))
        metrics[1].metric("Passing binders", pass_count)
        metrics[2].metric(
            "Top selectivity",
            f'{results["Selectivity score"].max():.3f}',
        )

        def color_status(value: str) -> str:
            if value == "Pass":
                return "background-color: #dcfce7; color: #166534; font-weight: 700"
            if value == "Fail":
                return "background-color: #fee2e2; color: #991b1b; font-weight: 700"
            return ""

        st.dataframe(
            results.style.map(color_status, subset=["Status"]).format(
                {
                    "Positive target score average": "{:.3f}",
                    "Negative target score average": "{:.3f}",
                    "Selectivity score": "{:.3f}",
                }
            ),
            width="stretch",
            hide_index=True,
        )
        st.button(
            "Continue to Visualization",
            type="primary",
            on_click=navigate,
            args=("Visualization",),
        )
    else:
        st.info("Run the mock screen to calculate and rank selectivity scores.")


def visualization_page() -> None:
    section_header(
        "Visualization",
        "Explore binder-target interaction patterns and structure placeholders.",
        6,
    )
    if st.session_state.score_matrix is None:
        st.warning("Run selectivity screening to create visualization data.")
        st.button(
            "Go to Selectivity Screening",
            on_click=navigate,
            args=("Selectivity Screening",),
        )
        return

    positive_ids = [target["id"] for target in st.session_state.positive_targets]
    negative_ids = [target["id"] for target in st.session_state.negative_targets]
    st.markdown("#### Binder-target interaction heatmap")
    st.caption(
        "Blue labels mark positive targets; purple labels mark negative/off-targets. "
        "Higher values indicate stronger mock binding."
    )
    figure = create_interaction_heatmap(
        st.session_state.score_matrix,
        positive_ids,
        negative_ids,
    )
    st.plotly_chart(figure, width="stretch")

    st.markdown("#### Structure viewer")
    viewer_column, selection_column = st.columns([2, 1])
    with selection_column:
        binder_ids = st.session_state.screening_results["Binder ID"].tolist()
        st.selectbox("Binder", binder_ids)
        all_target_ids = positive_ids + negative_ids
        st.selectbox("Target", all_target_ids)
        st.caption(
            "Selections will drive molecular loading once a real structure viewer "
            "and PDB artifacts are connected."
        )
    with viewer_column:
        st.markdown(
            """
            <div class="viewer-placeholder">
                <div>
                    <h3>3D Structure Viewer</h3>
                    <p>3D structure viewer will be integrated with<br>
                    py3Dmol / Mol* / NGL Viewer.</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.button(
        "Continue to Download",
        type="primary",
        on_click=navigate,
        args=("Download",),
    )


def build_summary_report() -> str:
    results = st.session_state.screening_results
    settings = st.session_state.bindcraft_settings
    top_binder = results.iloc[0]
    passing = int((results["Status"] == "Pass").sum())
    lines = [
        "Sequence-to-Selective-Binder Platform",
        "Mock Design Summary Report",
        "=" * 44,
        "",
        f"Positive targets: {', '.join(settings.get('positive_targets', []))}",
        f"Negative targets: {', '.join(settings.get('negative_targets', [])) or 'None'}",
        f"Binder length range: {settings.get('binder_length_min')}-{settings.get('binder_length_max')}",
        f"Candidates generated: {len(results)}",
        f"Candidates passing: {passing}",
        "",
        "Top-ranked binder",
        f"Binder ID: {top_binder['Binder ID']}",
        f"Sequence: {top_binder['Sequence']}",
        f"Positive score average: {top_binder['Positive target score average']:.3f}",
        f"Negative score average: {top_binder['Negative target score average']:.3f}",
        f"Selectivity score: {top_binder['Selectivity score']:.3f}",
        f"Status: {top_binder['Status']}",
        "",
        "NOTE: All structures, sequences, and scores in this report are mock outputs.",
    ]
    return "\n".join(lines)


def download_page() -> None:
    section_header(
        "Download Results",
        "Export mock binder sequences, screening scores, and a summary report.",
        7,
    )
    if st.session_state.screening_results is None:
        st.warning("Complete selectivity screening before exporting results.")
        st.button(
            "Go to Selectivity Screening",
            on_click=navigate,
            args=("Selectivity Screening",),
        )
        return

    results = st.session_state.screening_results
    sequences_csv = results[["Binder ID", "Sequence", "Status"]].to_csv(index=False)
    scores_export = results.merge(
        st.session_state.score_matrix.reset_index(),
        on="Binder ID",
        how="left",
    )
    scores_csv = scores_export.to_csv(index=False)
    summary_report = build_summary_report()

    st.markdown("#### Export package")
    download_columns = st.columns(3)
    with download_columns[0]:
        st.markdown(
            """
            <div class="science-card">
                <h4>binder_sequences.csv</h4>
                <div class="small-muted">Candidate IDs, amino-acid sequences, and pass/fail status.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.download_button(
            "Download sequences",
            data=sequences_csv,
            file_name="binder_sequences.csv",
            mime="text/csv",
            width="stretch",
        )
    with download_columns[1]:
        st.markdown(
            """
            <div class="science-card">
                <h4>binder_scores.csv</h4>
                <div class="small-muted">Ranked summaries plus per-target interaction scores.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.download_button(
            "Download scores",
            data=scores_csv,
            file_name="binder_scores.csv",
            mime="text/csv",
            width="stretch",
        )
    with download_columns[2]:
        st.markdown(
            """
            <div class="science-card">
                <h4>summary_report.txt</h4>
                <div class="small-muted">Run configuration and the top-ranked candidate.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.download_button(
            "Download report",
            data=summary_report,
            file_name="summary_report.txt",
            mime="text/plain",
            width="stretch",
        )

    with st.expander("Preview summary report"):
        st.code(summary_report, language="text")
    st.success("Mock result files are ready for download.")


def main() -> None:
    inject_styles()
    initialize_state()
    render_sidebar()

    page_renderers = {
        "Home": home_page,
        "Upload": upload_page,
        "Structure Prediction": structure_prediction_page,
        "Binder Design": binder_design_page,
        "Selectivity Screening": selectivity_screening_page,
        "Visualization": visualization_page,
        "Download": download_page,
    }
    page_renderers[st.session_state.active_page]()


if __name__ == "__main__":
    main()
