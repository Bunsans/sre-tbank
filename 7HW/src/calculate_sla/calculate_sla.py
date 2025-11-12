import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

import mysql.connector
import requests
from environs import Env

env = Env()
env.read_env()


class Config(object):
    scrape_interval = env.int("SCRAPE_INTERVAL", 60)
    sla_period_minutes = env.int("SLA_PERIOD_MINUTES", 30)
    log_level = env.log_level("LOG_LEVEL", logging.INFO)
    mysql_host = env("MYSQL_HOST", "oncall-mysql")
    mysql_port = env.int("MYSQL_PORT", 3306)
    mysql_user = env("MYSQL_USER", "root")
    mysql_password = env("MYSQL_PASS", "1234")
    mysql_db_name = env("MYSQL_DB_NAME", "sla")
    mage_api_url = env("MAGE_API_URL", "https://sage.sre-ab.ru/mage/api/search")
    mage_auth_token = env("MAGE_AUTH_TOKEN")
    mage_source = env("MAGE_SOURCE", "token_sla_calc")

class Mysql:
    def __init__(self, config: Config) -> None:
        logging.info("Connecting to MySQL database")
        self.connection = mysql.connector.connect(
            host=config.mysql_host,
            port=config.mysql_port,
            user=config.mysql_user,
            passwd=config.mysql_password,
            auth_plugin="mysql_native_password",
            autocommit=True,
        )
        self.db_name = config.mysql_db_name
        self.table_name = "sla_indicators"

        logging.info(
            f"Ensuring database '{self.db_name}' and table '{self.table_name}' exist."
        )
        cursor = self.connection.cursor()

        try:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {self.db_name}")
            cursor.execute(f"USE {self.db_name}")
            cursor.execute(
                f"""
            CREATE TABLE IF NOT EXISTS {self.table_name}(
            id INT AUTO_INCREMENT PRIMARY KEY,
            datetime datetime not null default NOW(),
            name varchar(255) not null,
            slo_target float(6,3) not null,
            sli float(6,3) not null,
            is_bad bool not null default false,
            period_minutes INT not null
            )
            """
            )
            # Добавил проверку на существование индекса перед созданием
            cursor.execute(f"SHOW INDEX FROM {self.table_name} WHERE Key_name = 'datetime'")
            if not cursor.fetchone():
                cursor.execute(f"ALTER TABLE {self.table_name} ADD INDEX (datetime)")
            cursor.execute(f"SHOW INDEX FROM {self.table_name} WHERE Key_name = 'name'")
            if not cursor.fetchone():
                cursor.execute(f"ALTER TABLE {self.table_name} ADD INDEX (name)")
        except mysql.connector.Error as err:
            logging.critical(f"Failed to initialize database or table: {err}")
            sys.exit(1)
        finally:
            cursor.close()

    def save_indicator(
        self,
        name: str,
        slo_target: float,
        sli: float,
        is_bad: bool,
        period_minutes: int,
        current_time: datetime,
    ):
        """Saves a calculated SLA indicator to the database."""
        cursor = self.connection.cursor()
        sql = f"INSERT INTO {self.table_name} (name, slo_target, sli, is_bad, period_minutes, datetime) VALUES (%s, %s, %s, %s, %s, %s)"
        val = (name, slo_target, sli, int(is_bad), period_minutes, current_time)
        try:
            cursor.execute(sql, val)
            logging.debug(
                f"Saved indicator: {name}, SlI: {sli}, Bad: {is_bad}"
            )
        except mysql.connector.Error as err:
            logging.error(f"Error saving indicator '{name}': {err}")
        finally:
            cursor.close()

    def close(self):
        if self.connection.is_connected():
            self.connection.close()
            logging.info("MySQL connection closed.")


