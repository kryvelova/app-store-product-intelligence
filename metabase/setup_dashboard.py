"""Bootstrap Metabase: admin account, analytics DB connection, cards, and
the "US App Store Engagement" dashboard — all via Metabase's REST API.

Idempotent: safe to re-run. Existing cards/dashboard with the same names
are replaced; the admin account and database connection are reused if they
already exist.

Requires Postgres + Metabase running (`docker compose up -d`) and
`mart_app_category_engagement` already built (`python3 -m transform.build_marts`).

Usage:
    python3 -m metabase.setup_dashboard
"""

import sys
import time
import uuid
from pathlib import Path

import requests
from dotenv import dotenv_values

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
_ENV = {**dotenv_values(_ENV_FILE)}

MB_URL = _ENV.get("MB_SITE_URL", "http://localhost:3000").rstrip("/")
MB_ADMIN_EMAIL = _ENV.get("MB_ADMIN_EMAIL")
MB_ADMIN_PASSWORD = _ENV.get("MB_ADMIN_PASSWORD")

POSTGRES_DB = _ENV.get("POSTGRES_DB")
POSTGRES_USER = _ENV.get("POSTGRES_USER")
POSTGRES_PASSWORD = _ENV.get("POSTGRES_PASSWORD")

ANALYTICS_DB_NAME = "App Store Analytics"
DASHBOARD_NAME = "US App Store Engagement"
MART_TABLE = "mart_app_category_engagement"

# Below this many rated apps backing a category's average, we don't trust
# it enough to compare — see the caveat text card for why.
MIN_RATED_APPS_DEFAULT = 10

_REQUIRED = {
    "MB_ADMIN_EMAIL": MB_ADMIN_EMAIL,
    "MB_ADMIN_PASSWORD": MB_ADMIN_PASSWORD,
    "POSTGRES_DB": POSTGRES_DB,
    "POSTGRES_USER": POSTGRES_USER,
    "POSTGRES_PASSWORD": POSTGRES_PASSWORD,
}


def _check_env() -> None:
    missing = [name for name, value in _REQUIRED.items() if not value]
    if missing:
        raise RuntimeError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Copy .env.example to .env and fill them in."
        )


def _tag_id() -> str:
    return str(uuid.uuid4())


