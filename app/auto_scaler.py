import requests
import yaml
import signal
import sys
import json
import logging
import time,os,sys
# Make sure app path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from util.logger import setup_logger
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        elif self.path == "/readyz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Ready")
        else:
            self.send_response(404)
            self.end_headers()

# Setup default logging early so startup errors are visible
setup_logger(log_level=logging.INFO)

def run(server_class=HTTPServer, handler_class=HealthHandler, port=8080):
    server_address = ("", port)
    try:
        httpd = server_class(server_address, handler_class)
    except OSError as e:
        if e.errno == 48:  # Address already in use on macOS/BSD
            logging.error(f"Port {port} is already in use. Cannot start health server.")
            sys.exit(1)
        else:
            raise
    logging.info(f"Starting health probe server on port {port}")
    httpd.serve_forever()



def startup():
    if len(sys.argv) < 3 or sys.argv[1] != "--config":
        logging.error("Usage: python3 auto_scaler.py --config config.yaml")
        sys.exit(1)

    config_path = sys.argv[2]
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Validate config values
    if not (0 < config.get("cpu_threshold", 0) <= 1):
        logging.error("Invalid cpu_threshold in config: %s", config.get("cpu_threshold"))
        sys.exit(1)
    if config.get("scale_up_step", 0) < 1 or config.get("scale_down_step", 0) < 1:
        logging.error("Scale steps must be >= 1")
        sys.exit(1)

    return config

# Graceful exit handler
def signal_handler(sig, frame):
    logging.info("Autoscaler stopped by user input.")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

config = startup()

# Override logger settings based on config
log_level_name = config.get("logging", {}).get("level", "INFO")
log_format = config.get("logging", {}).get("format", "%(asctime)s - %(levelname)s - %(message)s")
setup_logger(log_level=getattr(logging, log_level_name, logging.INFO), log_format=log_format)

BASE_URL = config["base_url"]
CPU_THRESHOLD = config["cpu_threshold"]
SCALE_UP_STEP = config["scale_up_step"]
SCALE_DOWN_STEP = config["scale_down_step"]
POLL_INTERVAL = config["poll_interval"]

PROBE_PORT = config.get("probe_port", 8080)

def find_task(prefix: str) -> dict:
    for t in config.get("tasks", []):
        if t.get("name") == prefix or t.get("name", "").startswith(prefix):
            return t
    raise KeyError(f"Task with prefix {prefix} not found in config")

get_task = find_task("auto_scaler_get_status")
put_task = find_task("auto_scaler_update_replicas")

def parse_response(resp: requests.Response):
    status_code = resp.status_code
    headers = dict(resp.headers)
    raw = resp.text or ""
    try:
        json_body = resp.json()
    except ValueError:
        json_body = None
    return status_code, headers, raw, json_body

def pretty(obj):
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)

def make_request(task: dict, payload: dict = None):
    try:
        resp = requests.request(
            method=task["request"]["method"],
            url=BASE_URL + task["request"]["endpoint"],
            headers=task["request"].get("headers", {}),
            json=payload,
            timeout=5,
        )
    except requests.RequestException as e:
        logging.error("%s request failed: %s", task["request"]["method"], e)
        return None

    status_code, headers, raw, json_body = parse_response(resp)
    body_repr = pretty(json_body) if json_body is not None else "{}"
    logging.info("%s %s%s%s %s %s",
                 task["request"]["method"],
                 task["request"]["endpoint"],
                 " payload=" if payload else "", pretty(payload) if payload else "",
                 status_code, body_repr)
    
    logging.debug("%s headers=%s", task["request"]["method"], headers)
    if json_body is None:
        logging.debug("%s raw body: %s", task["request"]["method"], raw)

    try:
        resp.raise_for_status()
    except requests.RequestException:
        logging.error("%s returned HTTP %s", task["request"]["method"], status_code)
        return None

    return json_body if json_body is not None else {}



def run_autoscaler():

    logging.info("Starting autoscaler loop (target CPU=%s)", CPU_THRESHOLD)
    while True:
        status = make_request(get_task)
        if status is None:
            time.sleep(POLL_INTERVAL)
            continue

        cpu_util = status.get("cpu", {}).get("highPriority")
        replicas = status.get("replicas")

        if not isinstance(cpu_util, (float, int)) or not (0 <= cpu_util <= 1):
            logging.warning("Invalid CPU util from API: %s", cpu_util)
            time.sleep(POLL_INTERVAL)
            continue
        if not isinstance(replicas, int) or replicas < 1:
            logging.warning("Invalid replicas from API: %s", replicas)
            time.sleep(POLL_INTERVAL)
            continue

        #logging.info("CPU: %.2f, Replicas: %d", cpu_util, replicas)

        if cpu_util == CPU_THRESHOLD:
            logging.info("CPU is at target threshold, no scaling action taken.")
        elif cpu_util > CPU_THRESHOLD:
            new_replicas = replicas + SCALE_UP_STEP
            logging.info("Scaling UP: CPU %.2f > %.2f, increasing replicas from %d to %d",
                         cpu_util, CPU_THRESHOLD, replicas, new_replicas)
            make_request(put_task, {"replicas": new_replicas})
        elif cpu_util < CPU_THRESHOLD:
            # Making sure that it should not go below 1 replica
            new_replicas = max(1, replicas - SCALE_DOWN_STEP)
            logging.info("Scaling Down: CPU %.2f < %.2f, decreasing replicas from %d to %d",
                         cpu_util, CPU_THRESHOLD, replicas, new_replicas)
            make_request(put_task, {"replicas": new_replicas})

        time.sleep(POLL_INTERVAL)

def start_health_server():
    run(port=config.get("probe_port", 8080))

if __name__ == "__main__":
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    run_autoscaler()