import json
import subprocess
import time
import uuid
import re
import os
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

PROMPT_TEXT = """

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
Coverage Radius = 7.5m
Coverage Area = π × 7.5²
              = 3.141592653 × 7.5²
              ≈ 176.71 m²

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
{
  "version": "2.2",
  "routeType": "dottedLine",
  "pinkarrow": {
    "id": "pink_arrow_0",
    "alias": "",
    "xPercent": 0,
    "yPercent": 0,
    "rotation": 90
  },
  "markers": [
    {
      "id": "marker_1",
      "alias": "",
      "number": 1,
      "coordinates": {
        "xPercent": 0,
        "yPercent": 0
      }
    }
  ]
}

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

LINE_PROMPT_TEXT = """
[C] Context
You are an expert telecom network engineer and indoor navigation specialist analyzing a residential floorplan image.
The floorplan contains:
- Starting Point (Point 0 / Pink Arrow): ID "{pink_id}" located at coordinate (x: {pink_x}%, y: {pink_y}%).
- Target Antenna Markers:
{markers_summary}
- Building elements such as walls, lift shafts, staircases, flats/private units, corridors, and other public access areas.

[O] Objective
Generate a SINGLE navigation routes by defining connection paths from the Starting Point ({pink_id}) to all target antenna markers in asscending order.

[T] Tone
Precise, technical, and architectural.

[A] Audience
Property management staff, facilities management teams, building operators, and cabling technicians requiring clear wayfinding guidance.

[R] Routing & Response Requirements
1. Route lines must connect the Starting Point ({pink_id}) to the target antenna markers.
2. Route lines strictly along the middle of continuous open white corridor spaces.
3. Use ONLY orthogonal movements (horizontal and vertical segments with 90-degree turns when changing direction).
4. Keep the route entirely within public corridors.
5. Minimize unnecessary detours while respecting all navigation constraints.
6. Ensure  the final route is continuous, clearly visible.
7. Use the `waypoints` array to specify key (xPercent, yPercent) corner coordinates where 90-degree turns occur along the corridor.

[N] Negative Constraints (CRITICAL)
Do NOT generate routes that:
- Pass through walls or stick to walls
- Cross black wall lines
- Enter lift shafts, lifts, staircases, or stairwells
- Pass through residential flats or private units
- Exit the building footprint or cross building boundaries
- Go behind lifts

Avoid:
- Diagonal line segments or curved paths
- Excessive detours or zigzagging when a simpler route exists
- Sharp angles other than 90-degree turns
- Disconnected route segments or broken route continuity

Do NOT output:
- Markdown prose, introductory text, conversational chatter, or explanations outside the JSON object.

[JSON Output Format]
Return ONLY a valid JSON object strictly adhering to this schema:
{{
  "connections": [
    {{
      "id": "conn_1",
      "fromId": "{pink_id}",
      "toId": "marker_1",
      "waypoints": [
        {{"xPercent": 45.2, "yPercent": 30.1}},
        {{"xPercent": 45.2, "yPercent": 60.5}}
      ]
    }}
  ]
}}
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

    if not session_id:
        return jsonify({"status": "error", "message": "Missing session ID"}), 400

    floorplan_file = STATIC_DIR / f"floorplan_{session_id}.png"
    if not floorplan_file.exists():
        return jsonify({"status": "error", "message": "Please upload a floorplan first for this session."}), 404

    try:
        # Pass DOT_PLACEMENT_MODEL here
        raw_output = run_ai_analysis(PROMPT_TEXT, str(floorplan_file), model=DOT_PLACEMENT_MODEL)
        data = parse_ai_json_response(raw_output)

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

def analyze_lines():
    data_json = request.get_json() or {}
    session_id = data_json.get("session_id")
    markers = data_json.get("markers", [])
    pinkarrow = data_json.get("pinkarrow")

    if not session_id:
        return jsonify({"status": "error", "message": "Missing session ID"}), 400

    floorplan_file = STATIC_DIR / f"floorplan_{session_id}.png"
    if not floorplan_file.exists():
        return jsonify({"status": "error", "message": "Please upload a floorplan first."}), 404

    pink_id = pinkarrow.get("id", "pink_arrow_0") if pinkarrow else "pink_arrow_0"
    pink_x = pinkarrow.get("xPercent", 0) if pinkarrow else 0
    pink_y = pinkarrow.get("yPercent", 0) if pinkarrow else 0

    markers_summary = json.dumps([
        {"id": m["id"], "number": m["number"], "xPercent": round(m["xPercent"], 1), "yPercent": round(m["yPercent"], 1)}
        for m in markers
    ], indent=2)

    formatted_prompt = LINE_PROMPT_TEXT.format(
        pink_id=pink_id,
        pink_x=round(pink_x, 1),
        pink_y=round(pink_y, 1),
        markers_summary=markers_summary
    )

    try:
        # Pass LINE_ROUTING_MODEL here
        raw_output = run_ai_analysis(formatted_prompt, str(floorplan_file), model=LINE_ROUTING_MODEL)
        data = parse_ai_json_response(raw_output)

        return jsonify({"status": "success", "data": data})

    except json.JSONDecodeError as e:
        print("\n" + "="*60)
        print("[JSON PARSE ERROR] Raw LLM Output was not valid JSON:")
        print(raw_output if 'raw_output' in locals() else "No output received")
        print("="*60 + "\n")
        return jsonify({
            "status": "error", 
            "message": f"AI route output contained invalid JSON syntax: {e.msg} (Line {e.lineno}, Col {e.colno})"
        }), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


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