# Alleycat Router

A FastAPI route optimizer for alleycat-style races.

The app supports two input formats:

1. **Simple JSON** for ordinary unordered checkpoint races.
2. **Mission JSON** for real manifest-style races with hubs, pickups, dropoffs, ordered loops, prerequisites, and repeated visits.

The main web UI is intentionally empty. Paste JSON from Gemini or another parser into the input box.

## Current Features

- Paste JSON into a mobile-friendly web UI.
- Optimize simple checkpoint routes.
- Optimize constrained mission routes.
- Generate a cue sheet.
- Generate split Google Maps route links.
- Support separate mobile and desktop route chunks.
- Copy cue sheet, optimized order, or full JSON.
- Use walking-style routing profiles for alleycat shortcut approximation.
- Use coordinates directly when supplied.
- Fall back to Nominatim geocoding when coordinates are missing.

## Important Google Maps Link Limits

Google Maps route URLs have waypoint limits.

The app uses:

```text
Mobile route chunks: 3 waypoints per link
Desktop route chunks: 9 waypoints per link
````

That means:

```text
Mobile chunk = origin + 3 waypoints + destination = 5 total stops
Desktop chunk = origin + 9 waypoints + destination = 11 total stops
```

The full route link may drop stops if there are too many waypoints. Use the split links if reliability matters.

## Routing Mode

For alleycat-style routing, use:

```json
"foot"
```

or, in mission JSON:

```json
"routing": {
  "cost_profile": "foot",
  "display_mode": "walking"
}
```

This approximates shortcut-heavy urban movement better than car routing.

If the public OSRM server rejects the `foot` profile, temporarily use:

```json
"driving"
```

until a walking-capable routing backend is available.

## Running Locally

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Start the server:

```powershell
python -m uvicorn app:app --reload
```

Open:

```text
http://127.0.0.1:8000/
```

API docs:

```text
http://127.0.0.1:8000/docs
```

Health check:

```text
http://127.0.0.1:8000/health
```

## Required Files

The project root should contain:

```text
app.py
optimizer.py
mission_optimizer.py
requirements.txt
render.yaml
README.md
MISSION_JSON_README.md
.gitignore
```

## requirements.txt

```txt
fastapi
uvicorn[standard]
httpx
pydantic
```

## Environment Variable

Nominatim requires a real identifying User-Agent.

Set:

```text
APP_USER_AGENT = alleycat-router-dev/0.1 your-email@example.com
```

If this is not set and `app.py` still contains `YOUR_EMAIL_HERE`, geocoding will fail.

## Deploying on Render

The included `render.yaml` should look like this:

```yaml
services:
  - type: web
    name: alleycat-router
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: APP_USER_AGENT
        value: alleycat-router-dev/0.1 your-email@example.com
