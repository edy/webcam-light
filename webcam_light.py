#!/usr/bin/env python3

import argparse
import json
import logging
import re
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Optional, Tuple, List
import urllib.request
import urllib.parse
import urllib.error

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class Config:
    webhook_url: str
    home_ip_prefix: str
    require_home_network: bool
    require_external_monitor: bool
    debounce_seconds: float
    displays_cache_ttl_seconds: int

class SystemInfo:

    def __init__(self, config: Config):
        self._config = config
        self._display_cache: Optional[bool] = None
        self._cache_timestamp: float = 0.0

    def get_active_ipv4_addresses(self) -> List[str]:
        try:
            result = subprocess.run(
                ["/sbin/ifconfig"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                timeout=5,
            )
            ips = []
            for line in result.stdout.splitlines():
                match = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)\b", line)
                if match:
                    ip = match.group(1)
                    if not ip.startswith("127."):
                        ips.append(ip)
            return ips

        except (subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
            logger.warning(f"Failed to get IP addresses: {e}")
            return []

    def is_on_home_network(self) -> Tuple[bool, List[str]]:
        ips = self.get_active_ipv4_addresses()
        is_home = any(ip.startswith(self._config.home_ip_prefix) for ip in ips)
        return is_home, ips

    def _detect_external_monitor(self) -> bool:
        try:
            result = subprocess.run(
                ["/usr/sbin/system_profiler", "SPDisplaysDataType"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                timeout=5,
            )

            # Check for non-internal connections
            for match in re.finditer(r"(?im)^\s*Connection Type:\s*(.+)\s*$", result.stdout):
                connection_type = match.group(1).strip()
                if connection_type.lower() != "internal":
                    return True

            # Fallback: count display headers
            display_headers = re.findall(r"(?m)^\s{8}.+:\s*$", result.stdout)
            return len(display_headers) >= 2

        except (subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
            logger.warning(f"Failed to detect external monitor: {e}")
            return False

    def has_external_monitor(self) -> bool:
        now = time.time()
        cache_valid = (
            self._display_cache is not None and
            (now - self._cache_timestamp) < self._config.displays_cache_ttl_seconds
        )

        if not cache_valid:
            self._display_cache = self._detect_external_monitor()
            self._cache_timestamp = now

        return self._display_cache



class WebhookNotifier:
    def __init__(self, config: Config):
        self._config = config

    def send_notification(self, state: str, metadata: dict) -> bool:
        payload = {"state": state, **metadata}

        try:
            json_data = json.dumps(payload).encode('utf-8')

            request = urllib.request.Request(
                self._config.webhook_url,
                data=json_data,
                headers={'Content-Type': 'application/json'}
            )

            with urllib.request.urlopen(request, timeout=5) as response:
                if 200 <= response.status < 300:
                    logger.info(f"Webhook sent successfully to {self._config.webhook_url}")
                    return True
                else:
                    logger.error(f"Webhook failed with status {response.status}")
                    return False

        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            logger.error(f"Failed to send webhook: {e}")
            return False

class CameraMonitor:
    def __init__(self, config: Config):
        self._config = config
        self._system_info = SystemInfo(config)
        self._notifier = WebhookNotifier(config)
        self._last_state: Optional[str] = None
        self._last_sent: float = 0.0

    def _conditions_met(self) -> Tuple[bool, dict]:
        is_home, ips = self._system_info.is_on_home_network()
        has_external = self._system_info.has_external_monitor()

        conditions_ok = True
        if self._config.require_home_network:
            conditions_ok &= is_home
        if self._config.require_external_monitor:
            conditions_ok &= has_external

        metadata = {
            "home_network": is_home,
            "ip_addresses": ips,
            "external_monitor": has_external,
        }

        return conditions_ok, metadata

    def _should_debounce(self, state: str) -> bool:
        now = time.time()
        return (
            state == self._last_state and
            (now - self._last_sent) < self._config.debounce_seconds
        )

    def _parse_camera_state(self, log_line: str) -> Optional[str]:
        if "running -> 1" in log_line:
            return "on"
        elif "running -> 0" in log_line:
            return "off"
        return None

    def run(self) -> None:
        predicate = (
            'subsystem == "com.apple.cameracapture" AND '
            'eventMessage CONTAINS "AVCaptureSession" AND '
            '(eventMessage CONTAINS "running -> 1" OR eventMessage CONTAINS "running -> 0")'
        )

        cmd = [
            "/usr/bin/log", "stream", "--style", "syslog",
            "--predicate", predicate,
        ]

        logger.info("Starting camera monitor...")

        process = None

        try:
            with subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            ) as process:

                for line in process.stdout:
                    # Skip log command informational messages
                    if "Filtering the log data using" in line:
                        continue

                    state = self._parse_camera_state(line)
                    if not state:
                        continue

                    if self._should_debounce(state):
                        continue

                    conditions_ok, metadata = self._conditions_met()
                    logger.info(f"Camera {state} | Conditions: {metadata}")

                    if conditions_ok and (state == "on" or state == "off"):
                        self._notifier.send_notification(state, metadata)

                    self._last_state = state
                    self._last_sent = time.time()

        except KeyboardInterrupt:
            logger.info("Monitoring stopped by user")
        except Exception as e:
            logger.error(f"Monitoring failed: {e}")
        finally:
            if process:
                process.terminate()
                process.wait(timeout=5)

def parse_arguments() -> Config:
    parser = argparse.ArgumentParser(
        description="Monitor macOS camera usage and send webhook notifications",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # Get environment variable defaults
    env_webhook_url = os.getenv("WEBHOOK_URL", "http://homeassistant:8123/api/webhook/none")
    env_home_ip_prefix = os.getenv("HOME_IP_PREFIX", "192.168.137.")
    env_require_home_network = os.getenv("REQUIRE_HOME_NETWORK", "true").lower() == "true"
    env_require_external_monitor = os.getenv("REQUIRE_EXTERNAL_MONITOR", "true").lower() == "true"
    env_debounce_seconds = float(os.getenv("DEBOUNCE_SECONDS", "5.0"))
    env_displays_cache_ttl = int(os.getenv("DISPLAYS_CACHE_TTL_SECONDS", "15"))

    parser.add_argument(
        "--webhook-url",
        default=env_webhook_url,
        help="Complete webhook URL including endpoint"
    )

    parser.add_argument(
        "--home-ip-prefix",
        default=env_home_ip_prefix,
        help="IP prefix to identify home network"
    )

    # Handle boolean arguments with environment variable defaults
    home_network_group = parser.add_mutually_exclusive_group()
    home_network_group.add_argument(
        "--require-home-network",
        action="store_true",
        help="Only send notifications when on home network"
    )
    home_network_group.add_argument(
        "--no-require-home-network",
        action="store_true",
        help="Send notifications regardless of network"
    )

    external_monitor_group = parser.add_mutually_exclusive_group()
    external_monitor_group.add_argument(
        "--require-external-monitor",
        action="store_true",
        help="Only send notifications when external monitor is connected"
    )
    external_monitor_group.add_argument(
        "--no-require-external-monitor",
        action="store_true",
        help="Send notifications regardless of external monitor"
    )

    parser.add_argument(
        "--debounce-seconds",
        type=float,
        default=env_debounce_seconds,
        help="Seconds to debounce duplicate events"
    )

    parser.add_argument(
        "--displays-cache-ttl",
        type=int,
        default=env_displays_cache_ttl,
        help="Display detection cache TTL in seconds"
    )

    args = parser.parse_args()

    # Determine boolean values: command line args override environment variables
    if args.require_home_network:
        require_home_network = True
    elif args.no_require_home_network:
        require_home_network = False
    else:
        require_home_network = env_require_home_network

    if args.require_external_monitor:
        require_external_monitor = True
    elif args.no_require_external_monitor:
        require_external_monitor = False
    else:
        require_external_monitor = env_require_external_monitor

    return Config(
        webhook_url=args.webhook_url,
        home_ip_prefix=args.home_ip_prefix,
        require_home_network=require_home_network,
        require_external_monitor=require_external_monitor,
        debounce_seconds=args.debounce_seconds,
        displays_cache_ttl_seconds=args.displays_cache_ttl
    )

def main() -> None:
    config = parse_arguments()
    monitor = CameraMonitor(config)
    monitor.run()

if __name__ == "__main__":
    main()
