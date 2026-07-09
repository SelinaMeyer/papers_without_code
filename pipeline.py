import argparse
import os
from typing import Optional


def default_conference_name(conference: str) -> str:
    """Return full analysis name for a conference abbreviation."""
    names = {
        "acl": "Association for Computational Linguistics",
        "cl": "Computational Linguistics",
        "naacl_coling": "NAACL and COLING",
    }
    return names.get(conference, conference)


def resolve_analysis_input(conference: str) -> str:
    """Resolve the preferred merged CSV for analysist."""
    output_dir = os.path.join("extracted_links", conference)
    os.makedirs(output_dir, exist_ok=True)
    merged_regex = os.path.join(output_dir, f"extracted_github_links_all_{conference}.csv")
    return merged_regex


def run_automatic_pipeline(selection: str, conference_name: Optional[str], plots: bool) -> None:
    """Run extraction, merge, and automatic analysis for one event or batch selector."""
    from comparison_of_github_repo_availability import run_analysis
    from extract_all_github_repos import run_extraction
    from merge_files import merge_conference

    conference = selection if "-" not in selection else selection.split("-", 1)[0]
    run_extraction(selection)
    merge_conference(conference)
    run_analysis(
        conference_name=conference_name or default_conference_name(conference),
        all_path=resolve_analysis_input(conference),
        get_plots=plots,
    )


def main() -> None:
    """Parse CLI arguments and dispatch to the selected pipeline stage."""
    parser = argparse.ArgumentParser(
        description="Top-level interface for the paper link extraction pipeline."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    auto_run = subparsers.add_parser(
        "auto-run",
        help="Fully reproducible automatic pipeline: extract, merge, and analyze without manual review augmentation.",
    )
    auto_run.add_argument("selection", help="Event or built-in batch selector, e.g. acl-2024, acl, cl")
    auto_run.add_argument("--conference-name", help="Display name used for analysis outputs")
    auto_run.add_argument("--plots", action="store_true", help="Generate plots during the analysis step")

    auto_extract = subparsers.add_parser(
        "auto-extract",
        help="Automatic stage: extract GitHub links from papers for an event or built-in batch selector.",
    )
    auto_extract.add_argument("selection", help="Event or built-in batch selector, e.g. acl-2024, acl, cl")

    auto_merge = subparsers.add_parser(
        "auto-merge",
        help="Automatic stage: merge extracted JSON snapshots into conference-level CSVs.",
    )
    auto_merge.add_argument("conference", help="Conference id, e.g. acl, cl, naacl_coling")

    auto_analyze = subparsers.add_parser(
        "auto-analyze",
        help="Automatic stage: analyze merged outputs without manual review augmentation.",
    )
    auto_analyze.add_argument("conference", help="Conference id, e.g. acl, cl, naacl_coling")
    auto_analyze.add_argument("--conference-name", help="Display name used for analysis outputs")
    auto_analyze.add_argument("--all-path", help="Override the merged CSV path")
    auto_analyze.add_argument("--plots", action="store_true", help="Generate plots")

    manual_analyze = subparsers.add_parser(
        "manual-analyze",
        help="Manual review augmentation: analyze merged outputs with a manually reviewed unavailable-link file.",
    )
    manual_analyze.add_argument("conference", help="Conference id, e.g. acl, cl, naacl_coling")
    manual_analyze.add_argument("--conference-name", help="Display name used for analysis outputs")
    manual_analyze.add_argument("--manual-review-file", required=True, help="Manually reviewed unavailable-link CSV")
    manual_analyze.add_argument("--all-path", help="Override the merged CSV path")
    manual_analyze.add_argument("--low-file-repos", help="Optional extra low-file manual-review CSV")
    manual_analyze.add_argument("--plots", action="store_true", help="Generate plots")
    manual_analyze.add_argument("--comparison", action="store_true", help="Generate comparison between venues")

    args = parser.parse_args()

    if args.command == "auto-run":
        run_automatic_pipeline(args.selection, args.conference_name, args.plots)
    elif args.command == "auto-extract":
        from extract_all_github_repos import run_extraction

        run_extraction(args.selection)
    elif args.command == "auto-merge":
        from merge_files import merge_conference

        merge_conference(args.conference)
    elif args.command == "auto-analyze":
        from comparison_of_github_repo_availability import run_analysis

        conference_name = args.conference_name or default_conference_name(args.conference)
        run_analysis(
            conference_name=conference_name,
            all_path=args.all_path or resolve_analysis_input(args.conference),
            get_plots=args.plots,
        )
    elif args.command == "manual-analyze":
        from comparison_of_github_repo_availability import run_analysis

        conference_name = args.conference_name or default_conference_name(args.conference)
        run_analysis(
            conference_name=conference_name,
            all_path=args.all_path or resolve_analysis_input(args.conference),
            get_plots=args.plots,
            compare_full_batch=args.comparison,
            manual_review_file=args.manual_review_file,
            low_file_repos=args.low_file_repos,
        )


if __name__ == "__main__":
    main()
