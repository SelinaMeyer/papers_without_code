import json
import pandas as pd
import numpy as np
import os
import re
import json
import matplotlib.pyplot as plt
import seaborn as sns
from extract_all_github_repos import get_github_data
import argparse
from typing import Any, Dict, List, Optional

def read_and_concatenate_json_files(directory: str, sort_year: bool = False) -> Dict[str, Dict[str, Any]]:
    """Load all JSON files in a directory and organize them by year and venue."""
    all_years_dict: Dict[str, Dict[str, Any]] = {}

    year_pattern = r"-([0-9]{4})"
    venue_pattern = r"_volume_([^-]+)-"

    for file in os.listdir(directory):
        year_match = re.search(year_pattern, file)
        print(year_match)
        venue_match = re.search(venue_pattern, file)
        print(venue_match)

        if not year_match or not venue_match:
            continue

        year = year_match.group(1)
        venue = venue_match.group(1)

        path = os.path.join(directory, file)

        with open(path) as f:
            data = json.load(f)

        if not sort_year:
            all_years_dict[f"{venue}-{year}"] = data
        else:
            all_years_dict[year] = data

    return all_years_dict

def merge_llm_extractions(all_years_dict: Dict[str, Any], llm_file: str) -> Dict[str, Any]:
    """Merge LLM-extracted GitHub links into the main per-year results structure."""
    with open(llm_file) as f:
        llm_extractions = json.load(f)
    for year, proceedings in llm_extractions.items():
        '''year_dict = all_years_dict.setdefault(year, {})'''

        for proceedings_title, proceedings_data in proceedings.items():
            if not isinstance(proceedings_data, dict):
                continue

            proc_dict = all_years_dict.setdefault(proceedings_title, {})
            papers_dict = proc_dict.setdefault("papers", {})

            new_papers = proceedings_data.get("papers", {})

            for paper_id, paper_info in new_papers.items():
                if not isinstance(new_papers, dict):
                    continue

                github_urls = paper_info.get("github_urls", {})
                
                for link_url, link_info in github_urls.items():

                    if not isinstance(link_info, dict):
                        continue

                    if link_info.get("number_of_files") == 0:
                        num_files_in_repo, files_in_repo, readme = get_github_data(link_url)

                        link_info["number_of_files"] = num_files_in_repo
                        link_info["files_names"] = files_in_repo
                        link_info["readme"] = readme

                papers_dict[paper_id] = paper_info
    return all_years_dict
    

def parse_json_to_pd_dataframe(json_dict: Dict[str, Any], filename: str) -> pd.DataFrame:
    """Flatten nested JSON into a DataFrame and persist as CSV for downstream analysis."""
    rows = []
    for year_name, year_data in json_dict.items():
        for proceedings_name, proceedings_data in year_data.items():
            for paper_id, paper_info in proceedings_data.get('papers', {}).items():
                source_url = paper_info.get('source_url')
                github_urls = paper_info.get('github_urls', {})
                if github_urls:
                    for repo_url, repo_data in github_urls.items():
                        rows.append({
                            'year': str(year_name),
                            'proceedings': proceedings_name,
                            'paper_id': paper_id,
                            'source_url': source_url,
                            'repo_url': repo_url,
                            'number_of_files': repo_data.get('number_of_files'),
                            'readme': repo_data.get("Readme"),
                            'is_repo': repo_data.get("is_repo", {})
                        })
                else:
                    rows.append({
                        'year': str(year_name),
                        'proceedings': proceedings_name,
                        'paper_id': paper_id,
                        'source_url': source_url,
                        'repo_url': None,
                        'number_of_files': None,
                        'readme': None
                    })

    df = pd.DataFrame(rows)
    df.to_csv(f"{filename}.csv")
    return df

def deduplicate_error_logs(logfilename: str, conference: str) -> None:
    """Deduplicate log lines and collect paper ids with parsing errors."""
    output_dir = os.path.join("extracted_links", conference)
    os.makedirs(output_dir, exist_ok=True)
    deduplicated_log = []
    problematic_papers = []
    with open(logfilename, "r") as logfile:
        for line in logfile:
            split_line = line.split("|")
            if split_line[2] not in deduplicated_log:
                deduplicated_log.append(split_line[2])
                paper_id = split_line[2].split(":")[0].strip(" ")
                if paper_id not in problematic_papers and all(x not in paper_id for x in ["Github", "Request", "Fetching", "Setting", "Object"]):
                    problematic_papers.append(paper_id)
        logfile.close()
    with open(os.path.join(output_dir, f"deduplicated_logs_{conference}.log"), "w+") as f:
        f.writelines(deduplicated_log)
        f.close()
    with open(os.path.join(output_dir, f"paper_ids_with_parsing_errors_{conference}.log"), "w+") as f:
        f.write(f"Number of papers with parsing errors: {len(problematic_papers)} \n")
        f.writelines(f"{problematic_papers}\n")
        f.close()
    with open(os.path.join(output_dir, f"paper_ids_with_parsing_errors_clean_{conference}.log"), "w+") as f:
        for paper_id in problematic_papers:
            f.write(f"{paper_id}\n")
        f.close()


def merge_conference(conference: str) -> None:
    """Merge extracted JSON files for one conference into CSV analysis files."""
    output_dir = os.path.join("extracted_links", conference)
    os.makedirs(output_dir, exist_ok=True)
    conference_json = read_and_concatenate_json_files(output_dir)
    parse_json_to_pd_dataframe(conference_json, os.path.join(output_dir, f"regex_extracted_github_links_all_{conference}"))
    llm_path = os.path.join(output_dir, f"llm_extracted_links_{conference}.json")
    if not os.path.exists(llm_path):
        conferece_df_merged = parse_json_to_pd_dataframe(conference_json, os.path.join(output_dir, f"extracted_github_links_all_{conference}"))
        papers_with_empty_unreachable_repo = conferece_df_merged[conferece_df_merged['number_of_files'].isin(["0", "404", "1", 0, 1])]
        papers_with_empty_unreachable_repo.to_csv(os.path.join(output_dir, f"papers_with_empty_404_placeholder_repo_merged_{conference}.csv"))
        papers_with_empty_unreachable_repo.drop_duplicates(subset="repo_url").to_csv(os.path.join(output_dir, f"deduplicated_papers_with_empty_404_placeholder_repo_{conference}.csv"))
    else:
        conference_json_merged = merge_llm_extractions(conference_json, llm_path)
        conferece_df_merged = parse_json_to_pd_dataframe(conference_json_merged, os.path.join(output_dir, f"extracted_github_links_all_{conference}_merged_llm_extractions"))
        papers_with_empty_unreachable_repo = conferece_df_merged[conferece_df_merged['number_of_files'].isin(["0", "404", "1", 0, 1])]
        papers_with_empty_unreachable_repo.to_csv(os.path.join(output_dir, f"papers_with_empty_404_placeholder_repo_merged_with_llm_extractions_{conference}.csv"))
        papers_with_empty_unreachable_repo.drop_duplicates(subset="repo_url").to_csv(os.path.join(output_dir, f"deduplicated_papers_with_empty_404_placeholder_repo_merged_with_llm_extractions_{conference}.csv"))
    log_path = os.path.join(output_dir, f"logs_{conference}.log")
    if os.path.exists(log_path):
        deduplicate_error_logs(log_path, conference)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="merge individual results and llm extractions")
    
    parser.add_argument(
        "conferences",
        help="which conferences should be examined?",
    )

    args = parser.parse_args()
    print(args)


    merge_conference(args.conferences)