class MageRequest:
    def __init__(self, config: Config) -> None:
        self.mage_api_url = config.mage_api_url
        self.mage_auth_token = config.mage_auth_token
        self.mage_source = config.mage_source
        self.session = requests.Session()
        logging.debug(f"mage_source: {self.mage_auth_token[:10]}")
        self.session.headers.update({
            'Authorization': f'Bearer {self.mage_auth_token}',
            'Content-Type': 'application/json',
            'accept': '*/*',
            'Source': f"{self.mage_source}"
        })

    def search(
        self, query: str, start: datetime, end: datetime, size: int = 1
    ) -> list:
        """
        Queries Mage API for data using MageQL.
        Returns a list of data points (specifically, the 'hits' from the response).
        For aggregated queries, we expect 'hits' to contain a single result.
        """
        start_iso = start.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        end_iso = end.strftime('%Y-%m-%dT%H:%M:%S.000Z')

        payload = {
            "query": query,
            "size": size,
            "startTime": start_iso,
            "endTime": end_iso
        }
        
        logging.debug(f"Mage API Request: URL={self.mage_api_url}, Payload={payload}")

        try:
            response = self.session.post(
                self.mage_api_url,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            content = response.json()
            
            # Извлекаем 'hits', который содержит агрегированные результаты
            hits = content.get("hits", [])
            
            if not hits:
                logging.warning(
                    f"Mage API query failed or returned no hits for query '{query}'. Response: {content}"
                )
                return []

            return hits

        except requests.exceptions.RequestException as error:
            logging.error(f"Error querying Mage API for '{query}': {error}")
            return []
        except Exception as error:
            logging.error(
                f"Unexpected error processing Mage API response for '{query}': {error}"
            )
            return []


def setup_logging(config: Config):
    logging.basicConfig(
        stream=sys.stdout,
        level=config.log_level,
        format="%(asctime)s %(levelname)s:%(message)s",
    )


def calculate_availability_sli(total_checks: float, success_checks: float) -> float:
    """Calculates the availability SLI percentage based on aggregated sums."""
    if total_checks == 0:
        return 100.0
    return (success_checks / total_checks) * 100


def get_sum_from_mage_response(hits: list, field_name: str) -> float:
    """
    Извлекает сумму из 'hits' ответа Mage API.
    Ожидается, что 'hits' содержит список с одним словарем,
    в котором находится нужное суммарное поле.
    """
    if not hits or not isinstance(hits, list) or not hits[0] or not isinstance(hits[0], dict):
        logging.warning(f"Invalid Mage API 'hits' response format or empty: {hits}")
        return 0.0
    
    # Теперь ищем поле непосредственно в первом элементе списка hits
    if field_name not in hits[0]:
        logging.warning(f"Field '{field_name}' not found in the first hit of Mage API response: {hits[0]}")
        return 0.0
        
    try:
        return float(hits[0][field_name])
    except (ValueError, TypeError) as e:
        logging.error(f"Could not convert value to float for field '{field_name}': {hits[0].get(field_name, 'N/A')}. Error: {e}")
        return 0.0


def main():
    config = Config()
    setup_logging(config)

    db = None
    try:
        db = Mysql(config)
        mage_client = MageRequest(config)

        logging.info(
            f"Starting SLA checker. Calculating over last {config.sla_period_minutes} minutes."
        )

        while True:
            current_time = datetime.now(timezone.utc)
            start_time = current_time - timedelta(minutes=config.sla_period_minutes)
            logging.info(
                f"Calculating SLAs for period: {start_time.isoformat()} to {current_time.isoformat()}"
            )

            # --- Technical SLI: API Availability ---
            api_total_metric_name = "prober_api_availability_total"
            api_success_metric_name = "prober_api_availability_success_total"
            
            mageql_api_total = (
                f'pql {{group="ab1_kim", system="oncall-prober-metrics", __name__="{api_total_metric_name}"}} '
                f'| stats sum(value) as total_value'
            )
            mageql_api_success = (
                f'pql {{group="ab1_kim", system="oncall-prober-metrics",  __name__="{api_success_metric_name}"}}  '
                f'| stats sum(value) as success_value'
            )

            # search теперь возвращает список hits
            api_total_hits = mage_client.search(mageql_api_total, start_time, current_time)
            api_success_hits = mage_client.search(mageql_api_success, start_time, current_time)

            # передаем список hits в get_sum_from_mage_response
            api_total_val = get_sum_from_mage_response(api_total_hits, "total_value")
            api_success_val = get_sum_from_mage_response(api_success_hits, "success_value")

            api_availability_percentage = calculate_availability_sli(
                api_total_val, api_success_val
            )

            api_availability_slo = 99.9
            api_availability_is_bad = api_availability_percentage < api_availability_slo
            db.save_indicator(
                name="api_availability_percentage",
                slo_target=api_availability_slo,
                sli=api_availability_percentage,
                is_bad=api_availability_is_bad,
                period_minutes=config.sla_period_minutes,
                current_time=current_time,
            )
            logging.info(
                f"API Availability: {api_availability_percentage:.3f}% (SLO: {api_availability_slo}%), Bad: {api_availability_is_bad}. Total: {api_total_val}, Success: {api_success_val}"
            )

            # --- Business SLI: Creation user ---
            creation_total_metric_name = "prober_creation_user_total"
            creation_success_metric_name = "prober_creation_user_success_total"

            mageql_creation_total = (
                f'pql {{ group="ab1_kim", system="oncall-prober-metrics", __name__="{creation_total_metric_name}"}}'
                f'| stats sum(value) as total_value'
            )
            mageql_creation_success = (
                f'pql {{ group="ab1_kim", system="oncall-prober-metrics", __name__="{creation_success_metric_name}"}}'
                f'| stats sum(value) as success_value'
            )

            creation_total_hits = mage_client.search(
                mageql_creation_total, start_time, current_time
            )
            creation_success_hits = mage_client.search(
                mageql_creation_success, start_time, current_time
            )

            creation_total_val = get_sum_from_mage_response(
                creation_total_hits, "total_value"
            )
            creation_success_val = get_sum_from_mage_response(
                creation_success_hits, "success_value"
            )

            creation_user_percentage = calculate_availability_sli(
                creation_total_val, creation_success_val
            )

            creation_user_slo = 98.0
            creation_user_is_bad = (
                creation_user_percentage < creation_user_slo
            )
            db.save_indicator(
                name="creation_user_percentage",
                slo_target=creation_user_slo,
                sli=creation_user_percentage,
                is_bad=creation_user_is_bad,
                period_minutes=config.sla_period_minutes,
                current_time=current_time,
            )
            logging.info(
                f"Creation user: {creation_user_percentage:.3f}% (SLO: {creation_user_slo}%), Bad: {creation_user_is_bad}. Total: {creation_total_val}, Success: {creation_success_val}"
            )

            logging.debug(f"Waiting {config.scrape_interval} seconds for next loop")
            time.sleep(config.scrape_interval)

    except Exception as e:
        logging.critical(
            f"SLA Calculator experienced a critical error: {e}", exc_info=True
        )
    finally:
        if db:
            db.close()


def terminate(signal, frame):
    logging.info("Terminating SLA calculator")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    main()