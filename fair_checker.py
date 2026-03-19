import json
import re
import html as html_lib
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from colorama import Fore, Style

BASE_GKHUB = "https://gkhub.earthobservations.org"


# ── GeoKnowledge Hub client ───────────────────────────────────────────────────

class GKHubClient:
    def __init__(self, base=BASE_GKHUB, timeout=30):
        self.base = base.rstrip("/")
        self.s = requests.Session()
        self.timeout = timeout

    def get_package(self, package_id):
        r = self.s.get(f"{self.base}/api/packages/{package_id}", timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_context_resources(self, parent_id, size=1000):
        r = self.s.get(
            f"{self.base}/api/packages/context/{parent_id}/resources",
            params={"size": size}, timeout=self.timeout
        )
        r.raise_for_status()
        return r.json()


# ── Display helpers ───────────────────────────────────────────────────────────

def _clean_html(text):
    """Strip HTML tags and normalise whitespace."""
    if not text:
        return text
    text = html_lib.unescape(text)
    soup = BeautifulSoup(text, "html.parser")
    for li in soup.find_all("li"):
        li.insert_before("\n- ")
        li.append("\n")
    for p in soup.find_all("p"):
        p.insert_before("\n\n")
        p.append("\n")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    cleaned = soup.get_text()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _color(text, *styles):
    return "".join(styles) + str(text) + Style.RESET_ALL


def summarize_package(pkg):
    """Print a human-readable summary of a GKHub package."""
    md = pkg.get("metadata", {})

    print(_color("=" * 90, Style.BRIGHT, Fore.CYAN))

    print(_color("TITLE", Style.BRIGHT, Fore.BLUE))
    print(_color("-" * 90, Fore.CYAN))
    print(_color(pkg.get("title") or md.get("title") or "N/A", Style.BRIGHT))
    print()

    print(_color("DESCRIPTION", Style.BRIGHT, Fore.BLUE))
    print(_color("-" * 90, Fore.CYAN))
    desc = md.get("description")
    if isinstance(desc, dict):
        desc = desc.get("en") or next(iter(desc.values()), "N/A")
    print(_clean_html(desc) or "N/A")
    print()

    print(_color("KEYWORDS", Style.BRIGHT, Fore.BLUE))
    print(_color("-" * 90, Fore.CYAN))
    subjects = md.get("subjects", [])
    keywords = [s.get("subject") for s in subjects if isinstance(s, dict) and s.get("subject")]
    print(_color(", ".join(keywords) if keywords else "N/A", Fore.GREEN))
    print()

    print(_color("CREATORS", Style.BRIGHT, Fore.BLUE))
    print(_color("-" * 90, Fore.CYAN))
    creators = md.get("creators", [])
    if creators:
        for i, c in enumerate(creators, 1):
            person = c.get("person_or_org", {})
            print(_color(f"[{i}]", Fore.YELLOW))
            print(_color("name:", Fore.RED), person.get("name") or "N/A")
            print(_color("email:", Fore.RED), person.get("email") or "N/A")
            print(_color("-" * 60, Fore.CYAN))
    else:
        print("N/A")
    print()

    print(_color("DATES", Style.BRIGHT, Fore.BLUE))
    print(_color("-" * 90, Fore.CYAN))
    print(_color("Created:", Fore.RED), pkg.get("created", "N/A"))
    print(_color("Updated:", Fore.RED), pkg.get("updated", "N/A"))
    print(_color("Publication date:", Fore.RED), md.get("publication_date", "N/A"))

    print(_color("=" * 90, Style.BRIGHT, Fore.CYAN))


# ── GKHub package parsing ─────────────────────────────────────────────────────

def parse_knowledge_resources(html_text, parent_package_id):
    """
    Parse a GKHub package HTML page and extract all knowledge resource entries,
    grouped by type: datasets, journal_publications, software, other.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    section = soup.find("section", id="knowledge-elements")
    if not section:
        return {}
    container = section.find("div", id="relatedRecordsDiv")
    if not container:
        return {}

    records = json.loads(container.get("data-record"))
    result = {"journal_publications": [], "datasets": [], "software": [], "other": []}

    for rec in records:
        metadata = rec.get("metadata", {})
        rtype = metadata.get("resource_type", {}).get("id", "")
        title = metadata.get("title")
        record_id = rec.get("id")

        doi = None
        pids = rec.get("pids", {})
        if "doi" in pids:
            doi = pids["doi"].get("identifier")

        entry = {
            "title": title,
            "record_id": record_id,
            "record_url": f"{BASE_GKHUB}/records/{record_id}?package={parent_package_id}",
            "publication_date": metadata.get("publication_date"),
            "doi": doi,
        }

        if rtype.startswith("publication"):
            result["journal_publications"].append(entry)
        elif rtype.startswith("dataset"):
            result["datasets"].append(entry)
        elif rtype.startswith("software") or rtype == "model":
            result["software"].append(entry)
        else:
            result["other"].append(entry)

    return result


# ── External metadata helpers ─────────────────────────────────────────────────

def resolve_doi_metadata(doi):
    """Try Crossref then DataCite to get bibliographic metadata for a DOI."""
    try:
        r = requests.get(f"https://api.crossref.org/works/{doi}", timeout=20)
        if r.status_code == 200:
            data = r.json()["message"]
            authors = [
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in data.get("author", [])
            ]
            return {
                "title": data.get("title", [None])[0],
                "journal": data.get("container-title", [None])[0],
                "year": data.get("issued", {}).get("date-parts", [[None]])[0][0],
                "volume": data.get("volume"),
                "issue": data.get("issue"),
                "pages": data.get("page"),
                "publisher": data.get("publisher"),
                "authors": authors,
            }
    except Exception:
        pass

    try:
        r = requests.get(f"https://api.datacite.org/dois/{doi}", timeout=20)
        if r.status_code == 200:
            data = r.json()["data"]["attributes"]
            authors = [c.get("name") for c in data.get("creators", [])]
            return {
                "title": data.get("titles", [{}])[0].get("title"),
                "journal": None,
                "year": data.get("publicationYear"),
                "volume": None,
                "issue": None,
                "pages": None,
                "publisher": data.get("publisher"),
                "authors": authors,
            }
    except Exception:
        pass

    return None


# ── Pretty-print knowledge resources ─────────────────────────────────────────

def pretty_print_knowledge_resources(data, title=None, package_id=None):
    """Print all knowledge resources from a parsed GKHub package."""
    sep = _color("-" * 70, Fore.CYAN)

    if title or package_id:
        print(_color("\n" + "=" * 90, Style.BRIGHT, Fore.CYAN))
        if title:
            print(_color(f"  {title}", Style.BRIGHT, Fore.WHITE))
        if package_id:
            url = f"{BASE_GKHUB}/packages/{package_id}"
            print(_color(f"  {url}", Fore.MAGENTA))
        print(_color("=" * 90, Style.BRIGHT, Fore.CYAN))

    def hdr(text):
        return _color(text, Style.BRIGHT, Fore.CYAN)

    def idx(text):
        return _color(text, Style.BRIGHT, Fore.WHITE)

    def lbl(text):
        return _color(text, Fore.BLUE)

    def doi_val(text):
        return _color(text, Fore.MAGENTA)

    # ── DATASETS ──────────────────────────────────────────────────────────────
    print(hdr("\n" + "=" * 90))
    print(hdr("DATASETS"))
    print(hdr("=" * 90))

    if data["datasets"]:
        for i, item in enumerate(data["datasets"], 1):
            print(idx(f"\n[{i}] {item['title']}"))
            print(lbl("Published:"), item["publication_date"])
            print(lbl("DOI:"), doi_val(item["doi"]) if item["doi"] else "N/A")
            print(lbl("Record:"), item["record_url"])

            if item["doi"] and item["doi"].startswith("10.5281/zenodo"):
                zenodo_info = get_zenodo_info(item["doi"])
                if zenodo_info:
                    zmd = zenodo_info["metadata"]
                    print("-" * 100)
                    print("\033[91m Authors: \033[0m",
                          ", ".join(p["name"] for p in zmd.get("creators", [])))
                    if "version" in zmd:
                        print("\033[91m Version: \033[0m", zmd.get("version"))
                    if "grants" in zmd:
                        print("\033[91m Funding: \033[0m")
                        for g in zmd["grants"]:
                            print("  ", g.get("title"), "|", g.get("funder", {}).get("name"))
                    if "license" in zmd:
                        print("\033[91m License: \033[0m", zmd["license"].get("id"))
                    if zenodo_info["dataset_files"]:
                        print("\033[91m Files: \033[0m")
                        for f in zenodo_info["dataset_files"]:
                            size_mb = (f["size"] or 0) / (1024 * 1024)
                            print(f"  • {f['filename']} ({size_mb:.2f} MB)")
                    print("-" * 100)
    else:
        print("None found.")

    # ── JOURNAL PUBLICATIONS ──────────────────────────────────────────────────
    print(hdr("\n" + "=" * 90))
    print(hdr("JOURNAL PUBLICATIONS"))
    print(hdr("=" * 90))

    if data["journal_publications"]:
        for i, item in enumerate(data["journal_publications"], 1):
            print(idx(f"\n[{i}] {item['title']}"))
            print(lbl("Record:"), item["record_url"])
            if item["doi"]:
                print(lbl("DOI:"), doi_val(item["doi"]))
                meta = resolve_doi_metadata(item["doi"])
                if meta:
                    if meta["authors"]:
                        print("  " + lbl("Authors:"), ", ".join(meta["authors"]))
                    if meta["journal"]:
                        print("  " + lbl("Journal:"), meta["journal"])
                    if meta["year"]:
                        print("  " + lbl("Year:"), meta["year"])
                    if meta["volume"]:
                        print("  " + lbl("Volume:"), meta["volume"])
                    if meta["pages"]:
                        print("  " + lbl("Pages:"), meta["pages"])
                    if meta["publisher"]:
                        print("  " + lbl("Publisher:"), meta["publisher"])
            else:
                print(lbl("DOI:"), "N/A")
            print(sep)
    else:
        print("None found.")

    # ── SOFTWARE / MODELS ─────────────────────────────────────────────────────
    print(hdr("\n" + "=" * 90))
    print(hdr("SOFTWARE / MODELS"))
    print(hdr("=" * 90))

    if data["software"]:
        for i, item in enumerate(data["software"], 1):
            print(idx(f"\n[{i}] {item['title']}"))
            print(lbl("Published:"), item["publication_date"])
            print(lbl("DOI:"), doi_val(item["doi"]) if item["doi"] else "N/A")
            print(lbl("Record:"), item["record_url"])
            print(sep)
    else:
        print("None found.")

    # ── OTHER ─────────────────────────────────────────────────────────────────
    print(hdr("\n" + "=" * 90))
    print(hdr("OTHER"))
    print(hdr("=" * 90))

    if data["other"]:
        for i, item in enumerate(data["other"], 1):
            print(idx(f"\n[{i}] {item['title']}"))
            print(lbl("Published:"), item["publication_date"])
            print(lbl("DOI:"), doi_val(item["doi"]) if item["doi"] else "N/A")
            print(lbl("Record:"), item["record_url"])
            print(sep)
    else:
        print("None found.")

    print(hdr("=" * 90))


# ── OEMC filename convention ──────────────────────────────────────────────────

_GEO_EXTENSIONS = (".tif", ".parquet", ".zarr", ".geojson", ".nc", ".h5", ".hdf5")


def check_filename(filename):
    """
    Validate a geographic data file against the OEMC naming convention:
      <variable>_<method>_<var_type>_<spatial_support>_<depth_ref>
      _<date_start>_<date_end>_<bbox>_<epsg>_<version>.<ext>

    Returns (True, "Valid"), (False, reason), or None if not a geo data file.
    """
    ext = next((e for e in _GEO_EXTENSIONS if filename.lower().endswith(e)), None)
    if ext is None:
        return None  # not a geographic data file — skip

    name = filename[: -len(ext)]
    parts = name.split("_")

    if len(parts) < 9:
        return False, "Filename has too few components"

    version        = parts[-1]
    epsg           = parts[-2]
    bbox           = parts[-3]
    date_end       = parts[-4]
    date_start     = parts[-5]
    depth_ref      = parts[-6]
    spatial_support = parts[-7]
    var_type       = parts[-8]
    # method and variable name occupy all remaining left-hand parts
    # (not validated here — free-form)

    if var_type not in {"m", "q.10", "d", "c", "cd", "p", "pv", "tv",
                        "sse", "l159", "u.841", "pc", "sd", "md", 
                        "si", "td", "n","p05", "p50", "p95"}:
        return False, f"Invalid variable type: '{var_type}'"

    if not re.fullmatch(r"\d+(m|km)", spatial_support):
        return False, f"Invalid spatial support: '{spatial_support}'"

    if not re.fullmatch(r"(?:[abs]|b.+)", depth_ref):
        return False, f"Invalid depth reference: '{depth_ref}'"

    try:
        start_dt = datetime.strptime(date_start, "%Y%m%d")
    except ValueError:
        return False, f"Invalid start date: '{date_start}'"
    try:
        end_dt = datetime.strptime(date_end, "%Y%m%d")
    except ValueError:
        return False, f"Invalid end date: '{date_end}'"
    if start_dt > end_dt:
        return False, f"Start date is after end date"

    if bbox not in {"go", "eu"}:
        return False, f"Invalid bounding box code: '{bbox}'"

    if epsg not in {"epsg.4326", "epsg.3035"}:
        return False, f"Invalid EPSG code: '{epsg}'"

    if not re.fullmatch(r"v\d{8}", version):
        return False, f"Invalid version format: '{version}'"

    return True, "Valid"


# ── Zenodo helpers ────────────────────────────────────────────────────────────

def check_zenodo_metadata(doi):
    if not doi or not doi.startswith("10.5281/zenodo"):
        return None

    record_id = doi.split(".")[-1]
    record_url = f"https://zenodo.org/api/records/{record_id}"

    response = requests.get(record_url, timeout=20)
    if response.status_code != 200:
        return None

    return response.json()["metadata"]

def get_zenodo_info(doi):
    """
    Extract complete information from a Zenodo entry including metadata and dataset files.
    Returns a dictionary with all information or None if the request fails.
    """
    if not doi or not doi.startswith("10.5281/zenodo"):
        return None

    record_id = doi.split(".")[-1]
    record_url = f"https://zenodo.org/api/records/{record_id}"

    try:
        response = requests.get(record_url, timeout=20)
        if response.status_code != 200:
            return None

        data = response.json()
        metadata = data.get("metadata", {})
        
        # Extract dataset files
        dataset_files = []
        for file_info in data.get("files", []):
            dataset_files.append({
                "filename": file_info.get("key"),
                "size": file_info.get("size"),
                "checksum": file_info.get("checksum"),
                "download_url": file_info.get("links", {}).get("self"),
                "id": file_info.get("id")
            })
        
        # Compile complete information
        return {
            "metadata": metadata,
            "dataset_files": dataset_files,
            "record_id": record_id,
            "doi": doi,
            "zenodo_url": f"https://zenodo.org/records/{record_id}"
        }
    
    except Exception as e:
        print(f"Error extracting info from Zenodo: {e}")
        return None



def check_findable(zenodo_info):
    checks = {
        "has_doi": bool(zenodo_info.get("doi")),
        "has_title": bool(zenodo_info["metadata"].get("title")),
        "has_description": bool(zenodo_info["metadata"].get("description")),
        "has_keywords": len(zenodo_info["metadata"].get("keywords", [])) > 0,
        "has_authors": len(zenodo_info["metadata"].get("creators", [])) > 0,
        "has_publication_date": bool(zenodo_info["metadata"].get("publication_date")),
        "has_version": bool(zenodo_info["metadata"].get("version")),
    }
    return checks

def check_accessible(zenodo_info):
    license_id = zenodo_info["metadata"].get("license", {}).get("id", "")
    checks = {
        "has_download_links": len(zenodo_info.get("dataset_files", [])) > 0,
        "doi_resolves": check_doi_resolves(zenodo_info["doi"]),
        "is_open_access": zenodo_info["metadata"].get("access_right") == "open",
        "license_is_cc_by": license_id.lower() in ("cc-by-4.0", "cc-by"),
    }
    checks["_license_id_info"] = license_id
    checks["_access_right_info"] = zenodo_info["metadata"].get("access_right")
    return checks

def check_doi_resolves(doi):
    try:
        response = requests.head(f"https://doi.org/{doi}", timeout=10)
        return response.status_code in [200, 302]
    except:
        return False

_PREFERRED_FORMATS = {'.geojson', '.tif', '.tiff', '.nc', '.zarr', '.shp', '.parquet', '.h5', '.hdf5', '.gpkg'}
_UNACCEPTABLE_FORMATS = {'.csv', '.json', '.txt', '.xml'}
_PROPRIETARY_FORMATS = {'.xlsx', '.xls', '.doc', '.docx'}


def check_interoperable(zenodo_info):
    files = zenodo_info.get("dataset_files", [])
    file_extensions = {f".{f['filename'].rsplit('.', 1)[-1].lower()}" for f in files if '.' in f["filename"]}

    uses_preferred = bool(file_extensions & _PREFERRED_FORMATS)
    #non_preferred = file_extensions - _PREFERRED_FORMATS - _UNACCEPTABLE_FORMATS - _PROPRIETARY_FORMATS
    non_preferred = file_extensions - _PREFERRED_FORMATS - _PROPRIETARY_FORMATS

    # Naming convention: only applied to geographic data files
    naming_results = [check_filename(f["filename"]) for f in files]
    naming_results = [r for r in naming_results if r is not None]  # drop non-geo files
    naming_issues = [msg for ok, msg in naming_results if not ok]
    files_follow_naming_convention = all(ok for ok, _ in naming_results) if naming_results else None

    checks = {
        "uses_preferred_formats": uses_preferred,
        "avoids_proprietary": not bool(file_extensions & _PROPRIETARY_FORMATS),
        "has_related_identifiers": len(
            zenodo_info["metadata"].get("related_identifiers", [])
        ) > 0,
        "links_to_publications": any(
            rel.get("resource_type") == "publication-article"
            for rel in zenodo_info["metadata"].get("related_identifiers", [])
        ),
        "has_communities": len(
            zenodo_info["metadata"].get("communities", [])
        ) > 0,
    }
    if files_follow_naming_convention is not None:
        checks["files_follow_naming_convention"] = files_follow_naming_convention

    checks["_file_formats_info"] = sorted(file_extensions)
    checks["_non_preferred_formats"] = sorted(non_preferred) if non_preferred else []
    checks["_naming_issues"] = naming_issues
    return checks

def check_reusable(zenodo_info):
    metadata = zenodo_info["metadata"]

    description_length = len(metadata.get("description", "").strip())

    open_licenses = ['cc-by-4.0', 'cc-by']

    checks = {
        "has_license": bool(metadata.get("license")),
        "license_is_open": metadata.get("license", {}).get("id") in open_licenses,
        "has_detailed_description": description_length > 200,
        "has_funding_info": len(metadata.get("grants", [])) > 0,
        "has_references": len(metadata.get("references", [])) > 0,
        "links_to_code": any(
            rel.get("resource_type") == "software"
            for rel in metadata.get("related_identifiers", [])
        ) or bool(metadata.get("custom", {}).get("code:codeRepository")),
        "has_version": bool(metadata.get("version")),
    }
    # Store additional info separately for reference, not in scoring
    checks["_license_id_info"] = metadata.get("license", {}).get("id")
    checks["_code_repository_info"] = metadata.get("custom", {}).get("code:codeRepository")
    return checks

def assess_fair_compliance(doi):
    """
    Comprehensive FAIR principles assessment for a Zenodo entry.
    Returns a detailed report with scores and recommendations.
    """
    zenodo_info = get_zenodo_info(doi)
    
    if not zenodo_info:
        return {"error": "Could not retrieve Zenodo information"}
    
    # Run all checks
    findable = check_findable(zenodo_info)
    accessible = check_accessible(zenodo_info)
    interoperable = check_interoperable(zenodo_info)
    reusable = check_reusable(zenodo_info)
    
    # Calculate scores (exclude keys starting with '_' from scoring)
    def calculate_score(checks):
        scoreable = {k: v for k, v in checks.items() if not k.startswith('_')}
        if not scoreable:
            return 0
        return sum(scoreable.values()) / len(scoreable) * 100
    
    scores = {
        "Findable": calculate_score(findable),
        "Accessible": calculate_score(accessible),
        "Interoperable": calculate_score(interoperable),
        "Reusable": calculate_score(reusable)
    }
    
    scores["Overall"] = sum(scores.values()) / 4
    
    return {
        "doi": doi,
        "title": zenodo_info["metadata"].get("title"),
        "scores": scores,
        "details": {
            "findable": findable,
            "accessible": accessible,
            "interoperable": interoperable,
            "reusable": reusable
        },
        "recommendations": generate_recommendations(
            findable, accessible, interoperable, reusable
        )
    }


def generate_recommendations(findable, accessible, interoperable, reusable):
    """Generate actionable recommendations based on failed checks."""
    recommendations = []
    
    if not findable.get("has_keywords"):
        recommendations.append("Add relevant keywords/tags to improve discoverability")

    if not accessible.get("is_open_access"):
        recommendations.append("Consider making data openly accessible")

    if not accessible.get("license_is_cc_by"):
        recommendations.append("License must be CC-BY-4.0 per data release policy")

    if not interoperable.get("avoids_proprietary"):
        recommendations.append("Convert proprietary formats to open standards")

    if not interoperable.get("uses_preferred_formats"):
        non_pref = interoperable.get("_non_preferred_formats", [])
        detail = f" ({', '.join(non_pref)})" if non_pref else ""
        recommendations.append(
            f"No preferred geographic formats found{detail}; consider using "
            f"{', '.join(sorted(_PREFERRED_FORMATS))}"
        )

    if interoperable.get("files_follow_naming_convention") is False:
        issues = interoperable.get("_naming_issues", [])
        detail = f": {issues[0]}" if issues else ""
        recommendations.append(f"Geographic files do not follow OEMC naming convention{detail}")

    if not interoperable.get("links_to_publications"):
        recommendations.append("Link to related publications using DOIs")

    if not reusable.get("has_funding_info"):
        recommendations.append("Add funding/grant information")

    if not reusable.get("links_to_code"):
        recommendations.append("Link to code repository if software was used to generate data")
    
    return recommendations

def print_fair_report(assessment):
    """Pretty print the FAIR assessment report."""
    print("\n" + "=" * 90)
    print(f"FAIR ASSESSMENT REPORT")
    print("=" * 90)
    print(f"\nTitle: {assessment['title']}")
    print(f"DOI: {assessment['doi']}")
    
    print("\n" + "-" * 90)
    print("FAIR SCORES:")
    print("-" * 90)
    for principle, score in assessment['scores'].items():
        bar_length = int(score / 5)
        bar = "█" * bar_length + "░" * (20 - bar_length)
        print(f"{principle:15} [{bar}] {score:.1f}%")
    
    print("\n" + "-" * 90)
    print("RECOMMENDATIONS:")
    print("-" * 90)
    if assessment['recommendations']:
        for i, rec in enumerate(assessment['recommendations'], 1):
            print(f"{i}. {rec}")
    else:
        print("✓ No recommendations - fully FAIR compliant!")
    
    print("\n" + "=" * 90)


# ── Markdown report writer ────────────────────────────────────────────────────

def _score_badge(score):
    """Return a text badge based on score."""
    if score >= 80:
        return "🟢"
    elif score >= 60:
        return "🟡"
    else:
        return "🔴"


def _score_bar(score, width=20):
    filled = int(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def write_report(pkg, resources, results, output_path=None):
    """
    Write a Markdown report combining package summary, knowledge resources,
    and FAIR compliance results.

    Parameters
    ----------
    pkg : dict
        Package metadata dict from GKHubClient.get_package().
    resources : dict
        Parsed resources dict from parse_knowledge_resources().
    results : dict
        FAIR assessment results from assess_all_knowledge_resources_fair().
    output_path : str, optional
        File path to write to. Defaults to 'fair_report_<timestamp>.md'.

    Returns
    -------
    str
        The path of the written file.
    """
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"fair_report_{timestamp}.md"

    lines = []
    md = pkg.get("metadata", {})

    # ── Header ────────────────────────────────────────────────────────────────
    title = pkg.get("title") or md.get("title") or "Untitled Package"
    lines += [
        f"# FAIR Assessment Report",
        f"",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"---",
        f"",
    ]

    # ── 1. Package Summary ────────────────────────────────────────────────────
    lines += [
        f"## 1. Package Summary",
        f"",
        f"**Title:** {title}",
        f"",
    ]

    pkg_id = pkg.get("id") or pkg.get("slug")
    if pkg_id:
        lines.append(f"**GeoKnowledge Hub:** [{BASE_GKHUB}/packages/{pkg_id}]({BASE_GKHUB}/packages/{pkg_id})")
        lines.append(f"")

    desc = md.get("description")
    if isinstance(desc, dict):
        desc = desc.get("en") or next(iter(desc.values()), None)
    if desc:
        lines += [f"**Description:**", f"", _clean_html(desc), f""]

    subjects = md.get("subjects", [])
    keywords = [s.get("subject") for s in subjects if isinstance(s, dict) and s.get("subject")]
    if keywords:
        lines.append(f"**Keywords:** {', '.join(keywords)}")
        lines.append(f"")

    creators = md.get("creators", [])
    if creators:
        lines.append(f"**Creators:**")
        lines.append(f"")
        for c in creators:
            person = c.get("person_or_org", {})
            name = person.get("name") or "N/A"
            email = person.get("email") or ""
            lines.append(f"- {name}" + (f" ({email})" if email else ""))
        lines.append(f"")

    lines += [
        f"| Field | Value |",
        f"|---|---|",
        f"| Created | {pkg.get('created', 'N/A')} |",
        f"| Updated | {pkg.get('updated', 'N/A')} |",
        f"| Publication Date | {md.get('publication_date', 'N/A')} |",
        f"",
        f"---",
        f"",
    ]

    # ── 2. Knowledge Resources ────────────────────────────────────────────────
    lines += [f"## 2. Knowledge Resources", f""]

    def _resources_table(items, show_zenodo=False):
        if not items:
            return ["_None found._", ""]
        rows = ["| # | Title | DOI | Date |", "|---|---|---|---|"]
        for i, item in enumerate(items, 1):
            t = item["title"] or ""
            doi_str = f"[{item['doi']}](https://doi.org/{item['doi']})" if item["doi"] else "N/A"
            date = item.get("publication_date") or "N/A"
            rows.append(f"| {i} | {t} | {doi_str} | {date} |")
        return rows + [""]

    lines += [f"### Datasets ({len(resources['datasets'])})",""]
    lines += _resources_table(resources["datasets"])

    lines += [f"### Journal Publications ({len(resources['journal_publications'])})",""]
    lines += _resources_table(resources["journal_publications"])

    lines += [f"### Software / Models ({len(resources['software'])})",""]
    lines += _resources_table(resources["software"])

    lines += [f"### Other ({len(resources['other'])})",""]
    lines += _resources_table(resources["other"])

    lines += [f"---", f""]

    # ── 3. FAIR Compliance ────────────────────────────────────────────────────
    lines += [f"## 3. FAIR Compliance Assessment", f""]

    all_assessments = results.get("datasets", [])
    if not all_assessments:
        lines += ["_No dataset assessments available._", ""]
    else:
        # Average scores
        principles = ["Findable", "Accessible", "Interoperable", "Reusable", "Overall"]
        avg_scores = {
            p: sum(a["scores"][p] for a in all_assessments) / len(all_assessments)
            for p in principles
        }

        lines += [
            f"**Total datasets assessed:** {len(all_assessments)}",
            f"",
            f"### Average FAIR Scores",
            f"",
            f"| Principle | Score | Bar |",
            f"|---|---|---|",
        ]
        for p in principles:
            s = avg_scores[p]
            lines.append(f"| {p} | {_score_badge(s)} {s:.1f}% | `{_score_bar(s)}` |")
        lines.append(f"")

        # Per-dataset detail
        lines += [f"### Per-Dataset Results", f""]
        for a in all_assessments:
            t = a["title"] or "Untitled"
            doi_link = f"[{a['doi']}](https://doi.org/{a['doi']})" if a.get("doi") else "N/A"
            overall = a["scores"]["Overall"]
            lines += [
                f"#### {t}",
                f"",
                f"**DOI:** {doi_link}",
                f"",
                f"| Principle | Score |",
                f"|---|---|",
            ]
            for p in principles:
                s = a["scores"][p]
                lines.append(f"| {p} | {_score_badge(s)} {s:.1f}% |")
            lines.append(f"")

            # Detailed check results
            details = a.get("details", {})
            for principle_key, label in [
                ("findable", "Findable"),
                ("accessible", "Accessible"),
                ("interoperable", "Interoperable"),
                ("reusable", "Reusable"),
            ]:
                checks = details.get(principle_key, {})
                scoreable = {k: v for k, v in checks.items() if not k.startswith("_")}
                if scoreable:
                    lines.append(f"**{label} checks:**")
                    lines.append(f"")
                    for k, v in scoreable.items():
                        icon = "✅" if v else "❌"
                        lines.append(f"- {icon} `{k}`")
                    # info fields
                    for k, v in checks.items():
                        if k.startswith("_") and v:
                            label_info = k.lstrip("_").replace("_", " ")
                            lines.append(f"  - _{label_info}: {v}_")
                    lines.append(f"")

            if a.get("recommendations"):
                lines += [f"**Recommendations:**", f""]
                for rec in a["recommendations"]:
                    lines.append(f"- {rec}")
                lines.append(f"")

            lines.append(f"---")
            lines.append(f"")

    content = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(content)

    print(f"Report written to: {output_path}")
    return output_path



def assess_all_knowledge_resources_fair(data):
    """
    Assess FAIR compliance for dataset entries discovered via GeoKnowledge Hub.
    Only datasets with Zenodo DOIs are assessed.
    Returns a summary report.
    """
    results = {"datasets": []}

    print("\n" + "=" * 90)
    print("ASSESSING FAIR COMPLIANCE FOR DATASETS")
    print("=" * 90)

    print("\n### DATASETS ###")
    for item in data["datasets"]:
        print(f"\nAssessing: {item['title'][:60]}...")

        if item.get("doi") and item["doi"].startswith("10.5281/zenodo"):
            try:
                assessment = assess_fair_compliance(item["doi"])
                results["datasets"].append(assessment)
                print(f"  ✓ Zenodo Assessment: Overall {assessment['scores']['Overall']:.1f}%")
            except Exception as e:
                print(f"  ✗ Zenodo Assessment failed: {e}")
        else:
            print(f"  ℹ No Zenodo DOI available — skipping FAIR assessment")

    print("\n" + "=" * 90)

    return results


def print_summary_report(results):
    """Print a summary of FAIR assessments for datasets."""
    print("\n" + "=" * 90)
    print("FAIR COMPLIANCE SUMMARY REPORT")
    print("=" * 90)

    all_assessments = results["datasets"]

    if not all_assessments:
        print("\nNo dataset assessments available.")
        return

    # Calculate average scores
    avg_scores = {
        "Findable": sum(a["scores"]["Findable"] for a in all_assessments) / len(all_assessments),
        "Accessible": sum(a["scores"]["Accessible"] for a in all_assessments) / len(all_assessments),
        "Interoperable": sum(a["scores"]["Interoperable"] for a in all_assessments) / len(all_assessments),
        "Reusable": sum(a["scores"]["Reusable"] for a in all_assessments) / len(all_assessments),
        "Overall": sum(a["scores"]["Overall"] for a in all_assessments) / len(all_assessments)
    }

    print(f"\nTotal Datasets Assessed: {len(all_assessments)}")

    print("\n" + "-" * 90)
    print("AVERAGE FAIR SCORES:")
    print("-" * 90)
    for principle, score in avg_scores.items():
        bar_length = int(score / 5)
        bar = "█" * bar_length + "░" * (20 - bar_length)
        color = "\033[92m" if score >= 80 else "\033[93m" if score >= 60 else "\033[91m"
        reset = "\033[0m"
        print(f"{principle:15} [{bar}] {color}{score:.1f}%{reset}")

    # Find datasets with lowest scores
    print("\n" + "-" * 90)
    print("DATASETS NEEDING ATTENTION (Lowest Overall Scores):")
    print("-" * 90)
    sorted_assessments = sorted(all_assessments, key=lambda x: x["scores"]["Overall"])[:5]
    for i, assessment in enumerate(sorted_assessments, 1):
        title = assessment['title'][:60] + "..." if len(assessment['title']) > 60 else assessment['title']
        print(f"{i}. {title}")
        print(f"   DOI: https://doi.org/{assessment['doi']}")
        print(f"   Overall Score: {assessment['scores']['Overall']:.1f}%")
        if assessment['recommendations']:
            print(f"   Top Issues: {', '.join(assessment['recommendations'][:3])}")

    print("\n" + "=" * 90)