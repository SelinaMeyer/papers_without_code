from github import Github, Auth
from github.GithubException import GithubException, UnknownObjectException
import os
import PyPDF2
import fitz
import re
from acl_anthology import Anthology
import requests
from urllib.parse import urlparse
import json
import argparse
import logging
import sys
import time
from dotenv import load_dotenv
from typing import Any, BinaryIO, Dict, List, Optional, Tuple, Union

logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')

# Persist a richer log than stdout in a local file for later debugging.
file_handler = logging.FileHandler('logs.log')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)


logger.addHandler(file_handler)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# ACL Anthology helper and authenticated GitHub client (token expected in env).
anthology = Anthology.from_repo()

auth = Auth.Token(os.getenv("GITHUB_TOKEN"))

g = Github(auth=auth)

def github_url_exists(url):
    r = requests.head(url, allow_redirects=True, timeout=10)
    return r.status_code < 400

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

    if num_files_in_repo in [1, "1"] and files_in_repo[0].path.lower() in ["readme.md", "license.md"]:
        num_files_in_repo = "1_readme_or_license_only"
    return num_files_in_repo, files_in_repo, readme, is_repo, link_exists

def get_and_save_publications(paper: Any, directory: str) -> Tuple[Optional[str], str]:
    """Download a paper PDF if needed and return its source URL and paper id."""
    paper_id = paper.full_id
    url: Optional[str] = None

    try:
        url = paper.pdf.url
        filename = os.path.join(directory, f"{paper_id}.pdf")

        if os.path.exists(filename):
            return url, paper_id

        max_retries = 5
        backoff = 2

        for attempt in range(max_retries):
            try:
                r = requests.get(
                    url,
                    stream=True,
                    timeout=(5, 60)
                )
                r.raise_for_status()

                with open(filename, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                print(f"Downloaded {filename}")
                time.sleep(1)
                break

            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    print(f"{paper_id}: download failed ({e})")
                    break

                sleep_time = backoff ** attempt
                print(f"{paper_id}: retry {attempt+1}/{max_retries} in {sleep_time}s")
                time.sleep(sleep_time)

    except AttributeError:
        print(f"{paper_id}: no PDF available")
        url = None

    return url, paper_id

def extract_all_urls(file: BinaryIO, paper_id: str) -> List[str]:
    """Extract all URLs from PDF annotations and page text for one paper.
    
    Code adapted from https://thepythoncode.com/article/extract-pdf-links-with-python
    """
    urls = []

    url_regex = r"https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=\n]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)"

    PDF = PyPDF2.PdfFileReader(file)
    pages = PDF.getNumPages()
    key = '/Annots'
    uri = '/URI'
    ank = '/A'

    for page in range(pages):
        print("Current Page: {}".format(page))
        pageSliced = PDF.getPage(page)
        pageObject = pageSliced.getObject()
        if key in pageObject.keys():
            ann = pageObject[key]
            for a in ann:
                u = a.getObject()
                try:
                    if uri in u[ank].keys():
                        if isinstance(u[ank][uri], bytes):
                            u[ank][uri] = u[ank][uri].decode("utf-8", errors="ignore")
                            print("[+] URL Found:", u[ank][uri])
                        urls.append(u[ank][uri])   
                except KeyError:
                    logging.info(f"{paper_id}: Link could not be parsed on page {page}.") 
                    logging.info("Object: {u}")    
                        
    with fitz.open(file) as pdf:
        text = ""
        for page in pdf:
            # extract text of each PDF page
            text += page.get_text()
    # extract all urls using the regular expression
    for match in re.finditer(url_regex, text):
        url = match.group()
        pos = match.end()

        while url.endswith("-") or url.endswith("_"):
            # look at the text immediately following the match
            remainder = text[pos:]

            # skip line breaks and surrounding whitespace
            remainder = remainder.lstrip("\r\n \t")

            # take the next token up to whitespace
            m = re.match(r'([^\s]+)', remainder)
            if not m:
                break

            next_part = m.group(1)
            url += next_part

            pos += remainder.find(next_part) + len(next_part)

            url = url.strip("'\".,);:! ")

        print("[+] URL Found:", url)
        urls.append(url)
    return urls


def extract_github_links(event_name: str, volume: str, paper_id: str) -> List[str]: 
    """Extract GitHub URLs from a paper PDF by scanning text and link annotations.

    Args:
        event_name: ACL event id used for file path resolution.
        volume: Volume title for the paper.
        paper_id: Full paper id (matches stored PDF filename).

    Returns:
        Cleaned, de-duplicated list of GitHub URLs found in the PDF.
    """
    
    file = open(f"files/{event_name}/{volume}/{paper_id}.pdf", "rb")
    extracted_links = []

    urls = extract_all_urls(file, paper_id)

    for url in urls:
        if "github.com" in url:
            extracted_links.append(url)
    
    print(extracted_links)
    github_urls = sorted(set(extracted_links), key=len) 
    clean = [u for i, u in enumerate(github_urls) if not any(u in v for v in github_urls[i+1:])] # drop broken duplicates from stitched canvas strings'''
    return clean

def get_and_parse_event(event_name: str) -> None:
    """Download event papers, pull GitHub links, and persist per-volume summaries.

    Creates/updates `extracted_links_per_volume_{event}.json` with paper URLs,
    discovered GitHub links, and shallow repo metadata.
    """
    unparseable_papers_list = ["2024.acl-long.843"] # raises segmentation fault (core dumped) when trying to extract links, likely due to malformed PDF structure. Skip for now.
    event = anthology.get_event(event_name)
    conference = event_name.split("-", 1)[0]
    output_dir = os.path.join("extracted_links", conference)
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"extracted_links_per_volume_{event_name}.json")
    try: 
        with open(filename, 'r') as f:
            volumes = json.load(f)
    except FileNotFoundError:
        volumes = {}

    if not os.path.exists(f"files/{str(event_name)}"):
        os.makedirs(f"files/{str(event_name)}")

    for volume in event.volumes():
        if str(volume.title) not in volumes:
            volumes[str(volume.title)] = {}
            volumes[str(volume.title)]["papers"] = {}
        dir = f"files/{str(event_name)}/{str(volume.title)}/"
        if not os.path.exists(dir):
            os.makedirs(dir)

        print("Downloaded papers in volume: ",len(os.listdir(dir)))
        print("Parsed papers in volume: ",len(volumes[str(volume.title)]["papers"]))
        print("Available papers in volume: ", len(list(volume.papers())))
        if len(volumes[str(volume.title)]["papers"]) < len(list(volume.papers())):
            for paper in volume.papers():
                if paper.full_id not in volumes[str(volume.title)]["papers"] and not paper.full_id in unparseable_papers_list:
                    print(paper.full_id)
                    url,id = get_and_save_publications(paper, dir)
                    volumes[str(volume.title)]["papers"][id] = {}
                    if url != None:
                        print("paper download complete")
                        try:
                            volumes[str(volume.title)]["papers"][id]["source_url"] = url
                            volumes[str(volume.title)]["papers"][id]["github_urls"] = {}
                            github_urls = extract_github_links(event_name, volume.title, id)
                            print("Links extracted")
                            for github_url in github_urls:
                                num_files_in_repo, files_in_repo, readme, is_repo, link_exists = get_github_data(github_url)
                                volumes[str(volume.title)]["papers"][id]["github_urls"][github_url] = {"number_of_files": num_files_in_repo,
                                                                                                        "files_names": str(files_in_repo),
                                                                                                        "Readme":  readme,
                                                                                                        "is_repo": is_repo,
                                                                                                        "link_exists": link_exists}
                        except Exception as e:
                            print(e)
                            volumes[str(volume.title)]["papers"][id]["source_url"] = "Paper not parseable"
                            volumes[str(volume.title)]["papers"][id]["github_urls"] = {}   
                        
                    else:
                        volumes[str(volume.title)]["papers"][id]["source_url"] = "Paper url not available"
                        volumes[str(volume.title)]["papers"][id]["github_urls"] = {}

                    with open(filename, 'w') as f:
                        json.dump(volumes, f)
        else: 
            print(f"Parsing for volume {volume.title} already finished")

        with open(filename, 'w') as f:
            json.dump(volumes, f)


def run_extraction(selection: str) -> None:
    """Run GitHub-link extraction for a single event or a built-in event batch."""
    arg_options = ["acl", "cl"]
    if selection not in arg_options:
        get_and_parse_event(selection)
    else:
        acl_list = [f"{selection}-{year}" for year in range(2015, 2026)]
        for event in acl_list:
            print("Parsing event ", event)
            get_and_parse_event(event)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Get all pdfs from an acl event, extract mentioned github repos and check them for files/availability."
    )
    parser.add_argument(
        "acl_event_name",
        help="the name of the acl event (e.g. acl-2018)."
    )

    args = parser.parse_args()
    run_extraction(args.acl_event_name)