```

Replace:

```text
your-email@example.com
```

with a real contact email.

Push to GitHub:

```powershell
git add .
git commit -m "add mission optimizer"
git push
```

In Render:

1. Create a new Web Service or Blueprint.
2. Connect the GitHub repo.
3. Use the free instance type.
4. Use this start command:

```text
uvicorn app:app --host 0.0.0.0 --port $PORT
```

5. Set the environment variable:

```text
APP_USER_AGENT = alleycat-router-dev/0.1 your-email@example.com
```

After deploy, open:

```text
https://your-service-name.onrender.com/
```

## Render Free Plan Note

Render free services can spin down when inactive. The first request after inactivity may take a while to wake up.

The app is lightweight. The expensive parts are external geocoding/routing calls, not the FastAPI server.

## Simple JSON Format

Use this for basic races where every checkpoint can be visited in any order.

```json
{
  "event_name": "Simple Alleycat",
  "city_hint": "Seattle, WA",
  "profile": "foot",
  "start": {
    "label": "Start",
    "address": "1433 11th Ave, Seattle, WA"
  },
  "checkpoints": [
    {
      "label": "Cap Hill Hub",
      "address": "209 21st Ave E, Seattle, WA"
    },
    {
      "label": "Pike Place Market",
      "address": "Pike Place Market, Seattle, WA"
    }
  ],
  "finish": {
    "label": "Finish",
    "address": "1433 11th Ave, Seattle, WA"
  }
}
```

The backend endpoint is:

```text
POST /optimize
```

The UI automatically uses this endpoint when the JSON does not contain:

```json
"schema_version": "alleycat-mission-v1"
```

## Mission JSON Format

Use Mission JSON for real manifest-style races.

Mission JSON starts with:

```json
{
  "schema_version": "alleycat-mission-v1"
}
```

The backend endpoint is:

```text
POST /optimize_mission
```

The UI automatically uses this endpoint when it sees:

```json
"schema_version": "alleycat-mission-v1"
```

Mission JSON separates physical places from required actions.

Physical places go in:

```json
"locations": {}
```

Required actions/checkoffs go in:

```json
"visits": []
```

Rules go in:

```json
"constraints": []
```

This matters because the same physical place may need to be visited several times.

For full mission schema documentation, see:

```text
MISSION_JSON_README.md
```

## Mission JSON Top-Level Shape

```json
{
  "schema_version": "alleycat-mission-v1",
  "event_name": "Example Alleycat",
  "city_hint": "Seattle, WA",
  "routing": {
    "cost_profile": "foot",
    "display_mode": "walking",
    "notes": "Use walking-style routing costs for alleycat shortcut approximation."
  },
  "start_visit_id": "start_hq",
  "finish_visit_id": "finish_hq",
  "locations": {},
  "visits": [],
  "constraints": []
}
```

## Supported Mission Constraint Types

The mission optimizer supports these constraint types:

```text
precedence
chain
pickup_dropoff
ordered_loop
unlock
group_completion
```

### precedence

One visit must happen before another.

```json
{
  "type": "precedence",
  "before": "cap_hub_arrive",
  "after": "cap_mlk"
}
```

### chain

A list of visits must happen in order.

```json
{
  "type": "chain",
  "id": "cap_mlk_must_return",
  "visit_ids": [
    "cap_mlk",
    "cap_return_after_mlk"
  ],
  "strict_consecutive": true
}
```

When `strict_consecutive` is true, the next visit after `cap_mlk` must be `cap_return_after_mlk`.

### pickup_dropoff

Pickup must happen before dropoff.

```json
{
  "type": "pickup_dropoff",
  "id": "pkg_1",
  "pickup_visit_id": "pickup_1st_university",
  "dropoff_visit_id": "dropoff_700_seneca"
}
```

### ordered_loop

A loop must preserve circular order, but can optionally start anywhere.

```json
{
  "type": "ordered_loop",
  "id": "downtown_loop",
  "visit_ids": [
    "dt_2316_2nd",
    "dt_urban_triangle",
    "dt_700_seneca",
    "dt_100_yesler",
    "dt_1st_university"
  ],
  "can_start_anywhere": true,
  "must_preserve_loop_order": true
}
```

The optimizer tests every valid loop rotation and keeps the cheapest valid route found.

### unlock

A visit unlocks later visits.

```json
{
  "type": "unlock",
  "unlocked_by": "cap_hub_arrive",
  "unlocks": [
    "cap_mlk",
    "cap_15th",
    "cap_bonus_broadway"
  ]
}
```

### group_completion

A completion visit cannot happen until several other visits are done.

```json
{
  "type": "group_completion",
  "id": "cap_bonus_return",
  "required_before": [
    "cap_bonus_broadway",
    "cap_bonus_23rd"
  ],
  "completion_visit_id": "cap_bonus_return_to_hub"
}
```

## Mission Optimizer Behavior

The mission optimizer currently uses:

```text
greedy_precedence_with_loop_rotation
```

That means:

1. Validate the mission JSON.
2. Geocode unique physical locations only.
3. Build a route matrix over physical locations.
4. Compile constraints into prerequisites and strict next-visit rules.
5. Test ordered-loop rotations.
6. At each step, choose the nearest legal next visit.
7. Generate cue sheet and split Google Maps links.

This is not guaranteed to be mathematically perfect for every possible manifest, but it is practical, fast, and supports the real alleycat constraints currently needed.

## Best Input Practice

Coordinates are strongly recommended.

Best:

```json
{
  "label": "Williamsburg Bridge Base",
  "address": "Williamsburg Bridge Pedestrian Path Manhattan Entrance, Delancey Street and Clinton Street, New York, NY",
  "lat": 40.718742,
  "lon": -73.989264
}
```

Avoid vague addresses like:

```json
{
  "address": "Base of Williamsburg Bridge, Manhattan side"
}
```

If coordinates are included, the backend skips geocoding completely.

## Gemini Parser Prompt

Use this with Gemini:

```text
Convert this alleycat manifest into valid JSON using the alleycat-mission-v1 schema.

