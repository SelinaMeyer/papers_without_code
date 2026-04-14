import json
import pandas as pd
import numpy as np
import os
import re
import matplotlib.pyplot as plt
import seaborn as sns
from acl_anthology import Anthology
from github import Github, Auth
import fitz
from transformers import pipeline, AutoModelForCausalLM, AutoTokenizer
import torch
import logging
import ast
import argparse
import requests
import time
from typing import Any, Dict, List, Union
from extract_all_github_repos import get_github_data, get_and_save_publications
script_dir = os.path.abspath(os.path.dirname(__file__))
cache_dir = os.path.join(script_dir, '.cache')


logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')

file_handler = logging.FileHandler('logs_llm_parser.log')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

torch.cuda.empty_cache()
os.environ['HF_HOME'] = cache_dir
os.environ['TRANSFORMERS_CACHE'] = os.path.join(cache_dir, 'transformers')
os.environ['HF_DATASETS_CACHE'] = os.path.join(cache_dir, 'datasets')
os.environ['HF_HUB_CACHE'] = os.path.join(cache_dir, 'hub')
os.environ["TOKENIZERS_PARALLELISM"] = "false"

model_name="openai/gpt-oss-20b"
anthology = Anthology.from_repo()

def get_conference_path(conference: str, filename: str) -> str:
    """Return a standardized conference path under `extracted_links/<conference>/`."""
    output_dir = os.path.join("extracted_links", conference)
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, filename)


def extract_github_links_with_llm(text: str, pipe: Any, num_retries: int = 0) -> List[Dict[str, Union[str, bool]]]:
    """Use an LLM to extract GitHub URLs from text and classify them.

    Args:
        text: Page snippet or full page content to scan.
        pipe: HuggingFace text-generation pipeline configured for chat models.
        num_retries: Recursive retry counter to recover from bad JSON outputs.

    Returns:
        List of dictionaries: {"url": url, "is_repo": bool}. Falls back to a
        single failure entry when extraction repeatedly fails.
    """

    messages = [
        {"role": "user", "content": f"""Extract all github links from the following text, delimited by triple backticks:
        ```{text}```
        Extract only github urls. For each github url, decide whether it is a repo, or a different type of github link, such as a github space or a specific github issue.
        Return your results as a list of dictionaries with the following format: [{{"url": "the extracted url",
                                                                        "is_repo": "True or False"}}]
        Do not return any other text. If no links are found, return an empty list.
        /no_think
        """}
    ]

    links = pipe(
        messages, 
        temperature=0.01,
        use_cache=True,
        return_full_text=False,
        max_new_tokens=1024
    )
    print(links[0]["generated_text"])
    only_links = re.search(r'assistantfinal\s*(\[\s*(?:\{.*?\}\s*)?\])', links[0]["generated_text"])
    if only_links:
        print(only_links)
        only_links = only_links.group(1)
        if isinstance(only_links, str):
            try:
                only_links = json.loads(only_links)
            except json.JSONDecodeError:
                if num_retries < 3:
                    return extract_github_links_with_llm(text, pipe, num_retries+1)
                only_links= [{"url": "llm extraction failed",
                            "is_repo": False}]
    else:
        if num_retries < 3:
            only_links = extract_github_links_with_llm(text, pipe, num_retries+1)
        else:
            only_links= [{"url": "llm extraction failed",
                        "is_repo": False}]
    print("LLM response: ", only_links) 
    return only_links


