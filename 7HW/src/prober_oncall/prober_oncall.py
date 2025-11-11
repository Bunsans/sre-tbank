import logging
import signal
import sys
import time

import requests
from environs import Env
from prometheus_client import Counter, Gauge, Histogram, start_http_server

# --- Prometheus Metrics Definitions ---
# Technical SLI: API Availability
PROBER_API_AVAILABILITY_TOTAL = Counter(
    "prober_api_availability_total", "Total count of API availability checks"
)
PROBER_API_AVAILABILITY_SUCCESS_TOTAL = Counter(
    "prober_api_availability_success_total",
    "Total count of successful API availability checks",
)
PROBER_API_AVAILABILITY_FAIL_TOTAL = Counter(
    "prober_api_availability_fail_total",
    "Total count of failed API availability checks",
)
PROBER_API_AVAILABILITY_DURATION_SECONDS = Histogram(
    "prober_api_availability_duration_seconds",
    "Duration in seconds of API availability checks",
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0],
)

# Business SLI: Notification Delivery (simulated via user creation/deletion)
PROBER_NOTIFICATION_DELIVERY_TOTAL = Counter(
    "prober_notification_delivery_total",
    "Total count of notification delivery simulations",
)
PROBER_NOTIFICATION_DELIVERY_SUCCESS_TOTAL = Counter(
    "prober_notification_delivery_success_total",
    "Total count of successful notification delivery simulations",
)
PROBER_NOTIFICATION_DELIVERY_FAIL_TOTAL = Counter(
    "prober_notification_delivery_fail_total",
    "Total count of failed notification delivery simulations",
)
PROBER_NOTIFICATION_DELIVERY_DURATION_SECONDS = Histogram(
    "prober_notification_delivery_duration_seconds",
    "Duration in seconds of notification delivery simulations",
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0],
)

env = Env()
env.read_env()


class Config(object):
    oncall_api_url = env("ONCALL_API_URL", "http://localhost:8080")
    prober_scrape_interval = env.int("PROBER_SCRAPE_INTERVAL", 30)
    prober_log_level = env.log_level("PROBER_LOG_LEVEL", logging.INFO)
    prober_metrics_port = env.int(
        "PROBER_METRICS_PORT", 9082
    )  # Changed port to avoid conflict


class OncallProberClient:
    def __init__(self, config: Config) -> None:
        self.oncall_api_url = config.oncall_api_url
        self.session = requests.Session()  # Use a session for better performance

    def _check_api_liveness(self) -> bool:
        """
        Checks the liveness of the OnCall API via its healthcheck endpoint.
        This represents the Technical SLI: API Availability.
        """
        PROBER_API_AVAILABILITY_TOTAL.inc()
        logging.debug("Probing OnCall API liveness")
        start_time = time.perf_counter()
        success = False
        try:
            response = self.session.get(f"{self.oncall_api_url}/healthcheck", timeout=5)
            if response.status_code == 200:
                logging.debug(
                    f"API liveness check successful (status: {response.status_code})"
                )
                PROBER_API_AVAILABILITY_SUCCESS_TOTAL.inc()
                success = True
            else:
                logging.warning(
                    f"API liveness check failed (status: {response.status_code})"
                )
                PROBER_API_AVAILABILITY_FAIL_TOTAL.inc()
        except requests.exceptions.RequestException as err:
            logging.error(f"API liveness check error: {err}")
            PROBER_API_AVAILABILITY_FAIL_TOTAL.inc()
        finally:
            PROBER_API_AVAILABILITY_DURATION_SECONDS.observe(
                time.perf_counter() - start_time
            )
        return success

    def _simulate_notification_delivery(self) -> bool:
        """
        Simulates notification delivery by creating and deleting a test user.
        This represents the Business SLI: Notification Delivery.
        A successful user creation and deletion indicates the core OnCall logic
        (which includes notification setup) is functioning.
        """
        PROBER_NOTIFICATION_DELIVERY_TOTAL.inc()
        logging.debug("Simulating notification delivery (create/delete user)")
        username = f"prober_test_user_{int(time.time())}"  # Unique username
        start_time = time.perf_counter()
        create_success = False
        delete_success = False

        try:
            # Step 1: Create user
            logging.debug(f"Attempting to create user: {username}")
            create_request = self.session.post(
                f"{self.oncall_api_url}/users",
                json={"name": username, "email": f"{username}@example.com"},
                timeout=5,
            )
            if create_request.status_code == 201:
                logging.debug(f"User '{username}' created successfully.")
                create_success = True
            else:
                logging.warning(
                    f"Failed to create user '{username}'. Status: {create_request.status_code}, Response: {create_request.text}"
                )

        except requests.exceptions.RequestException as err:
            logging.error(f"Error during user creation for '{username}': {err}")
        finally:
            # Step 2: Attempt to delete user regardless of creation success to clean up
            if create_success:  # Only attempt deletion if creation was successful
                try:
                    logging.debug(f"Attempting to delete user: {username}")
                    delete_request = self.session.delete(
                        f"{self.oncall_api_url}/users/{username}", timeout=5
                    )
                    if delete_request.status_code == 200:
                        logging.debug(f"User '{username}' deleted successfully.")
                        delete_success = True
                    else:
                        logging.warning(
                            f"Failed to delete user '{username}'. Status: {delete_request.status_code}, Response: {delete_request.text}"
                        )
                except requests.exceptions.RequestException as err:
                    logging.error(f"Error during user deletion for '{username}': {err}")

            # Record outcome for notification delivery simulation
            if create_success and delete_success:
                PROBER_NOTIFICATION_DELIVERY_SUCCESS_TOTAL.inc()
                logging.info(
                    f"Notification delivery simulation for '{username}' successful."
                )
                return_success = True
            else:
                PROBER_NOTIFICATION_DELIVERY_FAIL_TOTAL.inc()
                logging.warning(
                    f"Notification delivery simulation for '{username}' failed (create_success: {create_success}, delete_success: {delete_success})."
                )
                return_success = False

            PROBER_NOTIFICATION_DELIVERY_DURATION_SECONDS.observe(
                time.perf_counter() - start_time
            )
        return return_success

    def probe_all_slis(self) -> None:
        """Runs all defined SLI probes."""
        self._check_api_liveness()
        self._simulate_notification_delivery()


def setup_logging(config: Config):
    logging.basicConfig(
        stream=sys.stdout,
        level=config.prober_log_level,
        format="%(asctime)s %(levelname)s:%(message)s",
    )


def main():
    config = Config()
    setup_logging(config)
    logging.info(
        f"Starting OnCall prober exporter on port: {config.prober_metrics_port}"
    )
    start_http_server(config.prober_metrics_port)
    client = OncallProberClient(config)
    while True:
        logging.debug("Running all OnCall prober SLI checks")
        client.probe_all_slis()
        logging.debug(f"Waiting {config.prober_scrape_interval} seconds for next loop")
        time.sleep(config.prober_scrape_interval)


def terminate(signal, frame):
    logging.info("Terminating OnCall prober")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)  # Also handle Ctrl+C
    main()
