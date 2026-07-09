import json
import pandas as pd
import numpy as np
import os
import re
import json
import matplotlib.pyplot as plt
import seaborn as sns
#from extract_all_github_repos import get_github_data
import argparse
from typing import Any, Dict, List, Optional, Union

print(os.getcwd())

plt.rcParams.update({
    "font.size": 9,
    "axes.titlesize": 9,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
})

def normalize_year_column(df: pd.DataFrame, column: str = "year") -> pd.DataFrame:
    """Extract a numeric publication year from mixed year labels like `cl-2015`."""
    normalized = df.copy()
    normalized[column] = (
        normalized[column]
        .astype(str)
        .str.extract(r"(\d{4})")[0]
        .astype(int)
    )
    return normalized

def plot_line(
    df: pd.DataFrame,
    x: str,
    y: Union[str, Dict[str, str]],
    out_path: str,
    ylabel: str,
    legend: bool = True,
    hue: Optional[str] = None,
    width: float = 3,
    height: float = 2.4,
    yticks =  None,
    legend_in_plot=False
) -> None:
    """Create and save a line plot for one metric or a small set of named metrics."""
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    legend_space = 1.2 if legend else 0
    fig, ax = plt.subplots(figsize=(width + legend_space, height), constrained_layout=True)

    if isinstance(y, dict):
        for key in y.keys():
            if key not in df.columns:
                continue
            sns.lineplot(data=df, x=x, y=key, label=y[key], ax=ax)
    else:
        if hue is not None:
            sns.lineplot(data=df, x=x, y=y, hue=hue, ax=ax)
        else:
            sns.lineplot(data=df, x=x, y=y, ax=ax)

    ax.set(xlabel=x, ylabel=ylabel)

    ticks = np.arange(df["year"].min(), df["year"].max() + 1)
    ax.set_xticks(ticks)
    ax.set_xticklabels(ticks)
    ax.tick_params(axis="x", labelrotation=45)

    if yticks is not None:
        ax.set_yticks(yticks)

    if legend:
        ax.legend(loc="upper left")
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            if legend_in_plot:
                ax.legend(
                handles, 
                labels,
                loc="upper left", 
                borderaxespad=0
            )
            else:
                ax.legend(
                    handles, 
                    labels,
                    loc="upper left", 
                    bbox_to_anchor=(1.02, 1.0),
                    borderaxespad=0
                )

    fig.savefig(out_path, bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)


def plot_box(df: pd.DataFrame, x: str, y: str, out_path: str, ylabel: str) -> None:
    """Create and save a box plot for one metric grouped by a categorical field."""
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    WIDTH = 3
    HEIGHT = 2.4
    fig, ax = plt.subplots(figsize=(WIDTH, HEIGHT), constrained_layout=True)
    sns.boxplot(data=df, x=x, y=y, ax=ax)
    ax.set(xlabel=x, ylabel=ylabel)
    ax.tick_params(axis="x", rotation=45)
    plt.savefig(out_path, bbox_inches="tight", pad_inches=0.3)
    plt.close()

def compute_basic_stats(df: pd.DataFrame, conference_name: str) -> None: # if naacl_coling -> pass each df separately here
    """Write top-level repository-link counts for one conference dataset."""
    df_with_links = df.dropna(subset=["repo_url"]).copy()
    df_with_links = normalize_urls(df_with_links)
    df_with_links = df_with_links.drop_duplicates(subset=["paper_id", "normalized_url"])
    df_with_links = df_with_links[df_with_links["is_repo"] == True]

    with open(f"analysis/{conference_name}/basic_stats.txt", "w+") as f:
        json.dump({"total number of articles": df["paper_id"].nunique(),
        "total number of papers with github links": df_with_links["paper_id"].nunique(),
        "total number of parsed github links": len(df_with_links),
        "total number of unique parsed github links": df_with_links['normalized_url'].nunique(),
        "total number of papers without links": df["paper_id"].nunique() - df_with_links["paper_id"].nunique()
    }, f, indent=2)
    f.close()



def compute_yearly_stats(df: pd.DataFrame) -> pd.DataFrame:
    total = df.groupby("year")["paper_id"].nunique()
    df_with_links = df.dropna(subset=["repo_url"]).copy()
    df_with_links = normalize_urls(df_with_links)
    df_with_links = df_with_links.drop_duplicates(subset=["paper_id", "normalized_url"])
    df_with_links = df_with_links[df_with_links["is_repo"] == True]
    with_links = df_with_links.groupby("year")["paper_id"].nunique()
    number_links = df_with_links.groupby("year")["normalized_url"].nunique()

    grouped = (
        pd.concat([total, with_links, number_links], axis=1)
        .fillna(0)
        .reset_index()
    )

    grouped.columns = ["year", "total_papers", "papers_with_links", "link_count"]
    grouped["percentage_papers_with_links"] = (grouped["papers_with_links"]/grouped["total_papers"]) * 100

    return grouped.round(2)

