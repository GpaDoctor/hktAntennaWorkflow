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
    Cleans raw AI text output and parses it into a Python dictionary.
    Handles markdown fences, pre/post preamble chatter, and trailing commas.
    """
    json_text = raw_output.strip()
    
    # 1. Strip markdown code fences
    if "```" in json_text:
        json_text = re.sub(r"^```[a-zA-Z]*\n?", "", json_text)
        json_text = re.sub(r"\n?```$", "", json_text).strip()

    # 2. Extract substring between first '{' and last '}'
    start_idx = json_text.find("{")
    end_idx = json_text.rfind("}")
    if start_idx != -1 and end_idx != -1:
        json_text = json_text[start_idx:end_idx + 1]

    # 3. Clean trailing commas before closing brackets/braces (common LLM JSON error)
    json_text = re.sub(r",\s*([\]}])", r"\1", json_text)

    # 4. Parse JSON string
    return json.loads(json_text)



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
    """Deletes files in static folder older than 1 hour (3600 seconds)."""
    now = time.time()
    max_age_seconds = 3600  # 1 hour
    
    print("[SCHEDULER] Running periodic file cleanup...")
    # Matches files starting with floorplan_ or analysis_
    for file_path in STATIC_DIR.glob("*sess_*"):
        if file_path.is_file():
            file_age = now - file_path.stat().st_mtime
            if file_age > max_age_seconds:
                try:
                    file_path.unlink()
                    print(f"[SCHEDULER] Deleted stale file: {file_path.name}")
                except Exception as e:
                    print(f"[SCHEDULER ERROR] Could not delete {file_path.name}: {e}")



LINE_PROMPT_TEXT = """
[C] Context

You are an expert telecom network engineer and indoor navigation
specialist analyzing a residential floorplan image.

The floorplan contains:

- Starting Point / Pink Arrow:
  ID: "{pink_id}"
  Coordinate: xPercent={pink_x}, yPercent={pink_y}

- Target Antenna Markers:
{markers_summary}

- Existing Orange Bend Points:
{bend_points_summary}

- Building elements including walls, lift shafts, staircases,
  residential flats, private units, corridors, and public access areas.

[O] Objective

Generate one continuous cable-routing network from the pink starting
point to every target antenna marker.

Use orange bend points for every route turn and shared junction.

[T] Tone

Precise, technical, and architectural.

[A] Audience

Property management staff, facilities management teams, building
operators, and cabling technicians requiring clear cable-routing
guidance.

[R] Routing and Response Requirements

- Connect the pink starting point to every antenna marker.
- Route lines along the middle of continuous open corridor spaces.
- Keep the entire route within publicly accessible corridors.
- Use only horizontal and vertical connection segments.
- Do not use diagonal or curved connection segments.
- Every connection must represent one straight horizontal or vertical
  segment.
- Represent every 90-degree turn as a separate object in bendPoints.
- Represent every shared branching junction as a bend point.
- A connection endpoint may reference:
  - The pink starting point ID
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
- Ensure every antenna is reachable from the pink starting point.
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
      "fromId": "{pink_id}",
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
#     if "file" not in request.files:
#         return jsonify({"status": "error", "message": "No file uploaded"}), 400
    
#     file = request.files["file"]
#     if file.filename == "":
#         return jsonify({"status": "error", "message": "No selected file"}), 400

#     # Save incoming image as static/rawFloorPlan.png
#     save_path = STATIC_DIR / "rawFloorPlan.png"
#     file.save(save_path)
#     return jsonify({"status": "success", "message": "Floorplan uploaded successfully"})
def upload_floorplan():
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400
    
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"status": "error", "message": "No selected file"}), 400

    # Get a unique session token from the frontend, or generate one
    session_id = request.form.get("session_id", str(uuid.uuid4()))
    
    # Save with a unique filename per session
    filename = f"floorplan_{session_id}.png"
    save_path = STATIC_DIR / filename
    file.save(save_path)

    return jsonify({
        "status": "success", 
        "message": "Floorplan uploaded successfully",
        "session_id": session_id
    })

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
# def analyze_lines():
#     data_json = request.get_json() or {}
#     session_id = data_json.get("session_id")
#     markers = data_json.get("markers", [])
#     pinkarrow = data_json.get("pinkarrow")

