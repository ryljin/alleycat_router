import asyncio
import os
import sqlite3
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
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

APP_USER_AGENT = os.getenv(
    "APP_USER_AGENT",
    "alleycat-router-dev/0.1 (replace-with-your-email@example.com)",
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
    if location.lat is not None and location.lon is not None:
        return {
            "query": location.address,
            "display_name": location.address or location.label,
            "lat": location.lat,
            "lon": location.lon,
            "source": "input",
        }

    query = build_query(location, city_hint)

    cached = get_cached_geocode(query)

    if cached:
        cached["query"] = query
        return cached

    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 1,
    }

    headers = {
        "User-Agent": APP_USER_AGENT,
    }

    try:
        response = await client.get(
            NOMINATIM_BASE_URL,
            params=params,
            headers=headers,
            timeout=20,
        )
        response.raise_for_status()
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

    # Public Nominatim policy is strict. Cache makes repeat runs fast.
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
    )


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": APP_NAME,
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