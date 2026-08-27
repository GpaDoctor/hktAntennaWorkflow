import json
import subprocess
import time
import uuid
import re
import os
import math
from apscheduler.schedulers.background import BackgroundScheduler
from waitress import serve
from pathlib import Path
from pdf2image import convert_from_path
from PIL import Image, ImageOps
from flask import Flask, render_template, jsonify, request  # Added request


# =========================================================
# CONFIGURATION FLAG
# Set to True for local Ollama, False for Company API
# =========================================================
USE_LOCAL_AI = False

# Specify different models for each task
DOT_PLACEMENT_MODEL = "gemini-3.1-pro"  # Model for antenna placement
LINE_ROUTING_MODEL = "gpt-5.5"           # Model for drawing path lines

if USE_LOCAL_AI:
    from ollama import chat
    
    # Ensure Ollama model exists
    models = subprocess.run(["ollama", "list"], capture_output=True, text=True).stdout
    if "gemma3" not in models:
        print("Downloading gemma3...")
        subprocess.run(["ollama", "pull", "gemma3"])
else:
    from bot_builder_client import analyze_floorplan_with_bot


app = Flask(__name__)

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)


SESSION_ID_PATTERN = re.compile(
    r"^sess_[A-Za-z0-9_-]{1,100}$"
)


def is_valid_session_id(session_id):
    if not isinstance(session_id, str):
        return False

    return bool(
        SESSION_ID_PATTERN.fullmatch(
            session_id.strip()
        )
    )


def run_ai_analysis(prompt_text: str, image_file_path: str, model: str) -> str:
    """Helper function to route inference requests based on USE_LOCAL_AI flag."""
    if USE_LOCAL_AI:
        response = chat(
            model="gemma3",
            messages=[{
                "role": "user",
                "content": prompt_text,
                "images": [image_file_path]
            }]
        )
        return response["message"]["content"]
    else:
        return analyze_floorplan_with_bot(
            prompt_text=prompt_text,
            image_file_path=image_file_path,
            model=model  # Passes the model choice to bot_builder_client
        )

def parse_ai_json_response(raw_output: str) -> dict:
    """
    Extract and parse one JSON object from an AI response.
    """

    if not isinstance(raw_output, str):
        raise ValueError("AI response must be text.")

    json_text = raw_output.strip()

    if not json_text:
        raise ValueError("AI returned an empty response.")

    # Remove optional Markdown code fences.
    json_text = re.sub(
        r"^\s*```(?:json)?\s*",
        "",
        json_text,
        flags=re.IGNORECASE
    )

    json_text = re.sub(
        r"\s*```\s*$",
        "",
        json_text
    )

    # Extract the outermost JSON object.
    first_brace = json_text.find("{")
    last_brace = json_text.rfind("}")

    if first_brace == -1 or last_brace == -1:
        raise ValueError(
            "AI response did not contain a JSON object."
        )

    json_text = json_text[first_brace:last_brace + 1]

    # Remove trailing commas before } or ].
    json_text = re.sub(
        r",\s*([}\]])",
        r"\1",
        json_text
    )

    data = json.loads(json_text)

    if not isinstance(data, dict):
        raise ValueError(
            "AI response must be a JSON object."
        )

    return data


# # use local ai
# # from ollama import chat

# # use company ai
# # Import the new Bot Builder API client function
# from bot_builder_client import analyze_floorplan_with_bot


# app = Flask(__name__)

# BASE_DIR = Path(__file__).parent
# STATIC_DIR = BASE_DIR / "static"
# STATIC_DIR.mkdir(exist_ok=True)

# # use local ai
# # # Ensure Ollama model exists
# # models = subprocess.run(["ollama", "list"], capture_output=True, text=True).stdout
# # if "gemma3" not in models:
# #     print("Downloading gemma3...")
# #     subprocess.run(["ollama", "pull", "gemma3"])




# =========================================================
# 1. DEFINE THE CLEANUP FUNCTION --- Python daemon thread
# =========================================================
def delete_stale_session_files():
    """
    Delete session files older than one hour.
    """

    now = time.time()
    max_age_seconds = 3600

    print(
        "[SCHEDULER] Running periodic file cleanup...")

    for file_path in STATIC_DIR.glob("*sess_*"):
        try:
            if not file_path.is_file():
                continue

            file_age = (
                now - file_path.stat().st_mtime)

            if file_age <= max_age_seconds:
                continue

            file_path.unlink()

            print(
                "[SCHEDULER] Deleted stale file: "
                f"{file_path.name}"
            )

        except FileNotFoundError:
            # Another request or cleanup process may have
            # already deleted the file.
            continue

        except OSError as error:
            app.logger.exception(
                "[SCHEDULER ERROR] Could not delete stale session file %s: %s",
                file_path.name,
                error
            )


