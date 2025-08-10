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
    """
    A custom HTTP request handler for health and readiness checks.

    This handler responds to HTTP GET requests with specific paths:
    - "/healthz": Returns a 200 OK response with the body "OK", indicating the service is healthy.
    - "/readyz": Returns a 200 OK response with the body "Ready", indicating the service is ready.
    - Any other path: Returns a 404 Not Found response.

    Methods:
        do_GET():
            Handles HTTP GET requests and provides appropriate responses based on the request path.
    """
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
    """
    Starts an HTTP server for health probes.

    Args:
        server_class (type): The class to use for the HTTP server. Defaults to `HTTPServer`.
        handler_class (type): The request handler class to use. Defaults to `HealthHandler`.
        port (int): The port number on which the server will listen. Defaults to 8080.

    Raises:
        OSError: If the specified port is already in use or other socket-related errors occur.

    Behavior:
        - Initializes and starts an HTTP server using the specified server and handler classes.
        - Logs an error and exits the program if the specified port is already in use.
        - Logs a message indicating the server has started and listens indefinitely for incoming requests.
    """
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
    """
    The `startup` function reads a configuration file, validates the configuration values, and returns
    the configuration dictionary.
    :return: The `startup()` function returns the `config` dictionary after reading and validating the
    configuration values from a YAML file specified as a command-line argument.
    """
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
    """
    Handles termination signals to gracefully stop the autoscaler.

    This function is triggered when a termination signal (e.g., SIGINT or SIGTERM) 
    is received. It logs a message indicating that the autoscaler was stopped by 
    user input and then exits the program.

    Args:
        sig (int): The signal number received.
        frame (FrameType): The current stack frame (unused in this function).

    Returns:
        None
    """
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
    """
    Searches for a task in the configuration that matches the given prefix.

    This function iterates through the list of tasks in the configuration
    and returns the first task whose "name" matches the given prefix exactly
    or starts with the prefix.

    Args:
        prefix (str): The prefix to search for in the task names.

    Returns:
        dict: The task dictionary that matches the given prefix.

    Raises:
        KeyError: If no task with the given prefix is found in the configuration.
    """
    for t in config.get("tasks", []):
        if t.get("name") == prefix or t.get("name", "").startswith(prefix):
            return t
    raise KeyError(f"Task with prefix {prefix} not found in config")

get_task = find_task("auto_scaler_get_status")
put_task = find_task("auto_scaler_update_replicas")

def parse_response(resp: requests.Response):
    """
    Parses an HTTP response object and extracts key components.

    Args:
        resp (requests.Response): The HTTP response object to parse.

    Returns:
        tuple: A tuple containing the following elements:
            - status_code (int): The HTTP status code of the response.
            - headers (dict): A dictionary of the response headers.
            - raw (str): The raw text content of the response.
            - json_body (dict or None): The JSON-decoded body of the response, 
              or None if the response body is not valid JSON.
    """
    status_code = resp.status_code
    headers = dict(resp.headers)
    raw = resp.text or ""
    try:
        json_body = resp.json()
    except ValueError:
        json_body = None
    return status_code, headers, raw, json_body

def pretty(obj):
    """
    Converts a Python object into a JSON-formatted string.

    If the object cannot be serialized to JSON, it falls back to converting
    the object to its string representation.

    Args:
        obj: The Python object to be converted.

    Returns:
        str: A JSON-formatted string representation of the object, or the
        string representation of the object if JSON serialization fails.
    """
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)

def make_request(task: dict, payload: dict = None):
    """
    Sends an HTTP request based on the provided task configuration and optional payload.
    Args:
        task (dict): A dictionary containing the request configuration. It must include:
            - "request" (dict): A dictionary with the following keys:
                - "method" (str): The HTTP method (e.g., "GET", "POST").
                - "endpoint" (str): The API endpoint to send the request to.
                - "headers" (dict, optional): Additional headers to include in the request.
        payload (dict, optional): A dictionary representing the JSON payload to send with the request. Defaults to None.
    Returns:
        dict or None: The parsed JSON response body if the request is successful and contains a JSON response.
                      Returns an empty dictionary if the response body is empty.
                      Returns None if the request fails or an HTTP error occurs.
    Logs:
        - Logs the request method, endpoint, payload (if provided), status code, and response body.
        - Logs headers and raw response body at the debug level if the response body is not JSON.
        - Logs errors if the request fails or returns a non-2xx HTTP status code.
    """
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
    """
    Runs the autoscaler loop to monitor and adjust the number of replicas based on CPU utilization.

    This function continuously polls the status of the system, retrieves the current CPU utilization
    and the number of replicas, and adjusts the number of replicas to maintain the target CPU threshold.

    The scaling logic is as follows:
    - If the CPU utilization is equal to the target threshold, no scaling action is taken.
    - If the CPU utilization exceeds the target threshold, the number of replicas is increased by a predefined step.
    - If the CPU utilization is below the target threshold, the number of replicas is decreased by a predefined step,
        ensuring that the number of replicas does not drop below 1.

    The function logs relevant information and warnings during its execution, including invalid API responses
    and scaling actions taken.

    Note:
    - The function runs indefinitely in a loop with a sleep interval between iterations.
    - It relies on external functions `make_request`, `get_task`, and `put_task` for API interactions.
    - The following constants must be defined in the module:
        - `CPU_THRESHOLD`: Target CPU utilization threshold (float between 0 and 1).
        - `SCALE_UP_STEP`: Number of replicas to add when scaling up.
        - `SCALE_DOWN_STEP`: Number of replicas to remove when scaling down.
        - `POLL_INTERVAL`: Time interval (in seconds) between polling iterations.

    Raises:
            ValueError: If the API returns invalid data for CPU utilization or replicas.
    """

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
    """
    Starts a health check server on the specified port.

    The server listens on the port defined in the configuration under the key 
    "probe_port". If the key is not present, it defaults to port 8080.

    Returns:
        None
    """
    run(port=config.get("probe_port", 8080))

if __name__ == "__main__":
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    run_autoscaler()