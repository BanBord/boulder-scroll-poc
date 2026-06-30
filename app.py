import os
import uuid
import threading
import json

from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)

_jobs: dict = {}
_lock = threading.Lock()

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "output"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


@app.route("/")
def index():
    return send_from_directory("viewer", "index.html")


@app.route("/output/<path:filename>")
def serve_output(filename):
    return send_from_directory(OUTPUT_DIR, filename)


@app.route("/render", methods=["POST"])
def render():
    video_file = request.files.get("video")
    fill          = float(request.form.get("fill",     0.65))
    alpha         = float(request.form.get("alpha",    0.10))
    preview_secs  = float(request.form.get("preview",  0))
    show_skeleton = request.form.get("skeleton",     "false").lower() in ("true", "1", "on")
    track_holds   = request.form.get("track_holds",  "false").lower() in ("true", "1", "on")
    show_balance  = request.form.get("balance",      "false").lower() in ("true", "1", "on")
    print(f"[render] fill={fill}  alpha={alpha}  skeleton={show_skeleton}  holds={track_holds}  balance={show_balance}")

    job_id = uuid.uuid4().hex[:8]
    ext = os.path.splitext(video_file.filename)[1] or ".mp4"
    input_path    = os.path.join(UPLOAD_DIR, f"{job_id}_input{ext}")
    output_path   = os.path.join(OUTPUT_DIR,  f"{job_id}_output.mp4")
    balance_path  = os.path.join(OUTPUT_DIR,  f"{job_id}_balance.json")
    video_file.save(input_path)

    with _lock:
        _jobs[job_id] = {"progress": 0, "total": 1, "status": "running", "output": None}

    t = threading.Thread(
        target=_run,
        args=(job_id, input_path, output_path, balance_path,
              fill, alpha, preview_secs or None, show_skeleton, track_holds, show_balance),
        daemon=True,
    )
    t.start()
    return jsonify({"job_id": job_id})


def _run(job_id, input_path, output_path, balance_path,
         fill, alpha, max_seconds,
         show_skeleton=False, track_holds=False, show_balance=False):
    try:
        from src.pipeline import run as pipeline_run

        def on_progress(frame, total):
            with _lock:
                _jobs[job_id]["progress"] = frame
                _jobs[job_id]["total"]    = total

        pipeline_run(
            input_path=input_path,
            output_path=output_path,
            out_w=540, out_h=960,
            smoothing_alpha=alpha,
            person_fill=fill,
            show_com=False,
            show_skeleton=show_skeleton,
            track_holds=track_holds,
            show_balance=show_balance,
            balance_json_path=balance_path,
            progress_callback=on_progress,
            max_seconds=max_seconds,
        )

        with _lock:
            j = _jobs[job_id]
            j["status"]    = "done"
            j["progress"]  = j["total"]
            j["output"]    = os.path.basename(output_path)
            j["balance"]   = os.path.basename(balance_path)

    except Exception as exc:
        with _lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"]  = str(exc)


@app.route("/status/<job_id>")
def job_status(job_id):
    with _lock:
        job = dict(_jobs.get(job_id, {"status": "not_found"}))
    return jsonify(job)


@app.route("/balance/<filename>")
def serve_balance(filename):
    return send_from_directory(OUTPUT_DIR, filename, mimetype="application/json")


# ── Wall-Scan ──────────────────────────────────────────────────────────────

@app.route("/scan", methods=["GET"])
def scan_page():
    return send_from_directory("viewer", "scan.html")


@app.route("/scan_tests", methods=["GET"])
def scan_tests_page():
    return send_from_directory("viewer", "scan_tests.html")


@app.route("/scan", methods=["POST"])
def scan_image():
    """Take an uploaded wall photo, run wall_scan synchronously, write JSON.

    Returns ``{scan_id, image_url, json_url}``. The synchronous path keeps the
    Phase-1 flow simple — MobileSAM on a phone-sized photo is ~10 s, fine for
    a single button-click.
    """
    img_file = request.files.get("image")
    if img_file is None:
        return jsonify({"error": "no image uploaded"}), 400

    scan_id = uuid.uuid4().hex[:8]
    ext = os.path.splitext(img_file.filename)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png"):
        return jsonify({"error": f"unsupported image type: {ext}"}), 400
    image_path = os.path.join(UPLOAD_DIR, f"{scan_id}_wall{ext}")
    img_file.save(image_path)

    try:
        from src.wall_scan import scan, write_scan_json
        scan_dict = scan(image_path)
        json_path = os.path.join(OUTPUT_DIR, f"{scan_id}_scan.json")
        # Rewrite image path to a server-relative URL so the viewer can find it.
        scan_dict["image"] = f"/uploads/{os.path.basename(image_path)}"
        write_scan_json(scan_dict, json_path)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "scan_id":   scan_id,
        "image_url": scan_dict["image"],
        "json_url":  f"/scan_json/{scan_id}",
        "summary":   {
            "holds":       len(scan_dict["holds"]),
            "tags":        len(scan_dict["tags"]),
            "routes_hint": scan_dict["routes_hint"]["count"],
        },
    })


@app.route("/scan_json/<scan_id>")
def serve_scan_json(scan_id):
    return send_from_directory(OUTPUT_DIR, f"{scan_id}_scan.json",
                               mimetype="application/json")


@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)


if __name__ == "__main__":
    print("Boulder Scroll  →  http://localhost:5001")
    app.run(debug=False, threaded=True, port=5001)