class Metabase:
    """Thin wrapper around the subset of the Metabase API this script needs."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = requests.Session()

    def _headers(self):
        return {"X-Metabase-Session": self.token} if getattr(self, "token", None) else {}

    def get(self, path, **kwargs):
        r = self.session.get(f"{self.base_url}{path}", headers=self._headers(), **kwargs)
        r.raise_for_status()
        return r.json()

    def post(self, path, json_body=None, **kwargs):
        r = self.session.post(f"{self.base_url}{path}", json=json_body, headers=self._headers(), **kwargs)
        if not r.ok:
            raise RuntimeError(f"POST {path} failed ({r.status_code}): {r.text[:500]}")
        return r.json() if r.text else None

    def put(self, path, json_body=None, **kwargs):
        r = self.session.put(f"{self.base_url}{path}", json=json_body, headers=self._headers(), **kwargs)
        if not r.ok:
            raise RuntimeError(f"PUT {path} failed ({r.status_code}): {r.text[:500]}")
        return r.json() if r.text else None

    def delete(self, path, **kwargs):
        r = self.session.delete(f"{self.base_url}{path}", headers=self._headers(), **kwargs)
        r.raise_for_status()

    def wait_until_healthy(self, timeout=180):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = self.session.get(f"{self.base_url}/api/health", timeout=5)
                if r.ok and r.json().get("status") == "ok":
                    return
            except requests.RequestException:
                pass
            time.sleep(2)
        raise RuntimeError(f"Metabase did not become healthy within {timeout}s")

    def authenticate(self):
        """Complete first-run setup (creates the admin) or log in if already set up."""
        props = self.get("/api/session/properties")
        if not props.get("has-user-setup"):
            resp = self.post(
                "/api/setup",
                {
                    "token": props["setup-token"],
                    "user": {
                        "first_name": "Admin",
                        "last_name": "User",
                        "email": MB_ADMIN_EMAIL,
                        "password": MB_ADMIN_PASSWORD,
                    },
                    "prefs": {"site_name": "App Store Product Intelligence", "site_locale": "en"},
                },
            )
            self.token = resp["id"]
        else:
            resp = self.post("/api/session", {"username": MB_ADMIN_EMAIL, "password": MB_ADMIN_PASSWORD})
            self.token = resp["id"]


def get_or_create_database(mb: Metabase) -> int:
    """Return the id of the analytics Postgres connection, creating it if needed."""
    for db in mb.get("/api/database")["data"]:
        if db["name"] == ANALYTICS_DB_NAME:
            return db["id"]

    db = mb.post(
        "/api/database",
        {
            "engine": "postgres",
            "name": ANALYTICS_DB_NAME,
            "details": {
                "host": "postgres",  # docker-compose service name, not localhost
                "port": 5432,
                "dbname": POSTGRES_DB,
                "user": POSTGRES_USER,
                "password": POSTGRES_PASSWORD,
                "ssl": False,
            },
            "is_full_sync": True,
            "auto_run_queries": True,
        },
    )
    return db["id"]


def sync_and_get_fields(mb: Metabase, db_id: int) -> dict:
    """Sync the schema and return {field_name: field_id} for MART_TABLE."""
    mb.post(f"/api/database/{db_id}/sync_schema")
    for _ in range(30):
        meta = mb.get(f"/api/database/{db_id}/metadata")
        table = next((t for t in meta["tables"] if t["name"] == MART_TABLE), None)
        if table is not None:
            return {f["name"]: f["id"] for f in table["fields"]}
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {MART_TABLE} to appear in Metabase's schema sync")


def delete_existing_by_name(mb: Metabase, endpoint: str, name: str) -> None:
    """Delete any existing card/dashboard with this name (both endpoints return a flat list)."""
    for item in mb.get(endpoint):
        if item.get("name") == name:
            mb.delete(f"{endpoint}/{item['id']}")


def dimension_tag(name: str, display_name: str, field_id: int) -> dict:
    return {
        "id": _tag_id(),
        "name": name,
        "display-name": display_name,
        "type": "dimension",
        "dimension": ["field", field_id, None],
        "widget-type": "string/=",
        "default": None,
    }


def number_tag(name: str, display_name: str, default: str) -> dict:
    return {"id": _tag_id(), "name": name, "display-name": display_name, "type": "number", "default": default}


def make_card(mb: Metabase, db_id: int, *, name, description, query, template_tags, display, viz_settings=None):
    delete_existing_by_name(mb, "/api/card", name)
    card = mb.post(
        "/api/card",
        {
            "name": name,
            "description": description,
            "dataset_query": {
                "database": db_id,
                "type": "native",
                "native": {"query": query, "template-tags": template_tags},
            },
            "display": display,
            "visualization_settings": viz_settings or {},
        },
    )
    return card["id"]


def build_cards(mb: Metabase, db_id: int, fields: dict) -> dict:
    """Create every card and return {short_key: card_id}."""
    platform_tag = lambda: dimension_tag("platform", "Platform", fields["platform"])  # noqa: E731
    genre_tag = lambda: dimension_tag("genre", "Category", fields["primary_genre"])  # noqa: E731
    min_rated_tag = lambda: number_tag(  # noqa: E731
        "min_rated_apps", "Minimum Rated Apps", str(MIN_RATED_APPS_DEFAULT)
    )

    ids = {}

    # --- KPI cards: whole-picture totals, respond to Platform/Category but
    # NOT to the reliability threshold — they're meant to show the full
    # truth, including how much of the catalog has no ratings at all.
    kpi_specs = [
        ("kpi_total_apps", "Total Apps", "Total apps in scope, rated or not.",
         "SELECT SUM(app_count) AS total_apps FROM mart_app_category_engagement "
         "WHERE 1=1 [[AND {{platform}}]] [[AND {{genre}}]]"),
        ("kpi_rated_apps", "Rated Apps", "Apps with at least one rating.",
         "SELECT SUM(rated_app_count) AS rated_apps FROM mart_app_category_engagement "
         "WHERE 1=1 [[AND {{platform}}]] [[AND {{genre}}]]"),
        ("kpi_coverage", "Coverage %", "Share of apps that have any ratings at all.",
         "SELECT ROUND(100.0 * SUM(rated_app_count) / NULLIF(SUM(app_count), 0), 1) AS rating_coverage_pct "
         "FROM mart_app_category_engagement WHERE 1=1 [[AND {{platform}}]] [[AND {{genre}}]]"),
        ("kpi_total_ratings", "Total Ratings", "Total ratings submitted, summed across all apps.",
         "SELECT SUM(total_rating_count) AS total_rating_count FROM mart_app_category_engagement "
         "WHERE 1=1 [[AND {{platform}}]] [[AND {{genre}}]]"),
    ]
    for key, name, desc, query in kpi_specs:
        ids[key] = make_card(
            mb, db_id, name=name, description=desc, query=query,
            template_tags={"platform": platform_tag(), "genre": genre_tag()},
            display="scalar",
        )

    # --- Main: Category Engagement scatter/bubble.
    ids["main_scatter"] = make_card(
        mb, db_id,
        name="Category Engagement: Rating vs Volume vs Coverage",
        description=(
            "Each bubble is one App Store category on one platform. X = average rating "
            "(among rated apps only). Y = total rating count (log scale). Bubble size = "
            "rating coverage % (how much of the category is actually rated). Filtered to "
            "categories with at least the minimum rated-app threshold, so tiny, unreliable "
            "samples don't get plotted next to well-established ones."
        ),
        query=(
            "SELECT platform, primary_genre, avg_rating, total_rating_count, "
            "rating_coverage_pct, rated_app_count "
            "FROM mart_app_category_engagement "
            "WHERE rated_app_count >= {{min_rated_apps}} [[AND {{platform}}]] [[AND {{genre}}]] "
            "ORDER BY total_rating_count DESC"
        ),
        template_tags={"min_rated_apps": min_rated_tag(), "platform": platform_tag(), "genre": genre_tag()},
        display="scatter",
        viz_settings={
            "graph.dimensions": ["avg_rating"],
            "graph.metrics": ["total_rating_count"],
            "scatter.bubble": "rating_coverage_pct",
            "graph.y_axis.scale": "log",
            "graph.x_axis.title_text": "Average rating (rated apps only)",
            "graph.y_axis.title_text": "Total rating count (log scale)",
        },
    )

    # --- Secondary: Top categories by rating volume.
    ids["secondary_top"] = make_card(
        mb, db_id,
        name="Top Categories by Rating Volume",
        description="The categories with the most total ratings — a direct measure of engagement scale.",
        query=(
            "SELECT primary_genre || ' (' || platform || ')' AS category, total_rating_count "
            "FROM mart_app_category_engagement "
            "WHERE rated_app_count >= {{min_rated_apps}} [[AND {{platform}}]] [[AND {{genre}}]] "
            "ORDER BY total_rating_count DESC LIMIT 15"
        ),
        template_tags={"min_rated_apps": min_rated_tag(), "platform": platform_tag(), "genre": genre_tag()},
        display="row",
        viz_settings={"graph.dimensions": ["category"], "graph.metrics": ["total_rating_count"]},
    )

    # --- Platform comparison table (deliberately NOT filtered by platform).
    ids["platform_overview"] = make_card(
        mb, db_id,
        name="Platform Overview: iOS vs macOS",
        description=(
            "Both platforms side by side, unfiltered by the reliability threshold — this is "
            "the view that shows the rating-coverage gap between iOS and macOS directly."
        ),
        query=(
            "SELECT platform AS \"Platform\", SUM(app_count) AS \"Apps\", "
            "SUM(rated_app_count) AS \"Rated\", "
            "ROUND(100.0 * SUM(rated_app_count) / NULLIF(SUM(app_count), 0), 2) AS \"Coverage %\", "
            "SUM(total_rating_count) AS \"Total Ratings\" "
            "FROM mart_app_category_engagement WHERE 1=1 [[AND {{genre}}]] "
            "GROUP BY platform ORDER BY platform"
        ),
        template_tags={"genre": genre_tag()},
        display="table",
    )

    return ids


CAVEAT_TEXT = """### ⚠️ Read this before trusting an average rating

