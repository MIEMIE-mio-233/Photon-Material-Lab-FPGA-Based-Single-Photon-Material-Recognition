"""MPSoC-P4 本地网页入口；HTML在PS上提供，浏览器只负责控制与显示。"""

import argparse
import json
import uuid
import io
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException

from services import BusyError, Controller, PROJECT, WEB, load_json, training

app = Flask(__name__, static_folder=str(WEB / "static"))
app.config.update(JSON_AS_ASCII=False, JSON_SORT_KEYS=False, MAX_CONTENT_LENGTH=8 * 1024 * 1024)
config = load_json(WEB / "config.json")
controller = Controller(config)


@app.before_request
def same_origin():
    # 控制接口只接受本网页请求，不开放跨站调用或任意命令执行。
    if request.method == "POST":
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.host:
            return jsonify(ok=False, error="请从 P4 控制网页发起操作"), 403
        if request.path != "/api/upload" and not request.is_json:
            return jsonify(ok=False, error="请求应使用 JSON"), 400


@app.after_request
def response_headers(response):
    if request.path.startswith(("/api/", "/static/")) or request.path == "/":
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.errorhandler(Exception)
def handle_error(error):
    status = 409 if isinstance(error, BusyError) else 400
    if isinstance(error, HTTPException):
        status = error.code
    elif isinstance(error, FileNotFoundError):
        status = 404
    elif not isinstance(error, (ValueError, OSError)):
        app.logger.exception("网页请求失败")
        status = 500
    return jsonify(ok=False, error=str(error)), status


@app.route("/")
def index():
    return send_from_directory(str(WEB / "static"), "index.html", max_age=0)


@app.route("/api/hardware", methods=["POST"])
def hardware():
    return jsonify(ok=True, hardware=controller.hardware(request.get_json().get("action")))


@app.route("/api/outputs", methods=["POST"])
def outputs():
    options = request.get_json()
    if not isinstance(options, dict):
        raise ValueError("输出参数应为对象")
    return jsonify(ok=True, outputs=controller.outputs(options))


@app.route("/api/state")
def state():
    after = request.args.get("after_frame", default=0, type=int)
    return jsonify(ok=True, **controller.snapshot(max(0, after), request.args.get("capture_job")))


@app.route("/api/data")
def data():
    return jsonify(ok=True, **controller.store.browser_index())


@app.route('/api/demo/ack',methods=['POST'])
def demo_ack():
    options=request.get_json()
    if not isinstance(options,dict):raise ValueError('演示确认应为对象')
    controller.acknowledge_demo(options.get('result_id'))
    return jsonify(ok=True)


@app.route('/api/range-calibration',methods=['POST'])
def range_calibration():
    options=request.get_json()
    if not isinstance(options,dict):raise ValueError('校准参数应为对象')
    return jsonify(ok=True,range_calibration=controller.range_action(options))


@app.route("/api/data/delete_run", methods=["POST"])
def delete_run():
    options = request.get_json()
    if not isinstance(options, dict):
        raise ValueError("删除参数应为对象")
    return jsonify(ok=True, deleted=controller.delete_run(options.get("collection"), options.get("run_id")))


@app.route("/api/jobs/<kind>", methods=["POST"])
def start_job(kind):
    if kind == "stop":
        controller.stop()
        return jsonify(ok=True)
    options = request.get_json()
    if not isinstance(options, dict):
        raise ValueError("请求参数应为对象")
    return jsonify(ok=True, job=controller.start(kind, options)), 202


@app.route("/api/model", methods=["POST"])
def select_model():
    options = request.get_json()
    controller.select_model(options.get("model_id", options.get("source")))
    return jsonify(ok=True, model=controller.model_info())


@app.route("/api/models")
def model_versions():
    return jsonify(ok=True, **controller.model_catalog())


@app.route("/api/models/delete", methods=["POST"])
def delete_model_version():
    options = request.get_json()
    if not isinstance(options, dict):
        raise ValueError("模型删除参数应为对象")
    return jsonify(ok=True, deleted=controller.delete_model(options.get("model_id")))


@app.route("/api/plot")
def plot():
    return jsonify(ok=True, **controller.plot(request.args.get("path", ""), request.args.get("view", "full")))


@app.route("/api/comparison/plot")
def comparison_plot():
    return jsonify(ok=True, **controller.comparison_plot(request.args.get("view", "full")))


@app.route("/api/upload", methods=["POST"])
def upload():
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename.lower().endswith((".csv", ".npy")):
        raise ValueError("请上传一帧CSV或NPY直方图")
    path = WEB / "uploads" / ("frame_" + uuid.uuid4().hex[:12] + Path(uploaded.filename).suffix.lower())
    uploaded.save(str(path))
    try:
        training.read_frame(path)
    except Exception:
        path.unlink()
        raise ValueError("直方图格式无效：CSV需bin_index,count两列，NPY需uint32计数数组")
    return jsonify(ok=True, path=path.relative_to(PROJECT).as_posix())


@app.route("/api/training/image/<kind>")
def training_image(kind):
    path,status = controller.charts.request(kind, request.args.get("model_id") or None,
                                            int(request.args.get("class_index", 0)), request.args.get("retry") == "1")
    if path is not None:
        return send_file(str(path), max_age=0)
    code = 409 if status["state"] in ("failed", "cancelled") else 202
    response = jsonify(ok=code==202, **status)
    response.headers["Retry-After"] = "1"
    return response, code


@app.route("/api/model/download/<kind>")
def download_model(kind):
    extensions = {"native": ".joblib", "portable": ".portable.json", "report": ".report.json"}
    if kind not in extensions:
        raise ValueError("模型文件类型不正确")
    path = controller.registry.path(request.args.get("model_id") or None).with_suffix(extensions[kind])
    info = controller.registry.info(request.args.get('model_id') or None)
    return send_file(str(path), as_attachment=True, download_name=path.name, max_age=0)


@app.route("/api/frame/download")
def download_frame():
    content, name = controller.prepare_download(request.args.get("path", ""))
    return send_file(content, as_attachment=True, download_name=name, mimetype="text/csv", max_age=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=config["host"])
    parser.add_argument("--port", type=int, default=config["port"])
    args = parser.parse_args()
    print("TDC 材质识别网页：http://板卡IP:{}".format(args.port), flush=True)
    app.run(host=args.host, port=args.port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