Return only raw JSON.

Do not use Markdown fences.

Do not include comments.

Use stable lowercase snake_case IDs.

Put physical places in locations.

Put required checkoffs/actions in visits.

Put rules in constraints.

Use "foot" for routing.cost_profile.

Include latitude and longitude whenever possible.

If a place is vague or clue-like, resolve it to the most likely real-world location and include the best full address plus lat/lon.

If a hub must be visited multiple times, create separate visit IDs that point to the same location_id.

If something must happen before something else, add a precedence, chain, unlock, pickup_dropoff, ordered_loop, or group_completion constraint.

For hub out-and-back missions, use unlock from the hub, then a strict consecutive chain from checkpoint to return-to-hub.

Return valid JSON only.
```

## Example Hub Out-and-Back Modeling

For a rule like:

```text
Hub to 413 MLK and back to hub.
```

Use one hub visit, one checkpoint visit, and one return visit.

```json
{
  "id": "cap_hub_arrive",
  "location_id": "cap_hill_hub",
  "label": "Cap Hill Hub",
  "kind": "hub",
  "required": true
}
```

```json
{
  "id": "cap_mlk",
  "location_id": "cap_413_mlk",
  "label": "Cap Hill Mission: 413 MLK Jr Way",
  "kind": "checkpoint",
  "required": true
}
```

```json
{
  "id": "cap_return_after_mlk",
  "location_id": "cap_hill_hub",
  "label": "Return to Cap Hill Hub after 413 MLK",
  "kind": "return",
  "required": true
}
```

Then add:

```json
{
  "type": "unlock",
  "unlocked_by": "cap_hub_arrive",
  "unlocks": [
    "cap_mlk"
  ]
}
```

and:

```json
{
  "type": "chain",
  "id": "cap_mlk_must_return",
  "visit_ids": [
    "cap_mlk",
    "cap_return_after_mlk"
  ],
  "strict_consecutive": true
}
```

Do not make every out-and-back chain start with the hub if several missions share the same hub, because that can create strict-chain conflicts.

## Example Pickup/Dropoff Modeling

For:

```text
Pickup at 1st & University and drop at 700 Seneca.
```

Use:

```json
{
  "id": "pickup_1st_university",
  "location_id": "dt_1st_university",
  "label": "Pickup package at 1st & University",
  "kind": "pickup",
  "required": true
}
```

```json
{
  "id": "dropoff_700_seneca",
  "location_id": "dt_700_seneca",
  "label": "Drop package at 700 Seneca",
  "kind": "dropoff",
  "required": true
}
```

Then add:

```json
{
  "type": "pickup_dropoff",
  "id": "pkg_1",
  "pickup_visit_id": "pickup_1st_university",
  "dropoff_visit_id": "dropoff_700_seneca"
}
```

## Example Ordered Loop Modeling

For:

```text
2316 2nd Ave → Urban Triangle Park → 700 Seneca → 100 Yesler → 1st & University
```

Use:

```json
{
  "type": "ordered_loop",
  "id": "downtown_loop",
  "visit_ids": [
    "dt_2316_2nd",
    "dt_urban_triangle",
    "dt_700_seneca",
    "dt_100_yesler",
    "dt_1st_university"
  ],
  "can_start_anywhere": true,
  "must_preserve_loop_order": true
}
```

## Endpoints

### GET /

Main phone-friendly UI.

```text
/
```

### GET /health

Health check.

```text
/health
```

### POST /optimize

Simple unordered optimizer.

```text
/optimize
```

### POST /validate_mission

Validates mission JSON and compiles constraints.

```text
/validate_mission
```

### POST /optimize_mission

Optimizes constrained mission JSON.

```text
/optimize_mission
```

## Known Limitations

* The mission optimizer is greedy, not globally exact.
* Public Nominatim geocoding is rate-limited.
* Render free instances spin down when inactive.
* Public OSRM routing availability/profile support may vary.
* Google Maps URL links may drop stops if too many waypoints are included.
* Coordinates from Gemini or another geocoder are strongly preferred.

## Future Improvements

* Add exact/OR-Tools constrained optimizer.
* Add CSV/KML export for Google My Maps.
* Add Leaflet/OpenStreetMap in-app map display.
* Add support for optional bonuses with score values.
* Add time-limit optimization.
* Add manual pin correction.
* Add clue-solving confidence display.
* Add route comparison between human and machine order.