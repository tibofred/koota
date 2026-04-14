from typing import Optional
from urllib.parse import urlparse
from pathlib import Path
from datetime import date
from dotenv import load_dotenv
import os
import re
import csv
import json
import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=ENV_PATH)

API_KEY = os.getenv("SEARCHAPI_KEY")

if not API_KEY:
    raise ValueError("La variable d'environnement SEARCHAPI_KEY est absente.")

CONFIG_FILE = "clients.json"
OUTPUT_DIR = "exports"


def search_keyword(keyword: str, location: str) -> dict:
    url = "https://www.searchapi.io/api/v1/search"

    params = {
        "engine": "google_rank_tracking",
        "q": keyword,
        "location": location,
        "gl": "ca",
        "hl": "fr",
        "num": 100,
        "api_key": API_KEY,
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def normalize_domain(value: str) -> str:
    if not value:
        return ""

    value = value.lower().strip()

    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        host = parsed.netloc
    else:
        host = value

    host = host.replace("www.", "").strip().strip("/")
    return host


def get_root_domain(value: str) -> str:
    host = normalize_domain(value)
    parts = host.split(".")

    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def slugify_filename(value: str) -> str:
    value = value.strip().lower()
    value = value.replace("&", " et ")
    value = value.replace("'", "")
    value = re.sub(r"[^a-z0-9àâäçéèêëîïôöùûüÿñæœ -]", "", value, flags=re.IGNORECASE)
    value = value.replace(" ", "-")
    value = re.sub(r"-+", "-", value)
    return value.strip("-") or "mot-cle"


def fetch_meta_tags(url: str) -> dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        title_tag = soup.find("title")
        meta_desc_tag = soup.find("meta", attrs={"name": "description"})

        meta_title = title_tag.get_text(strip=True) if title_tag else ""
        meta_description = (
            meta_desc_tag.get("content", "").strip() if meta_desc_tag else ""
        )

        return {
            "meta_title": meta_title,
            "meta_description": meta_description,
        }

    except requests.RequestException:
        return {
            "meta_title": "",
            "meta_description": "",
        }


def build_exclusion_sets(client_domain: str, exclude_domains: Optional[list] = None):
    excluded_hosts = set()
    excluded_roots = set()

    all_domains = [client_domain]
    if exclude_domains:
        all_domains.extend(exclude_domains)

    for domain in all_domains:
        host = normalize_domain(domain)
        root = get_root_domain(domain)

        if host:
            excluded_hosts.add(host)
        if root:
            excluded_roots.add(root)

    return excluded_hosts, excluded_roots


def is_excluded_domain(result_domain: str, excluded_hosts: set, excluded_roots: set) -> bool:
    host = normalize_domain(result_domain)
    root = get_root_domain(result_domain)

    if not host:
        return True

    if host in excluded_hosts:
        return True

    if root in excluded_roots:
        return True

    for excluded_host in excluded_hosts:
        if host.endswith("." + excluded_host):
            return True

    return False


def extract_top_competitors(
    data: dict,
    client_domain: str,
    exclude_domains: Optional[list] = None,
    limit: int = 5,
) -> list:
    organic_results = data.get("organic_results", [])
    competitors = []

    excluded_hosts, excluded_roots = build_exclusion_sets(client_domain, exclude_domains)
    seen_domains = set()

    for item in organic_results:
        link = item.get("link", "").strip()
        title = item.get("title", "").strip()
        snippet = item.get("snippet", "").strip()
        position = item.get("position")

        if not link:
            continue

        result_host = normalize_domain(link)
        result_root = get_root_domain(link)

        if not result_host or not result_root:
            continue

        if is_excluded_domain(result_host, excluded_hosts, excluded_roots):
            continue

        if result_root in seen_domains:
            continue

        seen_domains.add(result_root)

        meta = fetch_meta_tags(link)

        competitors.append({
            "position": position,
            "title": title,
            "url": link,
            "meta_title": meta.get("meta_title", ""),
            "meta_description": meta.get("meta_description", ""),
            "snippet": snippet,
            "domain": result_root,
        })

        if len(competitors) >= limit:
            break

    return competitors


def export_keyword_csv(client_slug: str, keyword: str, rows: list):
    client_dir = Path(OUTPUT_DIR) / client_slug
    client_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{slugify_filename(keyword)}.csv"
    output_path = client_dir / filename

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)

        writer.writerow([
            "Position",
            "Titre SERP",
            "URL",
            "Meta title",
            "Meta description",
            "Snippet",
            "Domaine",
            "Mot clé",
        ])

        for row in rows:
            writer.writerow([
                row.get("position", ""),
                row.get("title", ""),
                row.get("url", ""),
                row.get("meta_title", ""),
                row.get("meta_description", ""),
                row.get("snippet", ""),
                row.get("domain", ""),
                keyword,
            ])

    print(f"CSV créé : {output_path}")


