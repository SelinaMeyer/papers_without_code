# Code based on https://huggingface.co/spaces/CONDA-Workshop/Data-Contamination-Database/blob/main/utils.py

import logging
import re
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Union
from huggingface_hub.errors import HFValidationError, RepositoryNotFoundError
from urllib.parse import urljoin, urlparse
import time
import requests
from dotenv import load_dotenv
import pandas as pd
from check_zenodo_links import url_exists
from typing import Any, Tuple
import argparse


from huggingface_hub import HfApi

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

os.makedirs("extracted_links/acl_other_links", exist_ok=True)

HF_API = HfApi(token=os.getenv("HUGGINGFACE_TOKEN"))


def get_base_url(url: str) -> Tuple[str, str]:
    """Split a URL into its base host and stripped path components."""
    parsed_url = urlparse(url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    return base_url, parsed_url.path.strip("/")

MAX_RETRIES = 5
BASE_SLEEP = 2  

def safe_url_exists(url: str) -> Dict[str, Any]:
    """Wrapper with retries, backoff, and error handling."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = url_exists(url)

            # handle rate limiting
            if resp.get("exists") == 429:
                sleep_time = BASE_SLEEP * (2 ** attempt)
                print(f"429 received, retrying in {sleep_time}s...")
                time.sleep(sleep_time)
                continue
            print(resp)
            return resp

        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as e:
            sleep_time = BASE_SLEEP * (2 ** attempt)
            print(f"Request failed ({e}), retrying in {sleep_time}s...")
            time.sleep(sleep_time)

        except Exception as e:
            print(f"Unexpected error: {e}")
            break

    # fallback if all retries fail
    return {"exists": None, "files": []}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract urls from downloaded files."
    )
    parser.add_argument(
        "acl_event_id",
        help="the id of the acl event (e.g. acl, cl). There should be corresponding folder with pdfs."
    )
    args = parser.parse_args()

    PARTIAL_PATH = f"extracted_links/{args.acl_event_id}_other_links/huggingface_links_partial.csv"
    FINAL_PATH = f"extracted_links/{args.acl_event_id}_other_links/huggingface_links_no_duplicates.csv"
    UNAVAILABLE_PATH = f"extracted_links/{args.acl_event_id}_other_links/unavailable_huggingface_links_no_duplicates.csv"
    PARTIAL_UNAV_PATH = f"extracted_links/{args.acl_event_id}_other_links/unavailable_huggingface_links_no_duplicates_partial.csv"

    SAVE_EVERY = 1

    if os.path.exists(PARTIAL_PATH):
        print("Resuming from partial file...")
        huggingface_df = pd.read_csv(PARTIAL_PATH)
    else:
        print("Starting fresh...")
        df = pd.read_csv(f"extracted_links/{args.acl_event_id}_other_links/additional_links_all_acls.csv")
        huggingface_df = df[df["link_type"] == "huggingface_urls"].copy()

        huggingface_df = huggingface_df.drop_duplicates(subset="url", keep="first").reset_index(drop=True)

        huggingface_df["link exists"] = None
        huggingface_df["repo_exists"] = None
        huggingface_df["repo_type"] = None
        huggingface_df["num_files"] = None
        huggingface_df["files"] = None


    start_idx = huggingface_df[huggingface_df["repo_exists"].isna()].index.min()

    if pd.isna(start_idx):
        print("All rows already processed.")
        start_idx = len(huggingface_df)
        only_non_existent = huggingface_df[huggingface_df["repo_exists"]==False]
        print(f"{len(only_non_existent)} Repositories unavailable")
        only_non_existent.to_csv(UNAVAILABLE_PATH)

    print(f"Starting from index: {start_idx}")


    if not os.path.exists(FINAL_PATH):
        for i in range(start_idx, len(huggingface_df)):
            row = huggingface_df.iloc[i]
            full_url = row["url"]
            url_base, path = get_base_url(full_url)
            print(path)
            if "spaces/" in full_url:
                path = path.removeprefix("spaces/").strip("/")
                repo_type = "space"
            elif "datasets/" in full_url:
                path = path.removeprefix("datasets/").strip("/")
                repo_type = "dataset"
            else:
                repo_type = "model"
            if len(path) > 1:
                if url_base == "https://huggingface.co":
                    try:
                        split_path = re.match(r'[^/]+(?:/[^/]+)?', path).group(0)
                        try:
                            repo_info = HF_API.list_repo_files(split_path, repo_type=repo_type)
                            print(repo_info)
                            exists = True
                        except RepositoryNotFoundError as e:
                            print(e)
                            exists = False
                        huggingface_df.at[i, "repo_exists"] = exists
                        huggingface_df.at[i, "repo_type"] = repo_type
                        if exists:
                            huggingface_df.at[i, "num_files"] = len(repo_info)
                            huggingface_df.at[i, "files"] =",".join(repo_info)
                    except HFValidationError:
                        huggingface_df.at[i, "repo_exists"] = "not namespace/repo_name format"
                        huggingface_df.at[i, "repo_type"] = "other"
                else:
                    huggingface_df.at[i, "repo_exists"] = "base url not huggingface.co"
                    huggingface_df.at[i, "repo_type"] = "none"
            else:
                huggingface_df.at[i, "repo_exists"] = "Only base url"
                huggingface_df.at[i, "repo_type"] = "none"

            
            if i % SAVE_EVERY == 0 and i > start_idx:
                print(f"Saving progress at row {i}")
                huggingface_df.to_csv(PARTIAL_PATH, index=False)

        
        huggingface_df.to_csv(FINAL_PATH, index=False)
        only_non_existent = huggingface_df[huggingface_df["repo_exists"].isin([False, "False"])]
        print(f"{len(only_non_existent)} Repositories unavailable")
        only_non_existent.to_csv(UNAVAILABLE_PATH)
        print("Processing complete.")

    if os.path.exists(PARTIAL_UNAV_PATH):
        print("Checking full links with request")
        unavailable_df = pd.read_csv(PARTIAL_UNAV_PATH)
        start_idx = unavailable_df[unavailable_df["requests_response"].isna()].index.min()
        print(start_idx)
        start_idx = unavailable_df[unavailable_df["requests_response"].isna()].index.min()

        if pd.isna(start_idx):
            print("All rows already processed.")
            start_idx = len(unavailable_df)

        print(f"Sarting from index: {start_idx}")
        for i in range(start_idx, len(unavailable_df)):
            row = unavailable_df.iloc[i]
            resp = safe_url_exists(row["url"])
            unavailable_df.at[i, "requests_response"] = resp.get("exists")
            unavailable_df.at[i, "files"] = ",".join(resp.get("files", []))
            unavailable_df.at[i, "num_files"] = len(resp.get("files"))

            time.sleep(1)

            if i % SAVE_EVERY == 0 and i > start_idx:
                print(f"Saving progress at row {i}")
                unavailable_df.to_csv(PARTIAL_UNAV_PATH, index=False)
        unavailable_df.to_csv(PARTIAL_UNAV_PATH, index=False)
        
        for index, row in unavailable_df.iterrows():
            print(f"Checking for 429s and False at index {index}")
            if row["requests_response"] in ([429, "429", False, "False"]):
                print("Starting new request")
                resp = safe_url_exists(row["url"].strip(")"))
                unavailable_df.at[index, "requests_response"] = resp.get("exists")
                unavailable_df.at[index, "files"] = ",".join(resp.get("files", []))
                unavailable_df.at[index, "num_files"] = len(resp.get("files"))
                print(unavailable_df.at[index, "requests_response"])
                unavailable_df.to_csv(PARTIAL_UNAV_PATH, index=False)
                time.sleep(1)
        unavailable_df.to_csv(UNAVAILABLE_PATH, index=False)
