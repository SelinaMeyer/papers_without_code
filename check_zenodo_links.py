import pandas as pd 
import logging
import re
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Union
from urllib.parse import urljoin, urlparse
import time 
import argparse

import requests
from typing import Any, Dict

def zenodo_url_to_id(url: str) -> str:
    """Extract the trailing Zenodo record identifier component from a URL."""
    return urlparse(url).path.split("/")[-1]

def zenodo_id_from_string(s: str) -> str:
    """Normalize a Zenodo identifier string such as `zenodo.5371628` to the numeric id."""
    return s.split(".")[-1] 

def url_exists(url: str) -> Dict[str, Any]:
    """Check whether a URL resolves successfully and return a small status payload."""
    try:
        response = requests.get(url, allow_redirects=True)
        print(response.status_code)

        if response.status_code not in [200, "200"]:
            return {
                "exists": response.status_code,
                "files": []
            }

        print("DEBUG:", response.status_code)

        return {
            "exists": response.status_code,
            "files": []
        }
    
    except requests.RequestException:
        return {"exists": False, "files": []}
    
def main() -> None:
    """Validate extracted ACL Zenodo links and write CSV outputs."""
    os.makedirs(f"extracted_links/{args.acl_event_id}_other_links", exist_ok=True)
    
    PARTIAL_PATH = f"extracted_links/{args.acl_event_id}_other_links/zenodo_links_partial.csv"
    FINAL_PATH = f"extracted_links/{args.acl_event_id}_other_links/zenodo_links_no_duplicates.csv"

    SAVE_EVERY = 50

    if os.path.exists(PARTIAL_PATH):
        print("Resuming from partial file...")
        zenodo_df = pd.read_csv(PARTIAL_PATH)
    else:
        print("Starting fresh...")
        df = pd.read_csv(f"extracted_links/{args.acl_event_id}_other_links/additional_links_all_acls.csv")
        zenodo_df = df[df["link_type"] == "zenodo_urls"].copy()

        zenodo_df = zenodo_df.drop_duplicates(subset="url", keep="first").reset_index(drop=True)

        zenodo_df["link exists"] = None
        zenodo_df["files"] = None
        zenodo_df["num_files"] = None

    start_idx = zenodo_df[zenodo_df["link exists"].isna()].index.min()

    if pd.isna(start_idx):
        print("All rows already processed.")
        start_idx = len(zenodo_df)

    print(f"Starting from index: {start_idx}")

    for i in range(start_idx, len(zenodo_df)):
        row = zenodo_df.iloc[i]
        full_url = row["url"]

        zenodo_id = zenodo_url_to_id(full_url)
        id = zenodo_id_from_string(zenodo_id)
        print(id)
        url = f"https://zenodo.org/api/records/{id}"

        response = url_exists(url)
        print(response)
        zenodo_df.at[i, "link_exists"] = response.get("exists")
        zenodo_df.at[i, "files"] = response.get("files")
        zenodo_df.at[i, "num_files"] = len(response.get("files"))

        time.sleep(1)

        if i % SAVE_EVERY == 0 and i > start_idx:
            print(f"Saving progress at row {i}")
            zenodo_df.to_csv(PARTIAL_PATH, index=False)

    zenodo_df.to_csv(FINAL_PATH, index=False)
    print("Processing complete.")

if __name__=="__main__":

    parser = argparse.ArgumentParser(
        description="Extract urls from downloaded files."
    )
    parser.add_argument(
        "acl_event_id",
        help="the id of the acl event (e.g. acl, cl). There should be corresponding folder with pdfs."
    )

    args = parser.parse_args()
    main()