def compute_proceedings_stats(df: pd.DataFrame, conference_name: str = "association for computational linguistics") -> pd.DataFrame:
    """Compute per-year, per-proceedings link coverage statistics."""

    total = df.groupby(["year", "proceedings"])["paper_id"].nunique()
    with_links = df[df["repo_url"].notna()].groupby(["year", "proceedings"])["paper_id"].nunique()

    result = (
        pd.concat([total, with_links], axis=1)
        .fillna(0)
        .reset_index()
    )

    result.columns = ["year", "proceedings", "total", "with_links"]
    result["percentage"] = result["with_links"] / result["total"]

    result["main"] = result["proceedings"].str.lower().str.contains(conference_name.lower()).map({True: "Yes", False: "No"})

    return result.round(2)

def compute_basic_unavailability_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Summarize unavailable repository counts overall and for self-hosted code/data links."""
    own_repo = df[df["paper_code_or_data"] == "yes"]

    all_unavailable = df.groupby("manual_check")["repo_url"].nunique()
    own_unavailable = own_repo.groupby("manual_check")["repo_url"].nunique()

    stats = pd.concat(
        [all_unavailable, own_unavailable],
        axis=1
    ).fillna(0)

    stats.columns = ["All repos", "Repos pointing to own code"]
    
    stats_complete = stats.sum().to_frame().T
    stats_complete.index = ["Total"]
    stats = pd.concat([stats, stats_complete])

    stats["share of unavailable pointing to own code"] = (
        stats["Repos pointing to own code"] / stats["All repos"]
    ) * 100


    return stats.round(2).reset_index()

def compute_yearly_unavailability_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute yearly unavailability statistics and return a wide-format DataFrame
    combining counts, shares, and relative proportions.

    Returns
    -------
    pd.DataFrame
        A DataFrame with one row per `year` and the following columns:

        Core identifier:
        - year : int
            The publication year.

        Count columns (absolute counts of `manual_check` categories):
        - all_<category> : int
            Number of records in the given year for each `manual_check` category
            across the full dataset.
        - own_<category> : int
            Number of records in the given year for each `manual_check` category
            restricted to rows where `paper_code_or_data == "yes"`.
        - all_total : int
            Total number of records in the year (sum over all categories).
        - own_total : int
            Total number of "own" records in the year.

        Share columns (within-group proportions, range [0, 1]):
        - all_percent_<category> : float
            Fraction of records in the given year belonging to each `manual_check`
            category across the full dataset.
        - own_percent_<category> : float
            Fraction of records in the given year belonging to each `manual_check`
            category within the "own" subset.

        Relative share columns (percentage, range [0, 100]):
        - share_<category> : float
            Percentage ratio of "own" counts to "all" counts for each category:
            (own_<category> / all_<category>) * 100.

    Notes
    -----
    - `<category>` corresponds to the unique values present in the `manual_check`
    column ("Placeholder", "404", "Empty").
    - Missing combinations are filled with 0.
    - All share columns are normalized per year.
    """

    all_unavailable = (
    df.drop_duplicates(subset=["year", "repo_url"])
      .groupby("year")["manual_check"]
      .value_counts()
      .unstack(fill_value=0)
    )

    all_unavailable["total"] = all_unavailable.sum(axis=1)
    own_unavailable = df[df["paper_code_or_data"]=="yes"]
    own_unavailable = (own_unavailable.drop_duplicates(subset=["year", "repo_url"])
        .groupby("year")["manual_check"]
        .value_counts()
        .unstack(fill_value=0)
    )

    own_unavailable["total"] = own_unavailable.sum(axis=1)

    all_pct = (
    df.drop_duplicates(subset=["year", "repo_url"])
      .groupby("year")["manual_check"]
      .value_counts(normalize=True)
      .unstack(fill_value=0) 
    ) * 100

    own_pct = (
        df[df["paper_code_or_data"] == "yes"]
        .drop_duplicates(subset=["year", "repo_url"])
        .groupby("year")["manual_check"]
        .value_counts(normalize=True)
        .unstack(fill_value=0) 
    ) * 100

    combined = pd.concat({
        "all": all_unavailable,
        "own": own_unavailable,
        "all_percent": all_pct,
        "own_percent": own_pct
    },
    axis=1).fillna(0)

    shares = combined["own"] / combined["all"] * 100

    combined.columns = ["_".join(col) for col in combined.columns]
    shares.columns = [f"share_own_of_all_{col}" for col in shares.columns]
    result = pd.concat([combined, shares], axis=1).reset_index()
    return result.round(2)

