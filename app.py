import asyncio
import os
import sqlite3
from typing import Optional
from urllib.parse import quote, urlencode

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from optimizer import calculate_path_cost, solve_open_tsp


APP_NAME = "alleycat-router-dev"
GEOCODE_DB = os.getenv("GEOCODE_DB", "geocode_cache.sqlite3")

NOMINATIM_BASE_URL = os.getenv(
    "NOMINATIM_BASE_URL",
    "https://nominatim.openstreetmap.org/search",
)

OSRM_BASE_URL = os.getenv(
    "OSRM_BASE_URL",
    "https://router.project-osrm.org",
)

DEFAULT_APP_USER_AGENT = "alleycat-router-dev/0.1 monarch102354@gmail.com"

APP_USER_AGENT = os.getenv(
    "APP_USER_AGENT",
    DEFAULT_APP_USER_AGENT,
)

app = FastAPI(title="Alleycat Router")


class LocationInput(BaseModel):
    label: str
    address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


class MatrixRequest(BaseModel):
    event_name: Optional[str] = None

    city_hint: Optional[str] = Field(
        default=None,
        description="Example: Seattle, WA. Added to vague address strings.",
    )

    profile: str = Field(
        default="driving",
        description=(
            "OSRM routing profile. Use driving for the public demo server. "
            "Use bicycle only if your OSRM server supports it."
        ),
    )

    start: LocationInput
    checkpoints: list[LocationInput]
    finish: LocationInput


class ResolvedLocation(BaseModel):
    index: int
    label: str
    query: Optional[str]
    display_name: Optional[str]
    lat: float
    lon: float
    source: str


class MatrixResponse(BaseModel):
    labels: list[str]
    locations: list[ResolvedLocation]
    duration_seconds: list[list[Optional[float]]]
    distance_meters: list[list[Optional[float]]]


class OptimizedLeg(BaseModel):
    from_index: int
    to_index: int
    from_label: str
    to_label: str
    duration_seconds: Optional[float]
    distance_meters: Optional[float]


class FreeMapLinks(BaseModel):
    google_maps_route_url: str
    google_maps_simple_route_url: str


class OptimizeResponse(BaseModel):
    labels: list[str]
    optimized_order_indexes: list[int]
    optimized_order_labels: list[str]
    total_duration_seconds: float
    total_distance_meters: Optional[float]
    method: str
    legs: list[OptimizedLeg]
    locations: list[ResolvedLocation]
    duration_seconds: list[list[Optional[float]]]
    distance_meters: list[list[Optional[float]]]
    free_map_links: FreeMapLinks


def init_db() -> None:
    with sqlite3.connect(GEOCODE_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS geocode_cache (
                query TEXT PRIMARY KEY,
                display_name TEXT,
                lat REAL NOT NULL,
                lon REAL NOT NULL
            )
            """
        )
        conn.commit()


def get_cached_geocode(query: str) -> Optional[dict]:
    with sqlite3.connect(GEOCODE_DB) as conn:
        row = conn.execute(
            """
            SELECT display_name, lat, lon
            FROM geocode_cache
            WHERE query = ?
            """,
            (query,),
        ).fetchone()

    if row is None:
        return None

    display_name, lat, lon = row

    return {
        "display_name": display_name,
        "lat": lat,
        "lon": lon,
        "source": "cache",
    }


def save_geocode(query: str, display_name: str, lat: float, lon: float) -> None:
    with sqlite3.connect(GEOCODE_DB) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO geocode_cache (query, display_name, lat, lon)
            VALUES (?, ?, ?, ?)
            """,
            (query, display_name, lat, lon),
        )
        conn.commit()


def ensure_valid_user_agent() -> None:
    if "YOUR_EMAIL_HERE" in APP_USER_AGENT or "example.com" in APP_USER_AGENT:
        raise HTTPException(
            status_code=500,
            detail=(
                "APP_USER_AGENT is still using a placeholder. "
                "Set APP_USER_AGENT to something like "
                "'alleycat-router-dev/0.1 your-email@domain.com' "
                "or replace DEFAULT_APP_USER_AGENT in app.py."
            ),
        )


def build_query(location: LocationInput, city_hint: Optional[str]) -> str:
    if not location.address:
        raise ValueError(f"Location '{location.label}' needs an address or coordinates.")

    address = location.address.strip()

    if city_hint and city_hint.lower() not in address.lower():
        return f"{address}, {city_hint}"

    return address