LINE_PROMPT_TEXT = """
[C] Context

You are an expert telecom network engineer and indoor navigation
specialist analyzing a residential floorplan image.

The floorplan contains:

- Starting Points / Pink Arrows:
{starting_points_summary}

- Target Antenna Markers:
{markers_summary}

- Existing Orange Bend Points:
{bend_points_summary}

- Building elements including walls, lift shafts, staircases,
  residential flats, private units, corridors, and public access areas.

[O] Objective

Generate cable-routing networks from the supplied pink starting points to every target antenna marker.

Use orange bend points for every route turn and shared junction.

[T] Tone

Precise, technical, and architectural.

[A] Audience

Property management staff, facilities management teams, building
operators, and cabling technicians requiring clear cable-routing
guidance.

[R] Routing and Response Requirements

- Connect each antenna marker to a suitable supplied pink starting point.
- Use all supplied starting points when practical.
- Route lines along the middle of continuous open corridor spaces.
- Keep the entire route within publicly accessible corridors.
- Use only horizontal and vertical connection segments.
- Do not use diagonal or curved connection segments.
- Every connection must represent one straight horizontal or vertical
  segment.
- Represent every 90-degree turn as a separate object in bendPoints.
- Represent every shared branching junction as a bend point.
- A connection endpoint may reference:
  - Any supplied pink starting point ID
  - An antenna marker ID
  - A bend point ID
- When multiple turns are required, create multiple bend points and
  connect them sequentially.
- When multiple antenna routes share the same junction, reuse the same
  bend point ID.
- Reuse suitable existing orange bend points where possible.
- Create new bend points only when required.
- Give each new bend point a unique ID beginning with "bend_".
- Give each connection a unique ID beginning with "conn_".
- Use supplied pink-arrow, marker, and existing bend-point IDs exactly.
- Minimize unnecessary detours while respecting all routing constraints.
- Ensure every antenna is reachable from at least one supplied pink starting point.
- Do not include a waypoints property in any connection.

[N] Negative Constraints

Do not generate routes that:

- Pass through walls.
- Cross black wall lines.
- Stick unnecessarily to walls.
- Enter lift shafts or lift cars.
- Enter staircases or stairwells.
- Pass through residential flats or private units.
- Pass through structural cores.
- Exit the building footprint.
- Cross building boundaries.
- Go behind lifts.
- Use diagonal segments.
- Use curved segments.
- Contain disconnected route segments.
- Reference nonexistent endpoint IDs.
- Contain duplicate bend-point IDs.
- Contain duplicate connection IDs.
- Contain inline waypoints or blue waypoint handles.

Do not output:

- Markdown
- Explanations
- Comments
- Introductory text
- Conversational text
- Anything outside the JSON object

[JSON Output Format]

Return ONLY one valid JSON object matching this structure:

{{
  "bendPoints": [
    {{
      "id": "bend_1",
      "xPercent": 45.2,
      "yPercent": 30.1
    }},
    {{
      "id": "bend_2",
      "xPercent": 60.0,
      "yPercent": 30.1
    }}
  ],
  "connections": [
    {{
      "id": "conn_1",
      "fromId": "pink_arrow_example",
      "toId": "bend_1"
    }},
    {{
      "id": "conn_2",
      "fromId": "bend_1",
      "toId": "bend_2"
    }},
    {{
      "id": "conn_3",
      "fromId": "bend_2",
      "toId": "marker_1"
    }}
  ]
}}

Important:

- bendPoints must contain all orange route turns and junctions.
- connections must contain only id, fromId, and toId.
- Do not include waypoints.
- Return valid JSON only.
"""


# =========================================================
# 2. YOUR FLASK ROUTES
# =========================================================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/upload", methods=["POST"])

# def upload_floorplan():
#     # Check if file exists in request
#     if "file" not in request.files:
#         return jsonify({
#             "status": "error",
#             "message": "No file uploaded."
#         }), 400

#     uploaded_file = request.files["file"]

