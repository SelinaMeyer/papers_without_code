import time

from github import Github, Auth
from github.GithubException import GithubException, UnknownObjectException
import re
from typing import Any, BinaryIO, Dict, List, Optional, Tuple, Union
import os
import pandas as pd
import requests
from extract_all_github_repos import extract_github_links, extract_all_urls, get_and_save_publications
import argparse
import requests

def github_url_exists(url):
    r = requests.head(url, allow_redirects=True, timeout=10)
    return r.status_code < 400

auth = Auth.Token(os.getenv("GITHUB_TOKEN"))
g = Github(auth=auth)

def get_github_data(link: Union[str, bytes, bytearray]) -> Tuple[int, str, str]:
    """Normalize a GitHub link and fetch shallow repo info via the GitHub API.

    Args:
        link: Full GitHub URL (or bytes) pointing to a repository.

    Returns:
        Tuple of (count of top-level entries or error flag, list/flag of entries, README text or fallback).
    """
    if isinstance(link, (bytes, bytearray)):
        link = link.decode("utf-8", errors="ignore")
    print(link)
    parts = re.split(r'https?://', link, maxsplit=1)
    if len(parts) > 1:
        git_link = parts[1]
    else:
        git_link = parts[0]
    is_repo = True
    try: 
        print(git_link)
        if any(s in git_link for s in [
                "github.com/features/",
                "gist.github.com",
                "github.com/features",
                "github.io",
                "github.com/advisories",
                "features/copilot"
            ]) or git_link in ["www.github.com","github.com"]:
                num_files_in_repo = "github_features_or_gist"
                files_in_repo = "github_features_or_gist"
                is_repo = False
                link_exists = github_url_exists("https://" + git_link.strip("/.,);:!\"'<>")) # adapt when adding to real code
                readme = "not available"
        else:
            repo = git_link.split("github.com/")
            repo = repo[1]
            print(repo)
            repo = re.sub(r"\.git$", "", repo)
            repo = repo.strip("/")
            repo = repo.strip("/.,);:!\"'<>")
            repo = repo.strip()
            print("CHECKING REPO:", repo)
            parts = repo.split("/")
            if len(parts) != 2:
                is_repo = False
                print("CHECKING URL: https://", git_link.strip("/.,);:!\"'<>"))
                link_exists = github_url_exists("https://" + git_link.strip("/.,);:!\"'<>")) # adapt when adding to real code
                num_files_in_repo = "not_a_repo"
                files_in_repo = "not_a_repo"
                if not link_exists:
                    try:
                        github_repo = g.get_repo(parts[:2])
                        contents = github_repo.get_contents("")
                        num_files_in_repo = len(contents)
                        files_in_repo = contents
                        print("Files in repo: ", files_in_repo)

                    except Exception as e:
                        if "This repository is empty" in str(e):
                            num_files_in_repo = "empty"
                            files_in_repo = "repo empty"
                            link_exists = True
                            print("Repo is empty")
                        else:
                            num_files_in_repo = "404"
                            files_in_repo = "repo unavailable"
                            link_exists = False
                            print(e)

            else:
                try:
                    github_repo = g.get_repo(repo)
                    contents = github_repo.get_contents("")
                    num_files_in_repo = len(contents)
                    files_in_repo = contents
                    link_exists = True
                    print("Files in repo: ", files_in_repo)

                except Exception as e:
                    if "This repository is empty" in str(e):
                        num_files_in_repo = 0
                        files_in_repo = "repo empty"
                        link_exists = True
                        print("Repo is empty")
                    else:
                        num_files_in_repo = "404"
                        files_in_repo = "repo unavailable"
                        link_exists = False

            if not num_files_in_repo in ["404", 0, "not_a_repo"]:
                try: 
                    readme = g.get_repo(repo).get_readme().decoded_content.decode("utf-8")
                except:
                    readme = "not available"
            else: 
                readme = "not available"

    except Exception as e:
        if "This repository is empty" in str(e):
            num_files_in_repo = 0
            files_in_repo = "repo empty"
            link_exists = True
            readme = "not available"
            print("Repo is empty")
        else:
            num_files_in_repo = "404"
            files_in_repo = "None available"
            readme = "not available"
            link_exists = False
            print(e)
    print("Number of files in repo: ", num_files_in_repo)

    return num_files_in_repo, files_in_repo, readme, is_repo, link_exists



def row_is_already_checked(row: pd.Series) -> bool:
    #checked_fields = ["num_files_in_repo_new", "files_in_repo_new", "readme_new", "is_repo"]
    checked_fields = ["checked"]
    for field in checked_fields:
        if field not in row:
            return False
        value = row[field]
        if pd.isna(value):
            return False
        if isinstance(value, str) and not value.strip():
            return False
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Get all pdfs from an acl event, extract mentioned github repos and check them for files/availability."
    )
    parser.add_argument(
        "acl_event_name",
        help="the name of the venue (e.g. acl, coling)."
    )
    parser.add_argument(
        "--filename",
        required=False
    )

    args = parser.parse_args()
    event_name = args.acl_event_name

    if args.filename is None:
        original_file = f"extracted_links/{event_name}/deduplicated_papers_with_empty_404_placeholder_repo_{event_name}.csv"
        updated_file = f"extracted_links/{event_name}/deduplicated_papers_with_empty_404_placeholder_repo_{event_name}_updated.csv"
    else:
        original_file = f"extracted_links/{event_name}/{args.filename}.csv"
        updated_file = f"extracted_links/{event_name}/{args.filename}_updated_test_check_link_endings.csv"

    if os.path.exists(updated_file):
        data = pd.read_csv(updated_file)
        print(f"Loaded existing updated CSV: {updated_file}")
    else:
        data = pd.read_csv(original_file)
        print(f"Loaded original CSV: {original_file}")

    for index, row in data.iterrows():
        print("Checking row ", index)
        if row_is_already_checked(row):
            print(f"Skipping index {index}: already checked")
            continue

        filepath = f"files/{row['year']}/{row['proceedings']}/{row['paper_id']}.pdf"
        if not os.path.exists(filepath):
            print("loading file")
            r = requests.get(
                    row["source_url"],
                    stream=True,
                    timeout=(5, 60)
                )
            r.raise_for_status()

            with open(filepath, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            print(f"Downloaded {filepath}")
            time.sleep(1)

        links = extract_github_links(row["year"], row["proceedings"], row["paper_id"])
        link_in_data = row["repo_url"]
        for link in links:
            if link.lower() in link_in_data.lower() or link_in_data.lower() in link.lower():
                data.at[index, "repo_url"] = link
                print(f"Updated link in data {link_in_data} to: {link}")
                link_to_use = link
                break
        else:
            link_to_use = link_in_data

        print(f"Processing index {index} with link: {link_to_use}")
        num_files, files, readme, is_repo, link_exists = get_github_data(link_to_use)
        data.at[index, "link_new"] = link
        data.at[index, "num_files_in_repo_new"] = num_files
        data.at[index, "files_in_repo_new"] = files
        data.at[index, "readme_new"] = readme
        data.at[index, "is_repo"] = is_repo
        data.at[index, "link_exists"] = link_exists
        data.at[index, "checked"] = True
        if num_files in [1, "1"] and files[0].path.lower() in ["readme.md", "license.md"]:
            data.at[index, "files_in_repo_new"] = "1_readme_or_license_only"
        data.to_csv(updated_file, index=False)

    data.to_csv(updated_file, index=False)
