import os
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import time
import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from config import config, HEALTH_CHECK_PORT
from monitor import EldoradoMonitor

logger = logging.getLogger("EldoradoApp")

# Shared runtime state for health check endpoint
bot_state = {
    "status": "starting",
    "started_at": datetime.now().isoformat(),
    "last_check": None,
    "checks_count": 0,
    "alerts_sent": 0,
    "last_error": None,
    "gmail_user": config.get("gmail", "user", ""),
    "check_interval": config.get("monitoring", "check_interval_seconds", 20)
}


class HealthCheckHandler(BaseHTTPRequestHandler):
    """HTTP handler for Render.com port binding and health check monitoring."""
    
    def log_message(self, format, *args):
        # Mute routine health check access logs to keep console clean
        return

    def do_GET(self):
        uptime_seconds = int((datetime.now() - datetime.fromisoformat(bot_state["started_at"])).total_seconds())
        
        response_data = {
            "status": "healthy",
            "bot_status": bot_state["status"],
            "service": "Eldorado.gg Order Notification Bot",
            "uptime_seconds": uptime_seconds,
            "last_check": bot_state["last_check"],
            "checks_count": bot_state["checks_count"],
            "alerts_sent": bot_state["alerts_sent"],
            "last_error": bot_state["last_error"],
            "timestamp": datetime.now().isoformat()
        }
        
        body = json.dumps(response_data, indent=2).encode("utf-8")
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()


def run_http_server(port: int):
    """Start lightweight HTTP health check server in background."""
    server_address = ("0.0.0.0", port)
    try:
        httpd = HTTPServer(server_address, HealthCheckHandler)
        logger.info(f"Health check HTTP server listening on port {port} (0.0.0.0:{port})")
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"Failed to start HTTP server on port {port}: {e}")


def main():
    # Determine port from Render $PORT or config
    port = int(os.getenv("PORT", HEALTH_CHECK_PORT))
    
    # Start HTTP server in a daemon thread so Render port binding succeeds instantly
    http_thread = threading.Thread(target=run_http_server, args=(port,), daemon=True)
    http_thread.start()
    
    # Small pause to allow server to bind port
    time.sleep(0.5)
    
    # Create and run the Eldorado monitor
    monitor = EldoradoMonitor(state=bot_state)
    
    try:
        bot_state["status"] = "running"
        monitor.start()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
        bot_state["status"] = "stopped"
    except Exception as e:
        logger.critical(f"Critical error in monitor: {e}", exc_info=True)
        bot_state["status"] = "error"
        bot_state["last_error"] = str(e)
        raise


if __name__ == "__main__":
    main()