#     # Check if a file was selected
#     if not uploaded_file or uploaded_file.filename == "":
#         return jsonify({
#             "status": "error",
#             "message": "No file selected."
#         }), 400

#     # Check session ID
#     session_id = str(request.form.get("session_id", "")).strip()

#     if not session_id:
#         return jsonify({
#             "status": "error",
#             "message": "Missing session ID."
#         }), 400

#     if not is_valid_session_id(session_id):
#         return jsonify({
#             "status": "error",
#             "message": "Invalid session ID."
#         }), 400

#     # Save file
#     # save_path = STATIC_DIR / f"floorplan_{session_id}.png"
#     # uploaded_file.save(save_path)
#     filename = uploaded_file.filename.lower()

#     if filename.endswith(".pdf"):

#         pdf_path = STATIC_DIR / f"floorplan_{session_id}.pdf"
#         uploaded_file.save(pdf_path)

#         # convert pdf -> png
#         image_path = STATIC_DIR / f"floorplan_{session_id}.png"

#         # PDF conversion code goes here
#         # Convert PDF -> PNG
#         pages = convert_from_path(str(pdf_path), dpi=200)

#         if not pages:
#             return jsonify({
#                 "status": "error",
#                 "message": "Unable to read PDF"
#             }), 400

#         pages[0].save(image_path, "PNG")

#     elif filename.endswith((".png", ".jpg", ".jpeg", ".webp")):

#         image_path = STATIC_DIR / f"floorplan_{session_id}.png"
#         uploaded_file.save(image_path)

#     else:

#         return jsonify({
#             "status": "error",
#             "message": "Unsupported uploaded_file type"
#         }), 400

#     return jsonify({
#         "status": "success",
#         "message": "Floorplan uploaded successfully."
#     }), 200
def upload_floorplan():
    if "file" not in request.files:
        return jsonify({
            "status": "error",
            "message": "No file uploaded."
        }), 400

    uploaded_file = request.files["file"]
    session_id = request.form.get("session_id", "")

    if not is_valid_session_id(session_id):
        return jsonify({
            "status": "error",
            "message": "Invalid or missing session ID."
        }), 400

    if not uploaded_file or uploaded_file.filename == "":
        return jsonify({
            "status": "error",
            "message": "No file selected."
        }), 400

    filename = uploaded_file.filename.lower()
    image_path = STATIC_DIR / f"floorplan_{session_id}.png"

    try:
        if filename.endswith(".pdf"):
            pdf_path = STATIC_DIR / f"floorplan_{session_id}.pdf"
            uploaded_file.save(pdf_path)

            pages = convert_from_path(
                str(pdf_path),
                dpi=1200,
                first_page=1,
                last_page=1
            )

            if not pages:
                return jsonify({
                    "status": "error",
                    "message": "Unable to read PDF."
                }), 400

            pages[0].convert("RGB").save(image_path, "PNG")

        elif filename.endswith((".png", ".jpg", ".jpeg", ".webp")):
            # Convert every supported image into a genuine PNG.
            image = Image.open(file.stream)
            image.convert("RGB").save(image_path, "PNG")

        else:
            return jsonify({
                "status": "error",
                "message": "Unsupported file type. Upload PDF, PNG, JPG, JPEG, or WebP."
            }), 400

        return jsonify({
            "status": "success",
            "message": "Floorplan uploaded successfully.",
            "image_url": f"/static/floorplan_{session_id}.png"
        })

    except Exception as error:
        app.logger.exception("Floorplan upload failed")

        return jsonify({
            "status": "error",
            "message": f"Unable to process the uploaded file: {error}"
        }), 500

@app.route("/api/analyze", methods=["POST"])
# def analyze():
#     floorplan_file = STATIC_DIR / "rawFloorPlan.png"
#     if not floorplan_file.exists():
#         return jsonify({"status": "error", "message": "Please upload a floorplan first."}), 404

#     response = chat(
#         model="gemma3",
#         messages=[{
#             "role": "user",
#             "content": PROMPT_TEXT,
#             "images": [str(floorplan_file)]
#         }]
#     )

#     json_text = response["message"]["content"]
#     json_text = json_text.replace("```json", "").replace("```", "").strip()
#     data = json.loads(json_text)

#     output_file = STATIC_DIR / "floorplan_analysis.json"
#     with open(output_file, "w", encoding="utf-8") as f:
#         json.dump(data, f, indent=4, ensure_ascii=False)

