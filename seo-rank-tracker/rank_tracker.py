from typing import Optional

import os
import json
import requests
from datetime import date
from pathlib import Path

API_KEY = os.getenv("SEARCHAPI_KEY")

if not API_KEY:
    raise ValueError("La variable d'environnement SEARCHAPI_KEY est absente.")

CONFIG_FILE = "clients.json"
OUTPUT_DIR = "seo-json"


def search_keyword(keyword: str, location: str) -> dict:
    url = "https://www.searchapi.io/api/v1/search"

    params = {
        "engine": "google",
        "q": keyword,
        "location": location,
        "gl": "ca",
        "hl": "fr",
        "num": 50,
        "api_key": API_KEY,
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def normalize_domain(value: str) -> str:
    return (
        value.lower()
        .replace("https://", "")
        .replace("http://", "")
        .replace("www.", "")
        .strip("/")
        .strip()
    )


def find_domain_positions(data: dict, domain: str) -> list:
    results = data.get("organic_results", [])
    matches = []

    domain = normalize_domain(domain)

    for item in results:
        link = item.get("link", "")
        position = item.get("position")
        title = item.get("title", "")
        snippet = item.get("snippet", "")

        if not link:
            continue

        link_clean = normalize_domain(link)

        if domain in link_clean:
            matches.append({
                "position": position,
                "title": title,
                "link": link,
                "snippet": snippet
            })

    return matches


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


def load_existing_json(slug: str) -> dict:
    output_path = Path(OUTPUT_DIR) / f"{slug}.json"

    if output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass

    return {
        "client_slug": slug,
        "client_name": "",
        "location": "",
        "updated_at": "",
        "keywords": []
    }


def get_previous_entry(existing_data: dict, keyword: str) -> Optional[dict]:

    for item in existing_data.get("keywords", []):
        if item.get("keyword") == keyword:
            return item
    return None


def merge_history(previous_item: Optional[dict], new_position, new_url: str) -> list:

    today = date.today().isoformat()
    history = []

    if previous_item and isinstance(previous_item.get("history"), list):
        history = previous_item["history"][:]

    if history and history[-1].get("date") == today:
        history[-1] = {
            "date": today,
            "position": new_position,
            "url": new_url
        }
    else:
        history.append({
            "date": today,
            "position": new_position,
            "url": new_url
        })

    return history


def calculate_change(current_position, previous_position):
    if current_position is None or previous_position is None:
        return None

    try:
        return previous_position - current_position
    except TypeError:
        return None


def analyze_client(client, selected_keyword=None):
    today = date.today().isoformat()

    client_name = client["name"]
    client_slug = client["slug"]
    domain = client["domain"]
    location = client["location"]
    keywords = client["keywords"]

    if selected_keyword:
        keywords_to_check = [selected_keyword]
    else:
        keywords_to_check = keywords

    existing_data = load_existing_json(client_slug)

    keyword_map = {}
    for item in existing_data.get("keywords", []):
        keyword_map[item.get("keyword")] = item

    new_keywords_data = []

    print(f"\n=== Analyse pour {client_name} ===")

    for keyword in keywords_to_check:
        print(f"\nRecherche : {keyword}")

        previous_item = keyword_map.get(keyword)
        previous_position = None

        if previous_item:
            previous_position = previous_item.get("current_position")

        try:
            data = search_keyword(keyword, location)
            matches = find_domain_positions(data, domain)

            if matches:
                best_match = sorted(
                    [m for m in matches if m.get("position") is not None],
                    key=lambda x: x["position"]
                )[0]

                current_position = best_match.get("position")
                current_url = best_match.get("link", "")
                change = calculate_change(current_position, previous_position)
                history = merge_history(previous_item, current_position, current_url)

                print(f"Position {current_position} -> {current_url}")

                new_keywords_data.append({
                    "keyword": keyword,
                    "current_position": current_position,
                    "previous_position": previous_position,
                    "change": change,
                    "current_url": current_url,
                    "history": history
                })
            else:
                current_position = None
                current_url = ""
                change = calculate_change(current_position, previous_position)
                history = merge_history(previous_item, current_position, current_url)

                print("Aucun résultat trouvé")

                new_keywords_data.append({
                    "keyword": keyword,
                    "current_position": current_position,
                    "previous_position": previous_position,
                    "change": change,
                    "current_url": current_url,
                    "history": history
                })

        except requests.RequestException as e:
            print(f"Erreur API : {e}")

            if previous_item:
                new_keywords_data.append(previous_item)
            else:
                new_keywords_data.append({
                    "keyword": keyword,
                    "current_position": None,
                    "previous_position": None,
                    "change": None,
                    "current_url": "",
                    "history": []
                })

    if not selected_keyword:
        checked_keywords = {item["keyword"] for item in new_keywords_data}

        for old_item in existing_data.get("keywords", []):
            if old_item.get("keyword") not in checked_keywords:
                new_keywords_data.append(old_item)

    output_data = {
        "client_slug": client_slug,
        "client_name": client_name,
        "location": location,
        "updated_at": today,
        "keywords": new_keywords_data
    }

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    output_path = Path(OUTPUT_DIR) / f"{client_slug}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\nJSON créé : {output_path}")


def main():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    clients = config.get("clients", [])

    if not clients:
        print("Aucun client trouvé dans clients.json")
        return

    print("\nMenu :")
    print("1 - Analyser un client")
    print("2 - Analyser tous les clients")
    print("3 - Analyser un mot-clé d'un client")

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