def analyse_data(
    conference_name: str,
    get_plots: bool, 
    df: pd.DataFrame,
    unavailable_df: Optional[pd.DataFrame] = None,
    ) -> None:
    """Compute availability statistics, write logs, and generate summary plots.

    Note: `unavailable_df` is expected to be provided and manually checked.
    """
    os.makedirs(f"analysis/{conference_name}", exist_ok=True)
    if get_plots:
        os.makedirs(f"Plots/{conference_name}", exist_ok=True)

    compute_basic_stats(df, conference_name)
    yearly_development = compute_yearly_stats(df)

    yearly_development.to_csv(f"analysis/{conference_name}/yearly_link_stats_overall.csv")
    yearly_development_by_event = compute_proceedings_stats(df)

    if get_plots:

        plot_line(yearly_development, x="year", y="percentage_papers_with_links", out_path=f"Plots/{conference_name}/development_of_github_links_in_collocated_by_year.png",
                ylabel="% Papers with Github Repository Links", legend=False, yticks=np.arange(10, 90, 10))
        
        plot_box(yearly_development_by_event[yearly_development_by_event["main"]=="Yes"],x="year", 
                y="percentage", out_path=f"Plots/{conference_name}/development_of_github_links_in_main_by_year.png",
                ylabel="% Papers with Github Repository Links")

    yearly_development_by_event.to_csv(f"analysis/{conference_name}/yearly_link_stats_by_event.csv")
    
    if unavailable_df is not None:
        unavailable_all = compute_basic_unavailability_stats(unavailable_df)
        unavailable_all.to_csv(f"analysis/{conference_name}/basic_unavailability_stats.csv")
        unavailable_yearly = compute_yearly_unavailability_stats(unavailable_df)

        unavailable_yearly = pd.merge(unavailable_yearly, yearly_development[["year", "link_count"]], on="year")
        unavailable_yearly["share of unavailable repos"] = unavailable_yearly["all_total"] / unavailable_yearly["link_count"] * 100
        unavailable_yearly.to_csv(f"analysis/{conference_name}/yearly_unavailability_stats.csv")

        if get_plots:
           
            unavailable_yearly["year"] = (
                unavailable_yearly["year"]
                .astype(str)                      
                .str.extract(r'(\d{4})')[0]      
                .astype(int)                     
            )
            plot_line(unavailable_yearly, x="year", y="share_own_of_all_total", 
                    out_path=f"Plots/{conference_name}/development_of_unavailable_own_github_links.png", 
                    ylabel="% Own Repository", width=3, legend=False)
            
            plot_line(unavailable_yearly, x="year", y="share of unavailable repos", 
                    out_path=f"Plots/{conference_name}/development_of_unavailable_github_links.png",
                    ylabel="% Unavailable", width=3.5, height=2, legend=False)
            
            plot_line(unavailable_yearly, x="year", y={"own_percent_Empty":"Empty",
                                                    "own_percent_Placeholder": "Placeholder",
                                                    "own_percent_404": "404",
                                                    "own_percent_Incorrect Link": "Incorrect Link"}, 
                    out_path=f"Plots/{conference_name}/development_of_unavailability_type_own_github_links.png", 
                    ylabel="% Unavailable")

            plot_line(unavailable_yearly, x="year", y={"own_Empty":"Empty",
                                                    "own_Placeholder": "Placeholder",
                                                    "own_404": "404",
                                                    "own_Incorrect Link": "Incorrect Link"}, 
                    out_path=f"Plots/{conference_name}/number_of_unavailability_type_own_github_links.png", 
                    ylabel="Count", yticks=np.arange(0,90,20), legend_in_plot=True, width=2.55)
            plot_line(unavailable_yearly, x="year", y={"all_Empty":"Empty (total)",
                                                    "all_Placeholder": "Placeholder (total)",
                                                    "all_404": "404 (total)",
                                                    "all_Incorrect Link": "Incorrect Link (total)"}, 
                    out_path=f"Plots/{conference_name}/number_of_unavailability_type_github_links.png", 
                    ylabel="Count")
            since_21 = unavailable_df[unavailable_df["year"] >= 2021] 
            since_21_own = since_21[since_21["paper_code_or_data"] == "yes"]
            since_21_venues = since_21_own["paper_id"].str.split(".", expand=True)
            counts = since_21_venues[1].value_counts()
            counts.to_csv(f"analysis/{conference_name}/event_counts.csv")

            # keep top N categories
            top_n = 5
            top_counts = counts.head(top_n)

            # sum the rest into "Other events"
            other_sum = counts.iloc[top_n:].sum()

            # combine
            plot_counts = top_counts.copy()
            if other_sum > 0:
                plot_counts["Other"] = other_sum

            # plot
            wedges, texts, autotexts = plt.pie(plot_counts, labels=plot_counts.index, autopct='%1.1f%%')
            # label text (category names)
            for t in texts:
                t.set_fontsize(10)

            # percentage text
            for at in autotexts:
                at.set_fontsize(8)
            plt.savefig(f"Plots/{conference_name}/event_plot.png", bbox_inches="tight")
            plt.close()

    return