#     return jsonify({"status": "success", "data": data})
# def analyze():
#     # Expect the frontend to send the session_id back
#     data_json = request.get_json() or {}
#     session_id = data_json.get("session_id")
    
#     if not session_id:
#         return jsonify({"status": "error", "message": "Missing session ID"}), 400

#     floorplan_file = STATIC_DIR / f"floorplan_{session_id}.png"
#     if not floorplan_file.exists():
#         return jsonify({"status": "error", "message": "Please upload a floorplan first for this session."}), 404

#     # use local ai
#     # Run Ollama analysis on this specific user's file
#     # response = chat(
#     #     model="gemma3",
#     #     messages=[{
#     #         "role": "user",
#     #         "content": PROMPT_TEXT,
#     #         "images": [str(floorplan_file)]
#     #     }]
#     # )

#     # json_text = response["message"]["content"]

#     # use company ai
#     try:
#         json_text = analyze_floorplan_with_bot(
#             prompt_text=PROMPT_TEXT,
#             image_file_path=str(floorplan_file)
#         )
#     except Exception as e:
#         return jsonify({"status": "error", "message": str(e)}), 500


#     json_text = json_text.replace("```json", "").replace("```", "").strip()
#     data = json.loads(json_text)

#     output_file = STATIC_DIR / f"analysis_{session_id}.json"
#     with open(output_file, "w", encoding="utf-8") as f:
#         json.dump(data, f, indent=4, ensure_ascii=False)

#     return jsonify({"status": "success", "data": data})
# def analyze():
#     data_json = request.get_json() or {}
#     session_id = data_json.get("session_id")
    
#     if not session_id:
#         return jsonify({"status": "error", "message": "Missing session ID"}), 400

#     floorplan_file = STATIC_DIR / f"floorplan_{session_id}.png"
#     if not floorplan_file.exists():
#         return jsonify({"status": "error", "message": "Please upload a floorplan first for this session."}), 404

#     try:
#         json_text = run_ai_analysis(PROMPT_TEXT, str(floorplan_file))
#     except Exception as e:
#         return jsonify({"status": "error", "message": str(e)}), 500

#     json_text = json_text.replace("```json", "").replace("```", "").strip()
#     data = json.loads(json_text)

#     output_file = STATIC_DIR / f"analysis_{session_id}.json"
#     with open(output_file, "w", encoding="utf-8") as f:
#         json.dump(data, f, indent=4, ensure_ascii=False)

#     return jsonify({"status": "success", "data": data})