async def geocode_location(
    client: httpx.AsyncClient,
    location: LocationInput,
    city_hint: Optional[str],
) -> dict:
    # Fast path: Gemini/AI already provided coordinates.
    # This skips Nominatim entirely.
    if location.lat is not None and location.lon is not None:
        return {
            "query": location.address,
            "display_name": location.address or location.label,
            "lat": location.lat,
            "lon": location.lon,
            "source": "input",
        }

    ensure_valid_user_agent()

    query = build_query(location, city_hint)

    cached = get_cached_geocode(query)

    if cached:
        cached["query"] = query
        return cached

    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 1,
        "addressdetails": 1,
    }

    headers = {
        "User-Agent": APP_USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        response = await client.get(
            NOMINATIM_BASE_URL,
            params=params,
            headers=headers,
            timeout=20,
        )

        if response.status_code == 403:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Nominatim returned 403 Forbidden. "
                    "Set a real APP_USER_AGENT, restart the server, and try again. "
                    "For fastest operation, include lat/lon in the input JSON so geocoding is skipped."
                ),
            )

        response.raise_for_status()

    except HTTPException:
        raise

    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=502,
            detail=f"Geocoding request failed for '{query}': {error}",
        )

    results = response.json()

    if not results:
        raise HTTPException(
            status_code=422,
            detail=f"Could not geocode address: {query}",
        )

    best = results[0]

    display_name = best.get("display_name", query)
    lat = float(best["lat"])
    lon = float(best["lon"])

    save_geocode(query, display_name, lat, lon)

    # Nominatim public usage is rate-limited.
    # The cache makes repeated runs fast.
    await asyncio.sleep(1.1)

    return {
        "query": query,
        "display_name": display_name,
        "lat": lat,
        "lon": lon,
        "source": "nominatim",
    }


async def resolve_locations(payload: MatrixRequest) -> list[ResolvedLocation]:
    raw_locations = [payload.start] + payload.checkpoints + [payload.finish]

    resolved: list[ResolvedLocation] = []

    async with httpx.AsyncClient() as client:
        for index, location in enumerate(raw_locations):
            data = await geocode_location(client, location, payload.city_hint)

            resolved.append(
                ResolvedLocation(
                    index=index,
                    label=location.label,
                    query=data.get("query"),
                    display_name=data.get("display_name"),
                    lat=data["lat"],
                    lon=data["lon"],
                    source=data["source"],
                )
            )

    return resolved


async def fetch_osrm_matrix(
    client: httpx.AsyncClient,
    locations: list[ResolvedLocation],
    profile: str,
) -> dict:
    # OSRM expects longitude,latitude.
    coordinate_string = ";".join(
        f"{location.lon:.7f},{location.lat:.7f}"
        for location in locations
    )

    url = f"{OSRM_BASE_URL}/table/v1/{profile}/{coordinate_string}"

    params = {
        "annotations": "duration,distance",
    }

    try:
        response = await client.get(url, params=params, timeout=30)
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=502,
            detail=f"OSRM matrix request failed: {error}",
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "OSRM matrix request failed",
                "status_code": response.status_code,
                "body": response.text,
            },
        )

    data = response.json()

    if data.get("code") != "Ok":
        raise HTTPException(
            status_code=502,
            detail={
                "message": "OSRM returned a non-Ok response",
                "osrm_response": data,
            },
        )

    return data


def lat_lon(location: ResolvedLocation) -> str:
    # Google Maps expects latitude,longitude.
    return f"{location.lat:.7f},{location.lon:.7f}"


def build_free_map_links(
    locations: list[ResolvedLocation],
    optimized_order: list[int],
) -> FreeMapLinks:
    ordered_locations = [locations[index] for index in optimized_order]

    origin = ordered_locations[0]
    destination = ordered_locations[-1]
    waypoints = ordered_locations[1:-1]

    route_params = {
        "api": "1",
        "origin": lat_lon(origin),
        "destination": lat_lon(destination),
        "travelmode": "bicycling",
    }

    if waypoints:
        route_params["waypoints"] = "|".join(
            lat_lon(location)
            for location in waypoints
        )

    google_maps_route_url = (
        "https://www.google.com/maps/dir/?"
        + urlencode(route_params, safe=",|")
    )

    simple_path = "/".join(
        quote(lat_lon(location), safe=",")
        for location in ordered_locations
    )

    google_maps_simple_route_url = (
        "https://www.google.com/maps/dir/"
        + simple_path
    )

    return FreeMapLinks(
        google_maps_route_url=google_maps_route_url,
        google_maps_simple_route_url=google_maps_simple_route_url,
    )