#     if not session_id:
#         return jsonify({"status": "error", "message": "Missing session ID"}), 400

#     floorplan_file = STATIC_DIR / f"floorplan_{session_id}.png"
#     if not floorplan_file.exists():
#         return jsonify({"status": "error", "message": "Please upload a floorplan first."}), 404

#     pink_id = pinkarrow.get("id", "pink_arrow_0") if pinkarrow else "pink_arrow_0"
#     pink_x = pinkarrow.get("xPercent", 0) if pinkarrow else 0
#     pink_y = pinkarrow.get("yPercent", 0) if pinkarrow else 0

#     markers_summary = json.dumps([
#         {"id": m["id"], "number": m["number"], "xPercent": round(m["xPercent"], 1), "yPercent": round(m["yPercent"], 1)}
#         for m in markers
#     ], indent=2)

#     formatted_prompt = LINE_PROMPT_TEXT.format(
#         pink_id=pink_id,
#         pink_x=round(pink_x, 1),
#         pink_y=round(pink_y, 1),
#         markers_summary=markers_summary
#     )

#     # use local ai
#     # response = chat(
#     #     model="gemma3",
#     #     messages=[{
#     #         "role": "user",
#     #         "content": formatted_prompt,
#     #         "images": [str(floorplan_file)]
#     #     }]
#     # )

#     # json_text = response["message"]["content"]

#     # use company ai
#     try:
#         json_text = analyze_floorplan_with_bot(
#             prompt_text=formatted_prompt,
#             image_file_path=str(floorplan_file)
#         )
#     except Exception as e:
#         return jsonify({"status": "error", "message": str(e)}), 500
    
#     json_text = json_text.replace("```json", "").replace("```", "").strip()
#     data = json.loads(json_text)

#     return jsonify({"status": "success", "data": data})
# def analyze_lines():
#     data_json = request.get_json() or {}
#     session_id = data_json.get("session_id")
#     markers = data_json.get("markers", [])
#     pinkarrow = data_json.get("pinkarrow")

#     if not session_id:
#         return jsonify({"status": "error", "message": "Missing session ID"}), 400

#     floorplan_file = STATIC_DIR / f"floorplan_{session_id}.png"
#     if not floorplan_file.exists():
#         return jsonify({"status": "error", "message": "Please upload a floorplan first."}), 404

#     pink_id = pinkarrow.get("id", "pink_arrow_0") if pinkarrow else "pink_arrow_0"
#     pink_x = pinkarrow.get("xPercent", 0) if pinkarrow else 0
#     pink_y = pinkarrow.get("yPercent", 0) if pinkarrow else 0

#     markers_summary = json.dumps([
#         {"id": m["id"], "number": m["number"], "xPercent": round(m["xPercent"], 1), "yPercent": round(m["yPercent"], 1)}
#         for m in markers
#     ], indent=2)

#     formatted_prompt = LINE_PROMPT_TEXT.format(
#         pink_id=pink_id,
#         pink_x=round(pink_x, 1),
#         pink_y=round(pink_y, 1),
#         markers_summary=markers_summary
#     )

#     try:
#         json_text = run_ai_analysis(formatted_prompt, str(floorplan_file))
#     except Exception as e:
#         return jsonify({"status": "error", "message": str(e)}), 500
    
#     json_text = json_text.replace("```json", "").replace("```", "").strip()
#     data = json.loads(json_text)

#     return jsonify({"status": "success", "data": data})

@app.route("/api/analyze-lines", methods=["POST"])
# def analyze_lines():
#     data_json = request.get_json() or {}
#     session_id = data_json.get("session_id")
#     markers = data_json.get("markers", [])
#     pinkarrow = data_json.get("pinkarrow")
#     bend_points = data_json.get("bendPoints", [])  # Extract existing bend points

#     if not session_id:
#         return jsonify({"status": "error", "message": "Missing session ID"}), 400