def analyze():
    data_json = request.get_json() or {}
    session_id = data_json.get("session_id")
    site_code = data_json.get("site_code", "").strip().upper()
    floor = str(data_json.get("floor", "")).strip()
    # 1. Extract radius from request (defaulting to 7.5 if missing)
    coverage_radius = float(data_json.get('coverage_radius', 7.5))
    # 2. Calculate Coverage Area dynamically
    coverage_area = math.pi * (coverage_radius ** 2)
    supplied_starting_points = data_json.get("startingPoints", [])
    if not isinstance(supplied_starting_points, list):
        supplied_starting_points = []
    requested_start_count = len(supplied_starting_points) or int(data_json.get("startingPointCount", 1) or 1)
    normalized_supplied_points = []
    for index, point in enumerate(supplied_starting_points):
        if not isinstance(point, dict):
            continue
        normalized_supplied_points.append({
            "id": str(point.get("id") or f"pink_arrow_{index}"),
            "alias": str(point.get("alias") or ""),
            "rotation": point.get("rotation", 0)
        })
    supplied_points_summary = json.dumps(normalized_supplied_points, ensure_ascii=False)

    PROMPT_TEXT = f"""

[C] Context

You are given a residential building floorplan image that contains:

Elevator shafts and lift cars
Lift lobby areas
Corridors and common circulation spaces
Staircases
Service rooms (electrical, mechanical, refuse, etc.)
Residential flats/private units
Structural walls and building cores

A bright green highlighted area is already present on the floorplan and represents the target wireless coverage area.

The purpose of this analysis is wireless network planning and antenna installation.

[O] Objective

Analyze the floorplan and generate a JSON configuration file containing:

One Pink Starting Marker

Place a single pink marker as the starting point.
The preferred placement priority is:
E.M.R.
P.D.
If both exist, choose E.M.R..
If E.M.R. does not exist, choose P.D..
If neither exists, choose the most suitable location nearest to the green coverage area.

Red Coverage Markers

Replace the previous single red marker approach.
Each red marker represents a wireless coverage point.
Coverage area of one red marker:
Coverage Radius = {coverage_radius}m
Coverage Area = π × {coverage_radius}²
              = 3.141592653 × {coverage_radius}²
              ≈ {coverage_area:.2f} m².

Determine the minimum number of red markers required to provide complete coverage of the bright green highlighted area.
Calculate and provide the optimal location of each red marker.
Position markers to maximize coverage efficiency while maintaining full coverage of the target green area.
Number markers sequentially beginning with 1.

Output Format

Do not generate or modify an image.
Output only a JSON file.
[S] Style
Professional engineering and wireless network planning analysis.
Spatially accurate based on floorplan interpretation.
Optimize marker placement to minimize the number of required coverage points.
Preserve all floorplan interpretation accuracy.
Focus solely on coverage planning within the green highlighted area.
[T] Tone

Precise, technical, objective, and engineering-focused.

[A] Audience
AI floorplan analysis systems
Wireless network planning tools
Telecommunications engineers
Facilities management teams
Building operators
[R] Response Requirements
Identify the bright green highlighted area.
Determine the placement of a single pink starting marker.
Use E.M.R. as the highest-priority location.
Use P.D. as the second-priority location.
Calculate the minimum number of red coverage markers required.
Determine the coordinates of each red marker required to cover the entire green area.
Provide coordinates as percentages relative to the full floorplan image dimensions.
Number all red markers sequentially.
Output the result as JSON only.
Do not include explanations, comments, markdown, or additional text outside the JSON.
JSON Schema
{{
    "version": "2.2",
    "routeType": "dottedLine",
    "pinkarrow": {{
        "id": "pink_arrow_0",
        "alias": "",
        "xPercent": 0,
        "yPercent": 0,
        "rotation": 90
    }},
    "markers": [
        {{
            "id": "marker_1",
            "alias": "",
            "number": 1,
            "coordinates": {{
                "xPercent": 0,
                "yPercent": 0
            }}
        }}
    ],
    "bendPoints": []
}}

[N] Constraints / Negative Instructions

Do NOT:

Generate or modify any image.
Return image annotations.
Return SVG, XML, HTML, or markdown.
Place coverage markers outside the green highlighted area unless required for optimal edge coverage.
Place markers inside:
Elevator shafts
Lift cars
Staircases
Residential units
Structural cores
Service rooms not intended for wireless equipment
Create unnecessary coverage overlaps.
Add labels, legends, dimensions, arrows, notes, explanations, or comments.
Output anything other than valid JSON.
Must Not Have
More than one pink starting marker.
Missing marker numbering.
Missing coordinates.
Duplicate marker IDs.
Explanatory text outside the JSON output.
Image output of any kind.
Success Criteria
Pink marker is placed at E.M.R. if available, otherwise P.D..
Entire green highlighted area is covered.
Number of red markers is minimized.
Marker locations are spatially optimized.
Output is valid JSON matching the specified schema.
Coordinates are provided as image-relative percentages (xPercent, yPercent).

MULTIPLE STARTING POINT REQUIREMENT (highest priority):
The user requested exactly {requested_start_count} starting point(s).
Existing starting-point identities are: {supplied_points_summary}
Return exactly {requested_start_count} objects in a "pinkArrows" array.
Preserve supplied IDs, aliases, and rotations, but determine and UPDATE their xPercent and yPercent positions from the image.
Place distinct points at appropriate telecom starting locations in this priority order: E.M.R., P.D./PDS, then other suitable public telecom/electrical/service locations near the coverage area.
Do not place all points at the same location. Do not return fewer points than requested.
The earlier single-starting-point restriction is overridden by this requirement.

"""

    if not session_id:
        return jsonify({"status": "error", "message": "Missing session ID"}), 400

    floorplan_file = STATIC_DIR / f"floorplan_{session_id}.png"
    if not floorplan_file.exists():
        return jsonify({"status": "error", "message": "Please upload a floorplan first for this session."}), 404

    try:
        # Pass DOT_PLACEMENT_MODEL here
        raw_output = run_ai_analysis(PROMPT_TEXT, str(floorplan_file), model=DOT_PLACEMENT_MODEL)
        data = parse_ai_json_response(raw_output)

        raw_connections = data.get("connections", [])

        clean_connections = []

        for index, connection in enumerate(raw_connections):
            if not isinstance(connection, dict):
                continue

            from_id = str(connection.get("fromId", "")).strip()
            to_id = str(connection.get("toId", "")).strip()

            if not from_id or not to_id:
                continue

            clean_connections.append({
                "id": str(
                    connection.get("id") or f"conn_{index + 1}"
                ),
                "fromId": from_id,
                "toId": to_id
            })

        data["connections"] = clean_connections

        ai_points = data.get("pinkArrows")
        if not isinstance(ai_points, list):
            legacy_point = data.get("pinkarrow") or data.get("greenArrow")
            ai_points = [legacy_point] if isinstance(legacy_point, dict) else []
        positioned_points = []
        for index in range(requested_start_count):
            source = ai_points[index] if index < len(ai_points) and isinstance(ai_points[index], dict) else {}
            identity = normalized_supplied_points[index] if index < len(normalized_supplied_points) else {
                "id": f"pink_arrow_{index}", "alias": "", "rotation": 90
            }
            try:
                x_value = max(0.0, min(100.0, float(source.get("xPercent"))))
                y_value = max(0.0, min(100.0, float(source.get("yPercent"))))
            except (TypeError, ValueError):
                # Keep a usable fallback only if the model omitted a requested point.
                original = supplied_starting_points[index] if index < len(supplied_starting_points) else {}
                x_value = float(original.get("xPercent", 42 + index * 4))
                y_value = float(original.get("yPercent", 50))
            positioned_points.append({
                "id": identity["id"],
                "alias": identity.get("alias", ""),
                "xPercent": x_value,
                "yPercent": y_value,
                "rotation": identity.get("rotation", 90)
            })
        data["pinkArrows"] = positioned_points
        data["pinkarrow"] = positioned_points[0] if positioned_points else None

        # Attach formatted alias (e.g., MA5-01) to each generated marker
        if site_code and floor and "markers" in data and isinstance(data["markers"], list):
            for index, marker in enumerate(data["markers"]):
                antenna_num = f"{index + 1:02d}"  # Formats 1 -> "01", 2 -> "02"
                marker["alias"] = f"{site_code}{floor}-{antenna_num}"

        output_file = STATIC_DIR / f"analysis_{session_id}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        return jsonify({"status": "success", "data": data})

    except json.JSONDecodeError as e:
        print("\n" + "="*60)
        print("[JSON PARSE ERROR] Raw LLM Output was not valid JSON:")
        print(raw_output if 'raw_output' in locals() else "No output received")
        print("="*60 + "\n")
        return jsonify({
            "status": "error", 
            "message": f"AI output contained invalid JSON syntax: {e.msg} (Line {e.lineno}, Col {e.colno})"
        }), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500




