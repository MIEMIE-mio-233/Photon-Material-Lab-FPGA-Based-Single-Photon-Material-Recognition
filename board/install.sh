#!/usr/bin/env bash
# 仅安装到可启动的PYNQ2.7 aarch64/Python3.8；不改IP、不下载PL。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${TDC_APP_DIR:-/home/xilinx/tdc_material}"
ENV_DIR="${TDC_ENV_DIR:-/home/xilinx/tdc-ml-env}"
PYNQ_PY="${PYNQ_PYTHON:-/usr/local/share/pynq-venv/bin/python3}"
[ "$(id -u)" = 0 ] || { echo '请使用sudo运行'; exit 1; }
"$PYNQ_PY" -c 'import sys,platform,numpy,scipy,flask,matplotlib,pynq; assert platform.machine()=="aarch64" and sys.version_info[:2]==(3,8)'
if systemctl is-active --quiet tdc-material-web; then
  echo '服务仍在运行，请先完成任务并停止服务，再安装。'; exit 1
fi
mkdir -p "$APP"
for name in dataset models overlays; do
  if [ -e "$APP/$name" ] && [ ! -L "$APP/$name" ]; then
    echo "$APP/$name已有实目录，请先备份并选择空目标。"; exit 1
  fi
done
if [ ! -x "$ENV_DIR/bin/python" ]; then
  "$PYNQ_PY" -m venv --system-site-packages "$ENV_DIR"
fi
BASE_SITE=$("$PYNQ_PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
ENV_SITE=$("$ENV_DIR/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
printf "import site; site.addsitedir('%s')\n" "$BASE_SITE" > "$ENV_SITE/pynq_base.pth"
"$ENV_DIR/bin/python" -m pip install --no-index --no-deps --find-links "$ROOT/board/wheels" scikit-learn==0.24.2 joblib==1.1.1 threadpoolctl==3.1.0
cp -a "$ROOT/src/ps/." "$APP/"
ln -sfn "$ROOT/data/dataset" "$APP/dataset"
ln -sfn "$ROOT/data/models" "$APP/models"
ln -sfn "$ROOT/board/overlays" "$APP/overlays"
cat > /etc/systemd/system/tdc-material-web.service <<EOF
[Unit]
Description=Photon material recognition web console
After=network.target
[Service]
Type=simple
WorkingDirectory=$APP
Environment=XILINX_XRT=/usr
Environment=PYTHONIOENCODING=utf-8
Environment=PYTHONUNBUFFERED=1
Environment=MPLBACKEND=Agg
Environment=LANG=C.UTF-8
ExecStart=$ENV_DIR/bin/python -u $APP/web/server.py --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now tdc-material-web
echo '网页：http://板卡IP:8080/；服务启动未加载PL。'