def normalize_urls(df):
    df["normalized_url"] = df["repo_url"].str.strip("/.,);:!\"' <>").str.lower().str.strip()
    df["normalized_url"] = df["normalized_url"].str.replace("\n", "")
    df["normalized_url"] = df["normalized_url"].str.replace(" ", "")
    return df

def run_analysis(
    conference_name: str,
    all_path: str,
    get_plots: bool = False,
    manual_review_file: Optional[str] = None,
    low_file_repos: Optional[str] = None,
    compare_full_batch: bool = False
) -> None:
    """Load extracted links, optionally merge manual-review annotations, and run analysis outputs."""

    df = pd.read_csv(all_path)
    df = normalize_year_column(df)

    if manual_review_file:
        unavailable_df = pd.read_csv(manual_review_file)
        unavailable_df = unavailable_df[unavailable_df["manual_check"].isin(["not_available", "empty", "coming_soon", "incorrect_link"])]
        unavailable_df = unavailable_df[["year", "proceedings", "paper_id", "repo_url", "number_of_files", "manual_check", "paper_code_or_data"]]
        if low_file_repos:
            pl_df = pd.read_csv(low_file_repos)
            pl_df = pl_df[pl_df["manual_check"] == "coming_soon"]
            unavailable_df = pd.concat([unavailable_df, pl_df])
        unavailable_df = normalize_year_column(unavailable_df)
        unavailable_df["manual_check"] = unavailable_df["manual_check"].replace({
            "not_available": "404",
            "empty": "Empty",
            "coming_soon": "Placeholder",
            "incorrect_link": "Incorrect Link"
        })
        analyse_data(conference_name, get_plots, df, unavailable_df)
    else:
        analyse_data(conference_name, get_plots, df)

    if conference_name.lower() == "acl":
        dat = pd.read_csv(f"analysis/{conference_name}/yearly_unavailability_stats.csv")
        means_before_2025 = (
            dat[dat["year"] != 2025]
            .mean(numeric_only=True)
            .round(2)
            .to_frame()
            .T
        )
        means_before_2025["subset"] = "mean_before_2025"

        means_with_2025 = (
            dat.mean(numeric_only=True)
            .round(2)
            .to_frame()
            .T
        )
        means_with_2025["subset"] = "mean_with_2025"

        only_2025 = dat[dat["year"] == 2025].round(2)
        only_2025["subset"] = "only_2025"

        result = pd.concat(
            [means_before_2025, only_2025, means_with_2025],
            ignore_index=True,
            sort=False,
        )

        result.to_csv(
            "analysis/acl/combined_yearly_unavailability_stats_all_acl.csv",
            index=False,
        )

    if compare_full_batch:
        # traverse through analysis directories and compare all batches for the given conference
        analysis_dir = f"analysis/"
        if os.path.exists(analysis_dir):
            combined_df = pd.DataFrame()
            for root, dirs, files in os.walk(analysis_dir):
                for file in files:
                    if file == "yearly_unavailability_stats.csv":
                        batch_df = pd.read_csv(os.path.join(root, file))
                        batch_df["venue"] = os.path.basename(root)
                        combined_df = pd.concat([combined_df, batch_df], ignore_index=True)
            combined_df.round(2).to_csv(f"analysis/combined_yearly_unavailability_stats.csv", index=False)
        


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Analyze extracted repository links with or without manual review augmentation.")
    
    parser.add_argument(
        "conference_name",
        help="Name of the conference to parse"
    )
    
    parser.add_argument(
        "all",
        help="Filepath to all extracted links",
    )

    parser.add_argument(
        "--manual-review-file",
        "--unavailable",
        dest="manual_review_file",
        help="Filepath to manually reviewed unavailable links"
    )
    parser.add_argument(
        "--low-file-repos",
        help="Optional extra manually reviewed low-file repository CSV to merge into the unavailable set"
    )

    parser.add_argument(
    "--get_plots",
    action="store_true",
    help="Generate plots"
    )

    parser.add_argument(
    "--compare_full_batch",
    action="store_true",
    help="Compare all conference batches"
    )
    
    args = parser.parse_args()
    print(args)

    run_analysis(
        conference_name=args.conference_name,
        all_path=args.all,
        get_plots=args.get_plots,
        manual_review_file=args.manual_review_file,
        low_file_repos=args.low_file_repos,
        compare_full_batch=args.compare_full_batch
    )