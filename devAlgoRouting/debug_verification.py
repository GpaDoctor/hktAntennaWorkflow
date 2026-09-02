import cv2
import json
import numpy as np


def verify_alignment(image_path, input_json_data, output_routing_json=None):
    """
    Draws points and routing information on top of a floorplan image.
    """

    # Load floorplan image
    grid = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)

    if grid is None:
        raise FileNotFoundError(f"Cannot load image: {image_path}")

    h, w = grid.shape[:2]
    print(f"[INFO] Loaded image dimensions: Width={w}px, Height={h}px")

    # Convert grayscale image to color for annotations
    debug_img = cv2.cvtColor(grid, cv2.COLOR_GRAY2BGR)

    def pct_to_px(pct_x, pct_y):
        """
        Convert percentage coordinates (0-100)
        into image pixel coordinates.
        """
        px = int(round((pct_x / 100.0) * (w - 1)))
        py = int(round((pct_y / 100.0) * (h - 1)))
        return px, py

    point_pixels = {}

    # Draw starting points
    for start in input_json_data.get("pinkArrows", []):
        sid = str(start["id"])

        px, py = pct_to_px(
            start["xPercent"],
            start["yPercent"]
        )

        point_pixels[sid] = (px, py)

        cv2.circle(
            debug_img,
            (px, py),
            8,
            (0, 255, 0),
            -1
        )

        cv2.putText(
            debug_img,
            f"START:{sid}",
            (px + 10, py - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            2
        )

    # Draw markers
    for marker in input_json_data.get("markers", []):
        mid = str(marker["id"])

        coords = marker["coordinates"]

        print(
            marker["alias"],
            coords["xPercent"],
            coords["yPercent"]
        )

        px, py = pct_to_px(
            coords["xPercent"],
            coords["yPercent"]
        )

        point_pixels[mid] = (px, py)

        cv2.circle(
            debug_img,
            (px, py),
            6,
            (0, 0, 255),
            -1
        )

        cv2.putText(
            debug_img,
            f"M:{mid}",
            (px + 8, py + 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (0, 0, 255),
            1
        )

    # Draw routing info if supplied
    if output_routing_json:

        routing_data = output_routing_json.get("data", {})

        # Bend points
        for bend in routing_data.get("bendPoints", []):
            bid = str(bend["id"])

            px, py = pct_to_px(
                bend["xPercent"],
                bend["yPercent"]
            )

            point_pixels[bid] = (px, py)

            cv2.circle(
                debug_img,
                (px, py),
                4,
                (0, 165, 255),
                -1
            )

        # Connections
        for conn in routing_data.get("connections", []):

            from_id = str(conn["fromId"])
            to_id = str(conn["toId"])

            if from_id in point_pixels and to_id in point_pixels:

                cv2.line(
                    debug_img,
                    point_pixels[from_id],
                    point_pixels[to_id],
                    (255, 100, 0),
                    2
                )

    output_file = "debug_verification.png"

    cv2.imwrite(output_file, debug_img)

    print(f"[SUCCESS] Saved debug image to '{output_file}'")


if __name__ == "__main__":

    FLOORPLAN_IMAGE = "floorplan.png"
    INPUT_JSON = "input.json"

    # Load input JSON
    with open(INPUT_JSON, "r") as f:
        input_json = json.load(f)

    # Optional routing output
    ROUTING_JSON = "routing_output.json"

    try:
        with open(ROUTING_JSON, "r") as f:
            routing_json = json.load(f)
    except FileNotFoundError:
        routing_json = None
        print("[INFO] No routing_output.json found. Drawing only markers.")

    verify_alignment(
        image_path=FLOORPLAN_IMAGE,
        input_json_data=input_json,
        output_routing_json=routing_json
    )