**Only 17.5% of apps in this dataset have any ratings at all** — 5,494 out
of 31,408. The other 82.5% show as 0 ratings, not a real "0-star" score;
they're simply excluded from every average here.

**The gap is not evenly spread across platforms.** Only **8 of 22,550**
macOS apps have any ratings — iOS coverage is far higher. See *Platform
Overview* below for the exact numbers.

A category's average rating is only as trustworthy as the number of rated
apps behind it. Use the **Minimum Rated Apps** filter (default: {min_rated}) \
to hide categories too small to draw conclusions from — it already applies \
to the charts below, but not to the KPI cards or Platform Overview, which \
intentionally show the whole, unfiltered picture.""".format(min_rated=MIN_RATED_APPS_DEFAULT)


def build_dashboard(mb: Metabase, card_ids: dict) -> dict:
    delete_existing_by_name(mb, "/api/dashboard", DASHBOARD_NAME)
    dash = mb.post(
        "/api/dashboard",
        {
            "name": DASHBOARD_NAME,
            "description": (
                "Which App Store categories have the strongest engagement/popularity, "
                "and how does that differ between iOS and macOS?"
            ),
        },
    )
    return dash


def assemble_dashboard(mb: Metabase, dash_id: int, card_ids: dict) -> None:
    platform_param_id = _tag_id()
    genre_param_id = _tag_id()
    min_rated_param_id = _tag_id()

    parameters = [
        {"id": platform_param_id, "name": "Platform", "slug": "platform", "type": "string/="},
        {"id": genre_param_id, "name": "Category", "slug": "genre", "type": "string/="},
        {
            "id": min_rated_param_id,
            "name": "Minimum Rated Apps",
            "slug": "min_rated_apps",
            "type": "number/=",
            "default": MIN_RATED_APPS_DEFAULT,
        },
    ]

    def mapping(param_id, card_id, tag_name, dimension: bool):
        target_type = "dimension" if dimension else "variable"
        return {"parameter_id": param_id, "card_id": card_id, "target": [target_type, ["template-tag", tag_name]]}

    dashcards = [
        {
            "id": -1,
            "card_id": None,
            "row": 0, "col": 0, "size_x": 18, "size_y": 4,
            "visualization_settings": {"virtual_card": {"display": "text"}, "text": CAVEAT_TEXT},
        },
        {
            "id": -2, "card_id": card_ids["kpi_total_apps"],
            "row": 4, "col": 0, "size_x": 4, "size_y": 3,
            "parameter_mappings": [
                mapping(platform_param_id, card_ids["kpi_total_apps"], "platform", True),
                mapping(genre_param_id, card_ids["kpi_total_apps"], "genre", True),
            ],
        },
        {
            "id": -3, "card_id": card_ids["kpi_rated_apps"],
            "row": 4, "col": 4, "size_x": 4, "size_y": 3,
            "parameter_mappings": [
                mapping(platform_param_id, card_ids["kpi_rated_apps"], "platform", True),
                mapping(genre_param_id, card_ids["kpi_rated_apps"], "genre", True),
            ],
        },
        {
            "id": -4, "card_id": card_ids["kpi_coverage"],
            "row": 4, "col": 8, "size_x": 4, "size_y": 3,
            "parameter_mappings": [
                mapping(platform_param_id, card_ids["kpi_coverage"], "platform", True),
                mapping(genre_param_id, card_ids["kpi_coverage"], "genre", True),
            ],
        },
        {
            "id": -5, "card_id": card_ids["kpi_total_ratings"],
            "row": 4, "col": 12, "size_x": 4, "size_y": 3,
            "parameter_mappings": [
                mapping(platform_param_id, card_ids["kpi_total_ratings"], "platform", True),
                mapping(genre_param_id, card_ids["kpi_total_ratings"], "genre", True),
            ],
        },
        {
            "id": -6, "card_id": card_ids["main_scatter"],
            "row": 7, "col": 0, "size_x": 18, "size_y": 9,
            "parameter_mappings": [
                mapping(min_rated_param_id, card_ids["main_scatter"], "min_rated_apps", False),
                mapping(platform_param_id, card_ids["main_scatter"], "platform", True),
                mapping(genre_param_id, card_ids["main_scatter"], "genre", True),
            ],
        },
        {
            "id": -7, "card_id": card_ids["secondary_top"],
            "row": 16, "col": 0, "size_x": 9, "size_y": 8,
            "parameter_mappings": [
                mapping(min_rated_param_id, card_ids["secondary_top"], "min_rated_apps", False),
                mapping(platform_param_id, card_ids["secondary_top"], "platform", True),
                mapping(genre_param_id, card_ids["secondary_top"], "genre", True),
            ],
        },
        {
            "id": -8, "card_id": card_ids["platform_overview"],
            "row": 16, "col": 9, "size_x": 9, "size_y": 8,
            "parameter_mappings": [
                mapping(genre_param_id, card_ids["platform_overview"], "genre", True),
            ],
        },
    ]

    mb.put(f"/api/dashboard/{dash_id}", {"parameters": parameters, "dashcards": dashcards})


def main() -> None:
    _check_env()

    mb = Metabase(MB_URL)
    print(f"Waiting for Metabase at {MB_URL} ...")
    mb.wait_until_healthy()

    print("Authenticating ...")
    mb.authenticate()

    print(f"Ensuring '{ANALYTICS_DB_NAME}' database connection ...")
    db_id = get_or_create_database(mb)

    print("Syncing schema and resolving field IDs ...")
    fields = sync_and_get_fields(mb, db_id)

    print("Creating cards ...")
    card_ids = build_cards(mb, db_id, fields)
    for key, cid in card_ids.items():
        print(f"  {key}: card {cid}")

    print(f"Creating dashboard '{DASHBOARD_NAME}' ...")
    dash = build_dashboard(mb, card_ids)
    assemble_dashboard(mb, dash["id"], card_ids)

    print(f"\nDone. Dashboard: {MB_URL}/dashboard/{dash['id']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - top-level script error reporting
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
