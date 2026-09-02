import heapq
import json
import math
import cv2
import numpy as np


def is_valid(x, y, grid):
    """Check if pixel is within image bounds and on a white/walkable region (>50 gray value)."""
    h, w = grid.shape
    if 0 <= x < w and 0 <= y < h:
        return grid[y, x] > 50
    return False


def is_diagonal_clear(cx, cy, nx, ny, grid):
    """Prevents cutting corners across black obstacles when moving diagonally."""
    dx = nx - cx
    dy = ny - cy
    if dx != 0 and dy != 0:
        # Check both adjacent orthogonal pixels to ensure no corner clipping
        if not is_valid(cx + dx, cy, grid) or not is_valid(cx, cy + dy, grid):
            return False
    return True


def astar_grid_path_8dir(start_px, target_px, grid):
    """Finds the shortest path through white regions allowing diagonal (8-directional) movements."""
    sx, sy = start_px
    tx, ty = target_px

    open_set = [(0, 0, sx, sy, 0, 0)]
    came_from = {}
    g_score = {(sx, sy): 0}

    # 8-directional movement (Orthogonal + Diagonal)
    directions = [
        (0, 1),
        (1, 0),
        (0, -1),
        (-1, 0),  # Orthogonal
        (1, 1),
        (1, -1),
        (-1, 1),
        (-1, -1),  # Diagonal
    ]

    SQRT_2 = math.sqrt(2)

    while open_set:
        _, current_g, cx, cy, dx, dy = heapq.heappop(open_set)

        if (cx, cy) == (tx, ty):
            path = []
            curr = (tx, ty)
            while curr in came_from:
                path.append(curr)
                curr = came_from[curr]
            path.append((sx, sy))
            return path[::-1]

        for ndx, ndy in directions:
            nx, ny = cx + ndx, cy + ndy

            if not is_valid(nx, ny, grid):
                continue

            if not is_diagonal_clear(cx, cy, nx, ny, grid):
                continue

            step_cost = SQRT_2 if (ndx != 0 and ndy != 0) else 1.0
            turn_penalty = (
                0
                if (dx == 0 and dy == 0) or (dx == ndx and dy == ndy)
                else 0.5
            )
            tentative_g = current_g + step_cost + turn_penalty

            if (nx, ny) not in g_score or tentative_g < g_score[(nx, ny)]:
                g_score[(nx, ny)] = tentative_g
                # Octile distance heuristic for 8-directional grids
                dx_h = abs(nx - tx)
                dy_h = abs(ny - ty)
                h_score = max(dx_h, dy_h) + (SQRT_2 - 1) * min(dx_h, dy_h)
                f_score = tentative_g + h_score

                came_from[(nx, ny)] = (cx, cy)
                heapq.heappush(
                    open_set, (f_score, tentative_g, nx, ny, ndx, ndy)
                )

    return None


def extract_bend_points(px_path, w, h):
    """Identifies trajectory changes (turns) along the 8-directional pixel path."""
    if len(px_path) < 3:
        return []

    simplified_pct = []
    for i in range(1, len(px_path) - 1):
        prev_x, prev_y = px_path[i - 1]
        curr_x, curr_y = px_path[i]
        next_x, next_y = px_path[i + 1]

        dx1, dy1 = curr_x - prev_x, curr_y - prev_y
        dx2, dy2 = next_x - curr_x, next_y - curr_y

        if (dx1, dy1) != (dx2, dy2):
            pct_x = round((curr_x / float(w - 1)) * 100, 2)
            pct_y = round((curr_y / float(h - 1)) * 100, 2)
            simplified_pct.append((pct_x, pct_y))

    return simplified_pct


