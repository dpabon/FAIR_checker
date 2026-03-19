# OEMC FAIR Checker

A tool for assessing [FAIR](https://www.go-fair.org/fair-principles/) (Findable, Accessible, Interoperable, Reusable) compliance of datasets published via [GeoKnowledge Hub](https://gkhub.earthobservations.org) and archived on [Zenodo](https://zenodo.org).

---

## How it works

1. Fetches a GeoKnowledge Hub package and lists all linked knowledge resources (datasets, publications, software).
2. For each dataset with a Zenodo DOI, retrieves metadata and files from the Zenodo API.
3. Runs FAIR checks and produces a scored report with actionable recommendations.
4. Optionally writes the full report to a Markdown file.

## FAIR Criteria

| Principle | Checks |
|---|---|
| **Findable** | Has DOI, title, description, keywords, authors, publication date, version |
| **Accessible** | Files downloadable, DOI resolves, open access, CC-BY / CC-BY-4.0 license |
| **Interoperable** | Uses preferred geographic formats, avoids proprietary formats, links to publications, belongs to communities, follows OEMC filename convention |
| **Reusable** | License present and open, detailed description (>200 chars), funding info, links to code, version |

### Preferred geographic formats

`.geojson`, `.tif / .tiff`, `.nc`, `.zarr`, `.shp`, `.parquet`, `.h5 / .hdf5`, `.gpkg`

### OEMC filename convention

Geographic files are validated against the OEMC naming convention:

```
{variable}_{method}_{var_type}_{spatial_support}_{depth_ref}_{date_start}_{date_end}_{bbox}_{epsg}_{version}.{ext}
```

Example: `lccs_rf_m_1km_s_20000101_20001231_eu_epsg.3035_v20240101.tif`

## Usage

Open `OEMC_FAIRChecker.ipynb` in Jupyter and run the cells in order:

1. **Fetch package** — set `PACKAGE_ID` and fetch GKHub metadata
2. **Parse resources** — extract datasets, publications, software
3. **Assess FAIR** — run checks on all Zenodo datasets
4. **Export report** — write a Markdown report file

```python
from fair_checker import GKHubClient, parse_knowledge_resources, \
    assess_all_knowledge_resources_fair, write_report

client = GKHubClient()
pkg = client.get_package("your-package-id")
resources = parse_knowledge_resources(html_text, "your-package-id")
results = assess_all_knowledge_resources_fair(resources)
write_report(pkg, resources, results)          # writes fair_report_<timestamp>.md
```

## Requirements

```
requests
beautifulsoup4
colorama
```

Install with:

```bash
pip install requests beautifulsoup4 colorama
```