def build_optimized_response(
    labels: list[str],
    locations: list[ResolvedLocation],
    duration_seconds: list[list[Optional[float]]],
    distance_meters: list[list[Optional[float]]],
) -> OptimizeResponse:
    tsp_result = solve_open_tsp(
        matrix=duration_seconds,
        start_index=0,
        finish_index=len(labels) - 1,
    )

    order = tsp_result["order"]

    total_duration_seconds = tsp_result["cost"]
    total_distance_meters = calculate_path_cost(order, distance_meters)

    legs: list[OptimizedLeg] = []

    for from_index, to_index in zip(order, order[1:]):
        legs.append(
            OptimizedLeg(
                from_index=from_index,
                to_index=to_index,
                from_label=labels[from_index],
                to_label=labels[to_index],
                duration_seconds=duration_seconds[from_index][to_index],
                distance_meters=distance_meters[from_index][to_index],
            )
        )

    return OptimizeResponse(
        labels=labels,
        optimized_order_indexes=order,
        optimized_order_labels=[labels[index] for index in order],
        total_duration_seconds=total_duration_seconds,
        total_distance_meters=total_distance_meters,
        method=tsp_result["method"],
        legs=legs,
        locations=locations,
        duration_seconds=duration_seconds,
        distance_meters=distance_meters,
        free_map_links=build_free_map_links(locations, order),
    )


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Alleycat Router</title>
  <style>
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      padding: 16px;
      background: #111;
      color: #f4f4f4;
    }

    h1 {
      font-size: 24px;
      margin: 0 0 8px;
    }

    p {
      color: #cfcfcf;
      line-height: 1.4;
    }

    textarea {
      width: 100%;
      min-height: 300px;
      box-sizing: border-box;
      border-radius: 10px;
      border: 1px solid #444;
      background: #1c1c1c;
      color: #f4f4f4;
      padding: 12px;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 13px;
    }

    button, a.button {
      display: block;
      width: 100%;
      box-sizing: border-box;
      margin-top: 10px;
      padding: 14px;
      border-radius: 10px;
      border: 0;
      background: #3b82f6;
      color: white;
      font-size: 16px;
      font-weight: 700;
      text-align: center;
      text-decoration: none;
    }

    button.secondary, a.secondary {
      background: #333;
    }

    .card {
      margin-top: 16px;
      padding: 14px;
      border-radius: 12px;
      background: #1a1a1a;
      border: 1px solid #333;
    }

    .error {
      color: #ffb4b4;
      white-space: pre-wrap;
    }

    .muted {
      color: #aaa;
      font-size: 14px;
    }

    ol {
      padding-left: 22px;
    }

    li {
      margin-bottom: 8px;
    }

    pre {
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
      background: #080808;
      border: 1px solid #333;
      padding: 12px;
      border-radius: 10px;
      font-size: 12px;
    }
  </style>