def choose_client(clients):
    print("\nClients disponibles :\n")

    for i, client in enumerate(clients, start=1):
        print(f"{i} - {client['name']}")

    while True:
        choice = input("\nChoisir un client : ").strip()

        if choice.isdigit():
            choice_num = int(choice)
            if 1 <= choice_num <= len(clients):
                return clients[choice_num - 1]

        print("Choix invalide.")


def choose_keyword(keywords):
    print("\nMots-clés disponibles :\n")

    for i, keyword in enumerate(keywords, start=1):
        print(f"{i} - {keyword}")

    while True:
        choice = input("\nChoisir un mot-clé : ").strip()

        if choice.isdigit():
            choice_num = int(choice)
            if 1 <= choice_num <= len(keywords):
                return keywords[choice_num - 1]

        print("Choix invalide.")


def analyze_client(client, selected_keyword: Optional[str] = None):
    client_name = client["name"]
    client_slug = client["slug"]
    domain = client["domain"]
    location = client["location"]
    keywords = client["keywords"]
    exclude_domains = client.get("exclude_domains", [])

    if selected_keyword:
        keywords_to_check = [selected_keyword]
    else:
        keywords_to_check = keywords

    print(f"\n=== Analyse des compétiteurs pour {client_name} ===")
    print(f"Région : {location}")
    print(f"Domaine client exclu : {domain}")
    print(
        "Domaines exclus supplémentaires : "
        f"{', '.join(exclude_domains) if exclude_domains else 'Aucun'}"
    )
    print(f"Date : {date.today().isoformat()}")

    for keyword in keywords_to_check:
        print(f"\nRecherche du mot-clé : {keyword}")

        try:
            data = search_keyword(keyword, location)
            competitors = extract_top_competitors(
                data=data,
                client_domain=domain,
                exclude_domains=exclude_domains,
                limit=5,
            )

            if competitors:
                export_keyword_csv(client_slug, keyword, competitors)

                print("Top compétiteurs trouvés :")
                for c in competitors:
                    print(
                        f"- Position {c.get('position')} | "
                        f"{c.get('domain')} | {c.get('url')}"
                    )
            else:
                print("Aucun compétiteur trouvé pour ce mot-clé.")
                export_keyword_csv(client_slug, keyword, [])

        except requests.RequestException as e:
            print(f"Erreur API pour '{keyword}' : {e}")


def main():
    if not Path(CONFIG_FILE).exists():
        raise FileNotFoundError(f"Fichier introuvable : {CONFIG_FILE}")

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    clients = config.get("clients", [])

    if not clients:
        print("Aucun client trouvé dans clients.json")
        return

    print("\nMenu :")
    print("1 - Analyser un client complet")
    print("2 - Analyser tous les clients")
    print("3 - Analyser un seul mot-clé d'un client")

    choice = input("\nChoisir une option : ").strip()

    if choice == "1":
        client = choose_client(clients)
        analyze_client(client)

    elif choice == "2":
        for client in clients:
            analyze_client(client)

    elif choice == "3":
        client = choose_client(clients)
        keyword = choose_keyword(client["keywords"])
        analyze_client(client, selected_keyword=keyword)

    else:
        print("Option invalide.")


if __name__ == "__main__":
    main()