def process_routing_and_render(
    image_path, input_json_data, output_image_path="output.png"
):
    grid = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if grid is None:
        raise FileNotFoundError(f"Cannot load image: {image_path}")

    h, w = grid.shape

    def pct_to_px(pct_x, pct_y):
        return int(round((pct_x / 100.0) * (w - 1))), int(
            round((pct_y / 100.0) * (h - 1))
        )

    starts = input_json_data.get("pinkArrows", [])
    markers = input_json_data.get("markers", [])

    bend_points = []
    connections = []
    bend_counter = 1
    conn_counter = 1

    connected_nodes = []
    for s in starts:
        connected_nodes.append(
            {
                "id": str(s["id"]),
                "px": pct_to_px(s["xPercent"], s["yPercent"]),
            }
        )

    for m in markers:
        m_id = str(m["id"])
        m_px = pct_to_px(
            m["coordinates"]["xPercent"], m["coordinates"]["yPercent"]
        )

        best_target = min(
            connected_nodes,
            key=lambda n: math.hypot(n["px"][0] - m_px[0], n["px"][1] - m_px[1]),
        )

        path_px = astar_grid_path_8dir(best_target["px"], m_px, grid)

        if path_px:
            bends = extract_bend_points(path_px, w, h)
            last_node_id = best_target["id"]

            for b_x, b_y in bends:
                bend_id = f"bend_{bend_counter}"
                bend_counter += 1

                bend_points.append(
                    {"id": bend_id, "xPercent": b_x, "yPercent": b_y}
                )

                connections.append(
                    {
                        "id": f"conn_{conn_counter}",
                        "fromId": last_node_id,
                        "toId": bend_id,
                    }
                )
                conn_counter += 1
                last_node_id = bend_id

            connections.append(
                {
                    "id": f"conn_{conn_counter}",
                    "fromId": last_node_id,
                    "toId": m_id,
                }
            )
            conn_counter += 1
            connected_nodes.append({"id": m_id, "px": m_px})

    # Produce JSON matching the exact input structure
    output_json = dict(input_json_data)
    output_json["bendPoints"] = bend_points
    output_json["connections"] = connections

    # Render debug visualization
    debug_img = cv2.cvtColor(grid, cv2.COLOR_GRAY2BGR)
    all_px = {}

    for s in starts:
        px, py = pct_to_px(s["xPercent"], s["yPercent"])
        all_px[str(s["id"])] = (px, py)
        cv2.circle(debug_img, (px, py), 8, (0, 255, 0), -1)

    for m in markers:
        px, py = pct_to_px(
            m["coordinates"]["xPercent"], m["coordinates"]["yPercent"]
        )
        all_px[str(m["id"])] = (px, py)
        cv2.circle(debug_img, (px, py), 6, (0, 0, 255), -1)

    for b in bend_points:
        px, py = pct_to_px(b["xPercent"], b["yPercent"])
        all_px[str(b["id"])] = (px, py)
        cv2.circle(debug_img, (px, py), 4, (0, 165, 255), -1)

    for c in connections:
        f_id, t_id = str(c["fromId"]), str(c["toId"])
        if f_id in all_px and t_id in all_px:
            cv2.line(debug_img, all_px[f_id], all_px[t_id], (255, 100, 0), 2)

    cv2.imwrite(output_image_path, debug_img)
    return output_json


def run_algorithmic_routing(image_path, starting_points, markers):
    """Return app-compatible A* bend points and connections."""
    grid = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if grid is None:
        raise FileNotFoundError(f"Cannot load routing image: {image_path}")

    height, width = grid.shape

    def percent_to_pixel(x_percent, y_percent):
        return (
            int(round(float(x_percent) / 100.0 * (width - 1))),
            int(round(float(y_percent) / 100.0 * (height - 1))),
        )

    connected_nodes = [
        {
            "id": str(point["id"]),
            "px": percent_to_pixel(point["xPercent"], point["yPercent"]),
        }
        for point in starting_points
    ]
    if not connected_nodes:
        raise ValueError("At least one valid starting point is required.")

    bend_points = []
    connections = []
    unroutable_markers = []
    bend_counter = 1
    connection_counter = 1

    for marker in markers:
        marker_id = str(marker["id"])
        marker_px = percent_to_pixel(marker["xPercent"], marker["yPercent"])
        best_target = min(
            connected_nodes,
            key=lambda node: math.hypot(
                node["px"][0] - marker_px[0],
                node["px"][1] - marker_px[1],
            ),
        )
        path_px = astar_grid_path_8dir(best_target["px"], marker_px, grid)
        if not path_px:
            unroutable_markers.append(marker_id)
            continue

        previous_node_id = best_target["id"]
        for bend_x, bend_y in extract_bend_points(path_px, width, height):
            bend_id = f"bend_{bend_counter}"
            bend_counter += 1
            bend_points.append({
                "id": bend_id,
                "xPercent": bend_x,
                "yPercent": bend_y,
            })
            connections.append({
                "id": f"conn_{connection_counter}",
                "fromId": previous_node_id,
                "toId": bend_id,
            })
            connection_counter += 1
            previous_node_id = bend_id

        connections.append({
            "id": f"conn_{connection_counter}",
            "fromId": previous_node_id,
            "toId": marker_id,
        })
        connection_counter += 1
        connected_nodes.append({"id": marker_id, "px": marker_px})

    return {
        "bendPoints": bend_points,
        "connections": connections,
        "unroutableMarkers": unroutable_markers,
    }


if __name__ == "__main__":
    with open("input.json", "r") as f:
        input_data = json.load(f)

    result_json = process_routing_and_render(
        "floorplan.png", input_data, "output.png"
    )

    with open("output.json", "w") as f:
        json.dump(result_json, f, indent=2)