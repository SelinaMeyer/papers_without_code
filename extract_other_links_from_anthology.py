from extract_all_github_repos import *

from github import Github, Auth
from github.GithubException import GithubException, UnknownObjectException
import os
import PyPDF2
import re
from acl_anthology import Anthology
import requests
from urllib.parse import urlparse
import json
import argparse
import logging
import sys
import time
from typing import Any, Dict, List, Optional, Tuple, Union

def extract_relevant_links(event_name: str) -> None:
    """Extract non-GitHub artifact links from previously downloaded PDFs for one event."""
    output_dir = f"extracted_links/{args.acl_event_name}_other_links"
    os.makedirs(output_dir, exist_ok=True)  
    filename = f"extracted_links/{args.acl_event_name}_other_links/extracted_additional_links_per_volume_{event_name}.json"

    # Load existing data if present
    try:
        with open(filename, 'r') as f:
            volumes = json.load(f)
    except FileNotFoundError:
        volumes = {}

    base_path = f"files/{event_name}"

    checkpoint_interval = 50  # adjust as needed
    processed = 0

    def save_checkpoint(data: Dict[str, Any]) -> None:
        """Save partial extraction results for resumable runs."""
        tmp_filename = filename + ".tmp"
        with open(tmp_filename, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_filename, filename)

    for root, dirs, files in os.walk(base_path):
        print("ROOT:", root)

        dir_name = os.path.basename(root)

        if dir_name not in volumes:
            volumes[dir_name] = {"papers": {}}

        for file in files:
            print("FILE:", file)

            if file not in volumes[dir_name]["papers"]:
                volumes[dir_name]["papers"][file] = {
                    "zenodo_urls": [],
                    "huggingface_urls": [],
                    "bitbucket_urls": [],
                    "gitlab_urls":[],
                    "other_urls": []
                }

                file_path = os.path.join(root, file)

                try:
                    with open(file_path, "rb") as pdf:
                        urls = extract_all_urls(pdf, file)
                except Exception as e:
                    print(f"Error processing {file_path}: {e}")
                    continue
                sorted_urls = sorted(set(urls), key=len) 
                clean = [u for i, u in enumerate(sorted_urls) if not any(u in v for v in sorted_urls[i+1:])] # drop broken duplicates from stitched canvas strings
                for url in clean:
                    if "zenodo" in url:
                        volumes[dir_name]["papers"][file]["zenodo_urls"].append(url)
                    elif "huggingface.co" in url and not "github.com" in url:
                        volumes[dir_name]["papers"][file]["huggingface_urls"].append(url)
                    elif "bitbucket.org" in url:
                        volumes[dir_name]["papers"][file]["bitbucket_urls"].append(url)
                    elif "gitlab.com" in url:
                        volumes[dir_name]["papers"][file]["gitlab_urls"].append(url)
                    elif "github.com" not in url:
                        volumes[dir_name]["papers"][file]["other_urls"].append(url)

            processed += 1

            # Periodic checkpoint
            if processed % checkpoint_interval == 0:
                save_checkpoint(volumes)
                print(f"[checkpoint] saved after {processed} files")

    # Final save
    save_checkpoint(volumes)
    print(f"[done] processed {processed} files and saved results")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract urls from downloaded files."
    )
    parser.add_argument(
        "acl_event_name",
        help="the name of the acl event (e.g. acl-2018). There should be corresponding folder with pdfs."
    )

    args = parser.parse_args()
    arg_options = ["acl", "cl"]
    if args.acl_event_name not in arg_options:
        file_handler = logging.FileHandler(f'logs/other_link_extraction_logs_{args.acl_event_name}.log')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        extract_relevant_links(args.acl_event_name)
    elif args.acl_event_name in arg_options:
        acl_list = [f"{args.acl_event_name}-{year}" for year in range(2015, 2026)]
        for event in acl_list:
            print("Parsing event ", event)
            file_handler = logging.FileHandler(f'logs/other_link_extraction_logs_{event}.log')
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            extract_relevant_links(event)