def get_github_links_from_papers_with_parsing_errors(ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Download PDFs for problematic papers and re-extract GitHub links via LLM.

    Args:
        ids: Paper ids that failed previous parsing attempts.

    Returns:
        Nested dictionary indexed by year -> volume -> paper id containing
        source URLs, parsed page counts, and GitHub metadata.
    """
    pipe: Any = pipeline(
        'text-generation',
        model=model_name,
        dtype=torch.bfloat16,
        device_map="cuda"
    )

    llm_output_path = get_conference_path(args.conferences, f"llm_extracted_links_{args.conferences}.json")

    try: 
        with open(llm_output_path, 'r') as f:
            results_dict  = json.load(f)
            print("reading in dict")
    except FileNotFoundError:
        results_dict = {}
        print("creating new dict")
    for id in ids:
        print("checking paper with id: ", id)
        id = id.strip()
        paper = anthology.get_paper(id)
        print(paper)
        volume = anthology.get_volume(id)
        print(volume)
        year = volume.year
        print(year)
        event = f"acl-{year}"
        year_key = str(year)
        if year_key not in results_dict:
            results_dict[year_key] = {}
            print("creating new year index")
        if str(volume.title) not in results_dict[year_key]:
            results_dict[year_key][str(volume.title)] = {}
            print("creating new volume index")
        if "papers" not in results_dict[year_key][str(volume.title)]:
            results_dict[year_key][str(volume.title)]["papers"] = {}
        if id not in results_dict[year_key][str(volume.title)]["papers"]:
            results_dict[year_key][str(volume.title)]["papers"][id] =  {"source_url": paper.pdf.url,
                                                                    "parsed_pages": 0, 
                                                                    "github_urls": {}}
            print("creating new paper index")

        path_to_paper = f"files/{event}/{str(volume.title)}/{id}.pdf"
        if not os.path.exists(path_to_paper):
            download_success = False
            for attempt in range(3):
                try:
                    r = requests.get(paper.pdf.url, stream=True, timeout=30)
                    r.raise_for_status()
                    os.makedirs(os.path.dirname(path_to_paper), exist_ok=True)
                    with open(path_to_paper, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                    print(f"Downloaded {id}")
                    download_success = True
                    break
                except requests.RequestException as exc:
                    logging.warning(f"Download failed for {id} (attempt {attempt+1}/3): {exc}")
                    time.sleep(2)
            if not download_success:
                logging.error(f"Giving up on downloading {id}; skipping paper")
                continue
        with fitz.open(path_to_paper) as pdf:
            print("pdf file exists")
            current_page = 0
            print(pdf.page_count)
            print(results_dict[year_key][str(volume.title)]["papers"][id]["parsed_pages"])
            if int(results_dict[year_key][str(volume.title)]["papers"][id]["parsed_pages"]) < int(pdf.page_count):
                print("parsing pages")
                for page in pdf:
                    current_page += 1
                    if results_dict[year_key][str(volume.title)]["papers"][id]["parsed_pages"] < current_page:
                        print("passing pages to LLM")
                        # Extract text of each PDF page; skip pages that raise fitz errors.
                        try: 
                            page_text = page.get_text()
                        except Exception:
                            logging.info(f"{id}: page {page} not parseable")
                            continue
                        if "github" in page_text.lower():
                            print("Page seems to contain a github reference")
                            # Send only short snippets around each mention to keep prompts compact.
                            snippet_ranges = []
                            for match in re.finditer(r"github", page_text, flags=re.IGNORECASE):
                                start = max(match.start() - 400, 0)
                                end = min(match.end() + 400, len(page_text))
                                if snippet_ranges and start <= snippet_ranges[-1][1]:
                                    snippet_ranges[-1] = (snippet_ranges[-1][0], max(snippet_ranges[-1][1], end))
                                else:
                                    snippet_ranges.append((start, end))

                            snippets = [page_text[start:end] for start, end in snippet_ranges] or [page_text]  # ensure at least one chunk

                            for snippet in snippets:
                                links = extract_github_links_with_llm(snippet, pipe)
                                if links:
                                    print(len(links))
                                    for link in links:
                                        if not isinstance(link, dict) or "url" not in link or "is_repo" not in link:
                                            logging.warning(f"Skipping malformed link entry: {link}")
                                            continue
                                        print(link["url"])
                                        if link["url"] != "llm extraction failed":
                                            try:
                                                num_files, filenames, readme = get_github_data(link["url"])
                                            except Exception as exc:
                                                logging.warning(f"Failed to fetch repo metadata for {link['url']}: {exc}")
                                                num_files, filenames, readme = 0, "error", f"fetch_failed: {exc}"
                                        else:
                                            num_files, filenames, readme = 0, "none", str(page)
                                        results_dict[year_key][str(volume.title)]["papers"][id]["github_urls"][link["url"]] = {"number_of_files": num_files,
                                                        "files_names":str(filenames),
                                                        "Readme": readme,
                                                        "is_repo": link["is_repo"],
                                                        "found_on_page": current_page}
                        
                        results_dict[year_key][str(volume.title)]["papers"][id]["parsed_pages"] += 1
                    with open(llm_output_path, "w") as f:
                        json.dump(results_dict, f)

        with open(llm_output_path, "w") as f:
            json.dump(results_dict, f)
    
    return results_dict

def create_id_file() -> List[str]:
    """Combine locally logged parsing errors with empty repo records and persist ids."""
    clean_error_ids_path = get_conference_path(args.conferences, f"paper_ids_with_parsing_errors_clean_{args.conferences}.log")
    empty_repo_path = get_conference_path(args.conferences, f"deduplicated_papers_with_empty_404_placeholder_repo_{args.conferences}.csv")
    papers_to_parse_path = get_conference_path(args.conferences, f"papers_to_parse_with_llm_{args.conferences}.txt")

    ids = [] 
    if os.path.exists(clean_error_ids_path):
        with open(clean_error_ids_path, "r") as f:
            raw_content = f.read().strip()
        if raw_content:
            if raw_content.startswith("["):
                ids.append(ast.literal_eval(raw_content))
            else:
                ids.append([
                    line.strip()
                    for line in raw_content.splitlines()
                    if line.strip() and not line.startswith("Number of papers with parsing errors:")
                ])

    empty_repos = pd.read_csv(empty_repo_path)
    for index, row in empty_repos.iterrows():
        paper_id = row["paper_id"]
        if paper_id not in ids:
            ids.append(paper_id)

    print(len(ids))
    with open(papers_to_parse_path, "w+") as f:
        for id in ids:
            f.writelines(f"{id} \n")
    return ids


def prepare_llm_inputs(conference: str) -> List[str]:
    """Build and save the conference-specific list of paper ids for LLM re-parsing."""
    global args
    args = argparse.Namespace(conferences=conference)
    return create_id_file()


def run_llm_reparse(conference: str, create_ids: bool = False) -> Dict[str, Dict[str, Any]]:
    """Run the LLM re-parsing stage for a conference and save the resulting JSON."""
    global args
    args = argparse.Namespace(conferences=conference)
    if create_ids:
        ids = create_id_file()
    else:
        papers_to_parse_path = get_conference_path(conference, f"papers_to_parse_with_llm_{conference}.txt")
        with open(papers_to_parse_path, "r") as f:
            ids = f.readlines()
    results = get_github_links_from_papers_with_parsing_errors(ids)
    llm_output_path = get_conference_path(conference, f"llm_extracted_links_{conference}.json")
    with open(llm_output_path, "w") as f:
        json.dump(results, f)
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="use llms to extract github repos which might have been parsed erroneously before."
    )
    parser.add_argument(
        "create_id_file",
        help="True or False"
    )
    parser.add_argument(
        "conferences",
        help="which conferences should be included"
    )

    args = parser.parse_args()
    print(args)
    if args.create_id_file == "True":
        print("Creating and Parsing File")
        run_llm_reparse(args.conferences, create_ids=True)
    else:
        print("Reading and Parsing File")
        run_llm_reparse(args.conferences, create_ids=False)