</head>
<body>
  <h1>Alleycat Router</h1>
  <p>Paste address JSON here. Coordinates are fastest. If lat/lon are included, the app skips geocoding.</p>

  <textarea id="inputJson">{
  "event_name": "13 Assassins",
  "city_hint": "New York, NY",
  "profile": "driving",
  "start": {
    "label": "Start",
    "address": "New York Public Library Morningside Heights, 2900 Broadway, New York, NY"
  },
  "checkpoints": [
    {
      "label": "Old Sin City",
      "address": "2520 Park Avenue, Bronx, NY"
    },
    {
      "label": "Base of Williamsburg Bridge",
      "address": "Williamsburg Bridge Pedestrian Path Manhattan Entrance, New York, NY"
    },
    {
      "label": "Flashdancers Gentleman's Club",
      "address": "59 Murray Street, New York, NY"
    },
    {
      "label": "Sapphires",
      "address": "333 East 60th Street, New York, NY"
    },
    {
      "label": "13 W 13th",
      "address": "13 West 13th Street, New York, NY"
    },
    {
      "label": "Hustlers",
      "address": "641 West 51st Street, New York, NY"
    }
  ],
  "finish": {
    "label": "Finish",
    "address": "101 Avenue A, New York, NY"
  }
}</textarea>

  <button onclick="optimizeRoute()">Optimize Route</button>

  <div id="result" class="card" style="display:none;"></div>

  <script>
    let lastResult = null;

    async function optimizeRoute() {
      const resultBox = document.getElementById("result");
      resultBox.style.display = "block";
      resultBox.innerHTML = "<p class='muted'>Optimizing...</p>";

      let payload;

      try {
        payload = JSON.parse(document.getElementById("inputJson").value);
      } catch (err) {
        resultBox.innerHTML = "<p class='error'>Invalid JSON:\\n" + err.message + "</p>";
        return;
      }

      try {
        const response = await fetch("/optimize", {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (!response.ok) {
          resultBox.innerHTML = "<p class='error'>" + escapeHtml(JSON.stringify(data, null, 2)) + "</p>";
          return;
        }

        lastResult = data;
        renderResult(data);
      } catch (err) {
        resultBox.innerHTML = "<p class='error'>Request failed:\\n" + err.message + "</p>";
      }
    }

    function renderResult(data) {
      const resultBox = document.getElementById("result");

      const orderItems = data.optimized_order_labels
        .map(label => "<li>" + escapeHtml(label) + "</li>")
        .join("");

      const miles = data.total_distance_meters / 1609.344;
      const minutes = data.total_duration_seconds / 60;
      const waypointCount = Math.max(0, data.optimized_order_labels.length - 2);

      let mapsWarning = "";

      if (waypointCount > 3) {
        mapsWarning = "<p class='muted'>Google Maps mobile browser links may drop stops above 3 waypoints. This route has " + waypointCount + " waypoints. Use the copied optimized order if Google Maps removes any stops.</p>";
      }

      resultBox.innerHTML = `
        <h2>Optimized Order</h2>
        <ol>${orderItems}</ol>

        <p><strong>Distance:</strong> ${miles.toFixed(2)} miles</p>
        <p><strong>Estimated time:</strong> ${minutes.toFixed(1)} minutes</p>
        <p><strong>Method:</strong> ${escapeHtml(data.method)}</p>

        ${mapsWarning}

        <a class="button" target="_blank" href="${data.free_map_links.google_maps_simple_route_url}">Open Google Maps Route</a>
        <button class="secondary" onclick="copyResultJson()">Copy Full JSON</button>
        <button class="secondary" onclick="copyOptimizedOrder()">Copy Optimized Order</button>

        <h2>Full JSON</h2>
        <pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>
      `;
    }

    async function copyResultJson() {
      if (!lastResult) return;
      await navigator.clipboard.writeText(JSON.stringify(lastResult, null, 2));
      alert("Copied full JSON.");
    }

    async function copyOptimizedOrder() {
      if (!lastResult) return;
      const text = lastResult.optimized_order_labels.join("\\n");
      await navigator.clipboard.writeText(text);
      alert("Copied optimized order.");
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }
  </script>
</body>
</html>
"""


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": APP_NAME,
        "app_user_agent": APP_USER_AGENT,
    }


@app.post("/matrix", response_model=MatrixResponse)
async def create_matrix(payload: MatrixRequest) -> MatrixResponse:
    if len(payload.checkpoints) == 0:
        raise HTTPException(
            status_code=400,
            detail="At least one checkpoint is required.",
        )

    locations = await resolve_locations(payload)

    async with httpx.AsyncClient() as client:
        matrix = await fetch_osrm_matrix(
            client=client,
            locations=locations,
            profile=payload.profile,
        )

    labels = [location.label for location in locations]

    return MatrixResponse(
        labels=labels,
        locations=locations,
        duration_seconds=matrix["durations"],
        distance_meters=matrix["distances"],
    )


@app.post("/optimize", response_model=OptimizeResponse)
async def optimize_route(payload: MatrixRequest) -> OptimizeResponse:
    if len(payload.checkpoints) == 0:
        raise HTTPException(
            status_code=400,
            detail="At least one checkpoint is required.",
        )

    locations = await resolve_locations(payload)

    async with httpx.AsyncClient() as client:
        matrix = await fetch_osrm_matrix(
            client=client,
            locations=locations,
            profile=payload.profile,
        )

    labels = [location.label for location in locations]

    return build_optimized_response(
        labels=labels,
        locations=locations,
        duration_seconds=matrix["durations"],
        distance_meters=matrix["distances"],
    )