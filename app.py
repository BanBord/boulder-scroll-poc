import os
import uuid
import threading
import json

from flask import Flask, request, jsonify, send_from_directory

from src import config

app = Flask(__name__)

_jobs: dict = {}
_lock = threading.Lock()

UPLOAD_DIR = config.UPLOAD_DIR
OUTPUT_DIR = config.OUTPUT_DIR
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
    fill          = float(request.form.get("fill",     config.DEFAULT_FILL))
    alpha         = float(request.form.get("alpha",    config.DEFAULT_ALPHA))
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
            out_w=config.OUT_W, out_h=config.OUT_H,
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


@app.route("/scan_selection.js")
def serve_scan_selection_module():
    return send_from_directory("viewer", "scan_selection.js",
                               mimetype="application/javascript")


@app.route("/scan_preprocess", methods=["POST"])
def scan_preprocess():
    """Phase 1: take an uploaded wall photo, run contrast-stretch + region-
    flattening immediately, write the result to disk.

    Returns ``{scan_id, preview_url}`` fast (~4 s on a 4K photo) — the slow
    MobileSAM step is a separate ``/scan_run/<scan_id>`` call, so the user
    sees the preprocessed preview before committing to the ~10 s scan.
    """
    img_file = request.files.get("image")
    if img_file is None:
        return jsonify({"error": "no image uploaded"}), 400

    scan_id = uuid.uuid4().hex[:8]
    ext = os.path.splitext(img_file.filename)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png"):
        return jsonify({"error": f"unsupported image type: {ext}"}), 400
    raw_path = os.path.join(UPLOAD_DIR, f"{scan_id}_wall_raw{ext}")
    img_file.save(raw_path)

    preprocessed_path = os.path.join(UPLOAD_DIR, f"{scan_id}_wall_preprocessed.png")
    try:
        from src.wall_scan import preprocess_image
        preprocess_image(raw_path, preprocessed_path)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "scan_id":    scan_id,
        "preview_url": f"/uploads/{os.path.basename(preprocessed_path)}",
    })


@app.route("/scan_run/<scan_id>", methods=["POST"])
def scan_run(scan_id):
    """Phase 2: run the (slow) MobileSAM scan on the already-preprocessed
    image from a prior ``/scan_preprocess`` call.

    Returns ``{scan_id, image_url, json_url}``, same shape as the old
    single-phase ``/scan`` endpoint.
    """
    preprocessed_path = os.path.join(UPLOAD_DIR, f"{scan_id}_wall_preprocessed.png")
    if not os.path.exists(preprocessed_path):
        return jsonify({"error": f"no preprocessed image for scan_id {scan_id} "
                                  f"— call /scan_preprocess first"}), 404

    try:
        from src.wall_scan import scan, write_scan_json
        raw_dump_path = os.path.join(OUTPUT_DIR, f"{scan_id}_sam_raw.json")
        scan_dict = scan(preprocessed_path, raw_dump_path=raw_dump_path)
        json_path = os.path.join(OUTPUT_DIR, f"{scan_id}_scan.json")
        # Rewrite image path to a server-relative URL so the viewer can find it.
        scan_dict["image"] = f"/uploads/{os.path.basename(preprocessed_path)}"
        write_scan_json(scan_dict, json_path)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "scan_id":   scan_id,
        "image_url": scan_dict["image"],
        "json_url":  f"/scan_json/{scan_id}",
        "sam_raw_url": f"/scan_raw/{scan_id}",
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


@app.route("/scan_raw/<scan_id>")
def serve_scan_raw(scan_id):
    """Raw SAM segment dump (pre hold/tag filtering) — debug artifact, see
    src.wall_scan.dump_raw_sam_segments()."""
    return send_from_directory(OUTPUT_DIR, f"{scan_id}_sam_raw.json",
                               mimetype="application/json")


@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)


if __name__ == "__main__":
    print("Boulder Scroll  →  http://localhost:5001")
    app.run(debug=False, threaded=True, port=5001)
