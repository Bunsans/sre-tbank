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
    sla_period_days = env.int("SLA_PERIOD_DAYS", 30)
    log_level = env.log_level("LOG_LEVEL", logging.INFO)
    mysql_host = env("MYSQL_HOST", "oncall-mysql")
    mysql_port = env.int("MYSQL_PORT", 3306)
    mysql_user = env("MYSQL_USER", "root")
    mysql_password = env("MYSQL_PASS", "1234")
    mysql_db_name = env("MYSQL_DB_NAME", "sla")

    mage_api_url = env("MAGE_API_URL", "https://sage.sre-ab.ru/mage/api/search")
    mage_auth_token = env("MAGE_AUTH_TOKEN") # !!! ОБЯЗАТЕЛЬНО ЗАМЕНИТЕ НА ВАШ ТОКЕН !!!


    # Новая конфигурация: имя индекса в Mage, куда попадают метрики
    mage_metrics_index = env("MAGE_METRICS_INDEX", "oncall_metrics") # Предполагаемое имя индекса


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
            current_value float(6,3) not null,
            is_bad bool not null default false,
            period_days INT not null
            )
            """
            )
            cursor.execute(f"ALTER TABLE {self.table_name} ADD INDEX (datetime)")
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
        current_value: float,
        is_bad: bool,
        period_days: int,
        current_time: datetime,
    ):
        """Saves a calculated SLA indicator to the database."""
        cursor = self.connection.cursor()
        sql = f"INSERT INTO {self.table_name} (name, slo_target, current_value, is_bad, period_days, datetime) VALUES (%s, %s, %s, %s, %s, %s)"
        val = (name, slo_target, current_value, int(is_bad), period_days, current_time)
        try:
            cursor.execute(sql, val)
            logging.debug(
                f"Saved indicator: {name}, Value: {current_value}, Bad: {is_bad}"
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
        self.mage_metrics_index = config.mage_metrics_index # Сохраняем имя индекса
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {self.mage_auth_token}',
            'Content-Type': 'application/json',
            'accept': '*/*',
        })

    def search(
        self, query: str, start: datetime, end: datetime, size: int = 1
    ) -> list:
        """
        Queries Mage API for data using MageQL.
        Returns a list of data points. For aggregated queries, we expect a single result.
        """
        start_iso = start.isoformat(timespec='milliseconds') + "Z"
        end_iso = end.isoformat(timespec='milliseconds') + "Z"

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
            
            if not content or content.get("total") is None or not content.get("data"):
                logging.warning(
                    f"Mage API query failed or returned no data for query '{query}': {content.get('message', 'N/A')}. Response: {content}"
                )
                return []

            return content.get("data", [])

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


def get_sum_from_mage_response(data: list, field_name: str) -> float:
    """
    Извлекает сумму из ответа Mage API.
    Ожидается, что MageQL запрос уже агрегирует данные
    и возвращает одну запись с нужным суммарным полем.
    """
    if not data or not isinstance(data[0], dict) or field_name not in data[0]:
        logging.warning(f"Field '{field_name}' not found in Mage API response or data is empty: {data}")
        return 0.0
    try:
        return float(data[0][field_name])
    except (ValueError, TypeError) as e:
        logging.error(f"Could not convert value to float for field '{field_name}': {data[0].get(field_name, 'N/A')}. Error: {e}")
        return 0.0


def main():
    config = Config()
    setup_logging(config)

    db = None
    try:
        db = Mysql(config)
        mage_client = MageRequest(config)

        logging.info(
            f"Starting SLA checker. Calculating over {config.sla_period_days} days."
        )

        while True:
            current_time = datetime.now(timezone.utc)
            start_time = current_time - timedelta(days=config.sla_period_days)
            logging.info(
                f"Calculating SLAs for period: {start_time.isoformat()} to {current_time.isoformat()}"
            )

            # --- Technical SLI: API Availability ---
            # MageQL запросы для Prometheus-счетчиков.
            # Мы ищем события, у которых `__name__` соответствует имени метрики
            # и суммируем их `_value_`.
            # Важно: `_value_` - это стандартное поле в Mage для значений метрик Prometheus.
            # Если у вас другое название поля, измените его.

            api_total_metric_name = "prober_api_availability_total"
            api_success_metric_name = "prober_api_availability_success_total"
            
            mageql_api_total = (
                f'group="ab1_kim" AND system="oncall-prober-metrics" AND  __name__="{api_total_metric_name}" '
                f'| agg sum(_value_) as total_value'
            )
            mageql_api_success = (
                f' group="ab1_kim" AND system="oncall-prober-metrics" AND  __name__="{api_success_metric_name}" '
                f'| agg sum(_value_) as success_value'
            )

            api_total_data = mage_client.search(mageql_api_total, start_time, current_time)
            api_success_data = mage_client.search(mageql_api_success, start_time, current_time)

            api_total_val = get_sum_from_mage_response(api_total_data, "total_value")
            api_success_val = get_sum_from_mage_response(api_success_data, "success_value")

            api_availability_percentage = calculate_availability_sli(
                api_total_val, api_success_val
            )

            api_availability_slo = 99.9
            api_availability_is_bad = api_availability_percentage < api_availability_slo
            db.save_indicator(
                name="api_availability_percentage",
                slo_target=api_availability_slo,
                current_value=api_availability_percentage,
                is_bad=api_availability_is_bad,
                period_days=config.sla_period_days,
                current_time=current_time,
            )
            logging.info(
                f"API Availability: {api_availability_percentage:.3f}% (SLO: {api_availability_slo}%), Bad: {api_availability_is_bad}. Total: {api_total_val}, Success: {api_success_val}"
            )

            # --- Business SLI: Notification Delivery ---
            notification_total_metric_name = "prober_notification_delivery_total"
            notification_success_metric_name = "prober_notification_delivery_success_total"

            mageql_notification_total = (
                f'group="ab1_kim" AND system="oncall-prober-metrics" AND __name__="{notification_total_metric_name}" '
                f'| agg sum(_value_) as total_value'
            )
            mageql_notification_success = (
                f'group="ab1_kim" AND system="oncall-prober-metrics" AND  __name__="{notification_success_metric_name}" '
                f'| agg sum(_value_) as success_value'
            )

            notification_total_data = mage_client.search(
                mageql_notification_total, start_time, current_time
            )
            notification_success_data = mage_client.search(
                mageql_notification_success, start_time, current_time
            )

            notification_total_val = get_sum_from_mage_response(
                notification_total_data, "total_value"
            )
            notification_success_val = get_sum_from_mage_response(
                notification_success_data, "success_value"
            )

            notification_delivery_percentage = calculate_availability_sli(
                notification_total_val, notification_success_val
            )

            notification_delivery_slo = 98.0
            notification_delivery_is_bad = (
                notification_delivery_percentage < notification_delivery_slo
            )
            db.save_indicator(
                name="notification_delivery_percentage",
                slo_target=notification_delivery_slo,
                current_value=notification_delivery_percentage,
                is_bad=notification_delivery_is_bad,
                period_days=config.sla_period_days,
                current_time=current_time,
            )
            logging.info(
                f"Notification Delivery: {notification_delivery_percentage:.3f}% (SLO: {notification_delivery_slo}%), Bad: {notification_delivery_is_bad}. Total: {notification_total_val}, Success: {notification_success_val}"
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