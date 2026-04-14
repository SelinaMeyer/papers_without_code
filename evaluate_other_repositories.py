from merge_files import read_and_concatenate_json_files
from typing import Any, Dict, List, Optional
import json
import pandas as pd
import os
import seaborn as sns
import matplotlib.pyplot as plt
from comparison_of_github_repo_availability import plot_box, plot_line
import argparse

WIDTH = 3
HEIGHT = 2.4

plt.rcParams.update({
    "font.size": 9,
    "axes.titlesize": 9,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
})


def parse_json_to_pd_dataframe(json_dict: Dict[str, Any], repo_type: str) -> pd.DataFrame:
    """Flatten nested JSON into a DataFrame for downstream analysis."""
    rows = []
    for year_name, year_data in json_dict.items():
        for proceedings_name, proceedings_data in year_data.items():
            for paper_id, paper_info in proceedings_data.get('papers', {}).items():
                urls = paper_info.get(repo_type, {})
                if urls:
                    for url in urls:
                        rows.append({
                            'year': int(year_name),
                            'proceedings': proceedings_name,
                            'paper_id': paper_id,
                            'url': url
                        })
                else:
                    rows.append({
                        'year': int(year_name),
                        'proceedings': proceedings_name,
                        'paper_id': paper_id,
                        'url': None
                    })

    df = pd.DataFrame(rows)
    return df


def compute_overall_link_stats(df: pd.DataFrame, event_name: str) -> None:
    """Write overall counts of additional link types for one event collection."""
    with open(f"analysis/{event_name}/additional_link_statistics.txt", "w+") as f:
        f.write(str(df["link_type"].value_counts()))
        f.write("\n Unique links:")
        f.write(str(df.groupby("link_type")["url"].nunique()))
    f.close()

def compute_yearly_link_stats(df: pd.DataFrame, event_name: str) -> None:
    """Write per-year counts of unique additional links by link type."""
    grouped = df.groupby(["year", "link_type"])["url"].nunique()
    grouped.to_csv(f"analysis/{event_name}/additional_links_unique_year_link_type.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract urls from downloaded files."
    )
    parser.add_argument(
        "acl_event_id",
        help="the id of the acl event (e.g. acl, cl). There should be corresponding folder with pdfs."
    )

    parser.add_argument(
        "venue_name",
        help="the name of the conference or venue. Analysis and Plots are saved in this folder. e.g. CL, Association of Computational Linguistics"
    )
    args = parser.parse_args()
    repo_types = ["zenodo_urls", "huggingface_urls", "bitbucket_urls", "gitlab_urls", "other_urls"]
    os.makedirs(f"extracted_links/{args.acl_event_id}_other_links", exist_ok=True)
    os.makedirs(f"analysis/{args.venue_name}", exist_ok=True)
    os.makedirs(f"Plots/{args.venue_name}", exist_ok=True)
    all_acls = read_and_concatenate_json_files(f"extracted_links/{args.event_id}_other_links", sort_year=True)

    all_types = pd.DataFrame()
    for repo_type in repo_types:
        df = parse_json_to_pd_dataframe(all_acls, repo_type)
        df["link_type"] = repo_type
        all_types = pd.concat([all_types, df])

    all_types = all_types.dropna(subset="url")
    all_types.to_csv(f"extracted_links/{args.event_id}_other_links/additional_links_all_acls.csv")
    compute_overall_link_stats(all_types, args.venue_name) 

    compute_yearly_link_stats(all_types, args.venue_name)
    yearly_links = pd.read_csv(f"analysis/{args.venue_name}/additional_links_unique_year_link_type.csv")
    print("Head of all types", yearly_links.head())
    yearly_links_no_other = yearly_links[yearly_links["link_type"] != "other_urls"]
    yearly_links_no_other["link_type"].replace({"zenodo_urls": "Zenodo", "huggingface_urls": "Huggingface", 
                                                "bitbucket_urls":"Bitbucket", "gitlab_urls": "Gitlab"}, inplace=True)
    plot_line(yearly_links_no_other, x="year", y="url", out_path=f"Plots/{args.venue_name}/development_other_links.png",
            ylabel="Count per Link Type", legend=True, hue="link_type", width=3)