@app.route("/api/analyze-lines", methods=["POST"])
def analyze_lines():
    try:
        # -----------------------------------------------------
        # 1. Read data sent by index.html
        # -----------------------------------------------------
        data_json = request.get_json(silent=True) or {}

        session_id = data_json.get("session_id")
        markers = data_json.get("markers", [])
        starting_points = data_json.get("startingPoints", [])
        if not isinstance(starting_points, list):
            legacy = data_json.get("pinkarrow")
            starting_points = [legacy] if isinstance(legacy, dict) else []
        existing_bend_points = data_json.get("bendPoints", [])

        # -----------------------------------------------------
        # 2. Validate required data
        # -----------------------------------------------------
        if not session_id:
            return jsonify({
                "status": "error",
                "message": "Missing session ID."
            }), 400

        if not starting_points:
            return jsonify({
                "status": "error",
                "message": (
                    "Missing starting point. "
                    "Please add Point 0 before generating lines."
                )
            }), 400

        if not isinstance(markers, list) or len(markers) == 0:
            return jsonify({
                "status": "error",
                "message": (
                    "No antenna markers were supplied. "
                    "Please add or generate antenna markers first."
                )
            }), 400

        if not isinstance(existing_bend_points, list):
            existing_bend_points = []

        # -----------------------------------------------------
        # 3. Find this browser session's floorplan
        # -----------------------------------------------------
        floorplan_file = (
            STATIC_DIR / f"floorplan_{session_id}.png"
        )

        if not floorplan_file.exists():
            return jsonify({
                "status": "error",
                "message": (
                    "Please upload a floorplan first "
                    "for this session."
                )
            }), 404

        # -----------------------------------------------------
        # 4. Normalize all starting points
        normalized_starting_points = []
        for index, point in enumerate(starting_points):
            if not isinstance(point, dict):
                continue
            try:
                normalized_starting_points.append({
                    "id": str(point.get("id") or f"pink_arrow_{index}"),
                    "xPercent": round(float(point.get("xPercent")), 1),
                    "yPercent": round(float(point.get("yPercent")), 1)
                })
            except (TypeError, ValueError):
                continue
        if not normalized_starting_points:
            return jsonify({"status": "error", "message": "No valid starting-point coordinates were supplied."}), 400
        starting_points_summary = json.dumps(normalized_starting_points, indent=2, ensure_ascii=False)

        # 5. Prepare antenna-marker information
        # -----------------------------------------------------
        normalized_markers = []

        for index, marker in enumerate(markers):
            if not isinstance(marker, dict):
                continue

            marker_id = marker.get("id")

            if not marker_id:
                continue

            try:
                marker_x = round(
                    float(marker.get("xPercent", 0)),
                    1
                )

                marker_y = round(
                    float(marker.get("yPercent", 0)),
                    1
                )
            except (TypeError, ValueError):
                continue

            normalized_markers.append({
                "id": marker_id,
                "number": marker.get(
                    "number",
                    index + 1
                ),
                "xPercent": marker_x,
                "yPercent": marker_y
            })

        if not normalized_markers:
            return jsonify({
                "status": "error",
                "message": (
                    "No valid antenna marker coordinates "
                    "were supplied."
                )
            }), 400

        markers_summary = json.dumps(
            normalized_markers,
            indent=2,
            ensure_ascii=False
        )

        # -----------------------------------------------------
        # 6. Prepare existing orange bend points
        # -----------------------------------------------------
        normalized_existing_bends = []

        for bend in existing_bend_points:
            if not isinstance(bend, dict):
                continue

            bend_id = bend.get("id")

            if not bend_id:
                continue

            try:
                bend_x = round(
                    float(bend.get("xPercent", 0)),
                    1
                )

                bend_y = round(
                    float(bend.get("yPercent", 0)),
                    1
                )
            except (TypeError, ValueError):
                continue

            normalized_existing_bends.append({
                "id": bend_id,
                "xPercent": bend_x,
                "yPercent": bend_y
            })

        bend_points_summary = json.dumps(
            normalized_existing_bends,
            indent=2,
            ensure_ascii=False
        )

        # -----------------------------------------------------
        # 7. Insert current coordinates into LINE_PROMPT_TEXT
        # -----------------------------------------------------
        formatted_prompt = LINE_PROMPT_TEXT.format(
            starting_points_summary=starting_points_summary,
            markers_summary=markers_summary,
            bend_points_summary=bend_points_summary
        )

        # -----------------------------------------------------
        # 8. Run the line-routing AI
        # -----------------------------------------------------
        raw_output = run_ai_analysis(
            formatted_prompt,
            str(floorplan_file),
            model=LINE_ROUTING_MODEL
        )

        # -----------------------------------------------------
        # 9. Parse the AI JSON response
        # -----------------------------------------------------
        data = parse_ai_json_response(raw_output)

        if not isinstance(data, dict):
            raise ValueError(
                "The line-routing AI did not return "
                "a valid JSON object."
            )

        raw_bend_points = data.get(
            "bendPoints",
            []
        )

        raw_connections = data.get(
            "connections",
            []
        )

        if not isinstance(raw_bend_points, list):
            raw_bend_points = []

        if not isinstance(raw_connections, list):
            raw_connections = []

        # -----------------------------------------------------
        # 10. Clean returned orange bend points
        # -----------------------------------------------------
        clean_bend_points = []
        bend_ids = set()

        for index, bend in enumerate(raw_bend_points):
            if not isinstance(bend, dict):
                continue

            bend_id = bend.get("id")

            if not bend_id:
                bend_id = f"bend_{index + 1}"

            bend_id = str(bend_id).strip()

            if not bend_id:
                continue

            # Prevent duplicate bend IDs.
            if bend_id in bend_ids:
                continue

            try:
                x_percent = round(
                    float(bend.get("xPercent")),
                    1
                )

                y_percent = round(
                    float(bend.get("yPercent")),
                    1
                )
            except (TypeError, ValueError):
                continue

            # Keep coordinates inside the image.
            x_percent = max(
                0.0,
                min(100.0, x_percent)
            )

            y_percent = max(
                0.0,
                min(100.0, y_percent)
            )

            clean_bend_points.append({
                "id": bend_id,
                "xPercent": x_percent,
                "yPercent": y_percent
            })

            bend_ids.add(bend_id)

        # -----------------------------------------------------
        # 11. Build the set of valid connection endpoints
        # -----------------------------------------------------
        valid_endpoint_ids = {str(point["id"]) for point in normalized_starting_points}

        for marker in normalized_markers:
            valid_endpoint_ids.add(
                str(marker["id"])
            )

        for bend_id in bend_ids:
            valid_endpoint_ids.add(
                str(bend_id)
            )

        # -----------------------------------------------------
        # 12. Clean returned connections
        # -----------------------------------------------------
        clean_connections = []
        connection_ids = set()
        connected_pairs = set()

        for index, connection in enumerate(
            raw_connections
        ):
            if not isinstance(connection, dict):
                continue

            connection_id = connection.get("id")

            if not connection_id:
                connection_id = (
                    f"conn_{index + 1}"
                )

            connection_id = str(
                connection_id
            ).strip()

            from_id = str(
                connection.get("fromId", "")
            ).strip()

            to_id = str(
                connection.get("toId", "")
            ).strip()

            # Both endpoints must be present.
            if not from_id or not to_id:
                continue

            # A point cannot connect to itself.
            if from_id == to_id:
                continue

            # Both endpoints must exist.
            if from_id not in valid_endpoint_ids:
                continue

            if to_id not in valid_endpoint_ids:
                continue

            # Prevent duplicate connection IDs.
            if connection_id in connection_ids:
                connection_id = (
                    f"conn_{len(clean_connections) + 1}"
                )

            # Prevent duplicate lines in either direction.
            connection_pair = tuple(
                sorted([from_id, to_id])
            )

            if connection_pair in connected_pairs:
                continue

            # Orange-only connection structure.
            #
            # We deliberately create a new dictionary containing
            # only id, fromId and toId. If the AI returns the old
            # "waypoints" property, it is discarded here.
            clean_connections.append({
                "id": connection_id,
                "fromId": from_id,
                "toId": to_id
            })

            connection_ids.add(connection_id)
            connected_pairs.add(connection_pair)

        if not clean_connections:
            return jsonify({
                "status": "error",
                "message": (
                    "The AI did not return any valid "
                    "line connections."
                )
            }), 422

        # -----------------------------------------------------
        # 13. Return orange-only routing data
        # -----------------------------------------------------
        return jsonify({
            "status": "success",
            "data": {
                "bendPoints": clean_bend_points,
                "connections": clean_connections
            }
        })

    except json.JSONDecodeError as error:
        return jsonify({
            "status": "error",
            "message": (
                "The line-routing AI returned invalid JSON: "
                f"{error}"
            )
        }), 502

    except (TypeError, ValueError) as error:
        return jsonify({
            "status": "error",
            "message": str(error)
        }), 400

    except Exception as error:
        app.logger.exception(
            "Line-routing analysis failed."
        )

        return jsonify({
            "status": "error",
            "message": (
                "Line-routing analysis failed: "
                f"{error}"
            )
        }), 500