#     floorplan_file = STATIC_DIR / f"floorplan_{session_id}.png"
#     if not floorplan_file.exists():
#         return jsonify({"status": "error", "message": "Please upload a floorplan first."}), 404

#     pink_id = pinkarrow.get("id", "pink_arrow_0") if pinkarrow else "pink_arrow_0"
#     pink_x = pinkarrow.get("xPercent", 0) if pinkarrow else 0
#     pink_y = pinkarrow.get("yPercent", 0) if pinkarrow else 0

#     markers_summary = json.dumps([
#         {"id": m["id"], "number": m["number"], "xPercent": round(m["xPercent"], 1), "yPercent": round(m["yPercent"], 1)}
#         for m in markers
#     ], indent=2)

#     formatted_prompt = LINE_PROMPT_TEXT.format(
#         pink_id=pink_id,
#         pink_x=round(pink_x, 1),
#         pink_y=round(pink_y, 1),
#         markers_summary=markers_summary
#     )

#     try:
#         raw_output = run_ai_analysis(formatted_prompt, str(floorplan_file), model=LINE_ROUTING_MODEL)
#         data = parse_ai_json_response(raw_output)

        
#         raw_connections = data.get("connections", [])

#         clean_connections = []

#         for index, connection in enumerate(raw_connections):
#             if not isinstance(connection, dict):
#                 continue

#             from_id = str(connection.get("fromId", "")).strip()
#             to_id = str(connection.get("toId", "")).strip()

#             if not from_id or not to_id:
#                 continue

#             clean_connections.append({
#                 "id": str(
#                     connection.get("id") or f"conn_{index + 1}"
#                 ),
#                 "fromId": from_id,
#                 "toId": to_id
#             })

#         data["connections"] = clean_connections

#         # Ensure bendPoints array exists in response data
#         if "bendPoints" not in data:
#             data["bendPoints"] = bend_points

#         return jsonify({"status": "success", "data": data})

#     except json.JSONDecodeError as e:
#         print("\n" + "="*60)
#         print("[JSON PARSE ERROR] Raw LLM Output was not valid JSON:")
#         print(raw_output if 'raw_output' in locals() else "No output received")
#         print("="*60 + "\n")
#         return jsonify({
#             "status": "error", 
#             "message": f"AI route output contained invalid JSON syntax: {e.msg} (Line {e.lineno}, Col {e.colno})"
#         }), 500
#     except Exception as e:
#         return jsonify({"status": "error", "message": str(e)}), 500

def analyze_lines():
    try:
        # -----------------------------------------------------
        # 1. Read data sent by index.html
        # -----------------------------------------------------
        data_json = request.get_json(silent=True) or {}

        session_id = data_json.get("session_id")
        markers = data_json.get("markers", [])
        pinkarrow = data_json.get("pinkarrow")
        existing_bend_points = data_json.get("bendPoints", [])

        # -----------------------------------------------------
        # 2. Validate required data
        # -----------------------------------------------------
        if not session_id:
            return jsonify({
                "status": "error",
                "message": "Missing session ID."
            }), 400

        if not pinkarrow or not isinstance(pinkarrow, dict):
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
        # 4. Extract Point 0 information
        # -----------------------------------------------------
        pink_id = pinkarrow.get(
            "id",
            "pink_arrow_0"
        )

        pink_x = round(
            float(pinkarrow.get("xPercent", 0)),
            1
        )

        pink_y = round(
            float(pinkarrow.get("yPercent", 0)),
            1
        )

        # -----------------------------------------------------
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
            pink_id=pink_id,
            pink_x=pink_x,
            pink_y=pink_y,
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
        valid_endpoint_ids = {str(pink_id)}

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
    scheduler.add_job(func=delete_stale_session_files, trigger="interval", minutes=30)
    scheduler.start()
    print("[SCHEDULER] Background file cleanup task started (runs every 30 mins).")

    # Start the Waitress server
    print("Server starting on http://0.0.0.0:5000...")
    serve(app, host="0.0.0.0", port=5000, threads=6)