@app.route("/api/cleanup", methods=["POST"])
def cleanup_session():
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id") or request.form.get("session_id")

    if not session_id:
        return jsonify({"status": "error", "message": "Missing session_id"}), 400

    # Pattern match files for this session (e.g., floorplan_sess123.png, analysis_sess123.json)
    deleted_files = 0
    for file_path in STATIC_DIR.glob(f"*{session_id}*"):
        try:
            if file_path.is_file():
                file_path.unlink()
                deleted_files += 1
        except Exception as e:
            print(f"[CLEANUP ERROR] Failed to delete {file_path}: {e}")

    print(f"[CLEANUP] Purged {deleted_files} files for session: {session_id}")
    return jsonify({"status": "success", "deleted": deleted_files})

# if __name__ == "__main__":
#     app.run(host="127.0.0.1", port=8000, debug=True)
if __name__ == "__main__":
    # Start the background cleanup scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=delete_stale_session_files, trigger="interval", 
                    #   seconds=60
                      minutes=30
                      )
    scheduler.start()
    print("[SCHEDULER] Background file cleanup task started (runs every 30 mins).")

    # Start the Waitress server
    print("Server starting on http://0.0.0.0:5000...")
    try:
        serve(app, host="0.0.0.0", port=5000, threads=6)
    finally:
        scheduler.shutdown()