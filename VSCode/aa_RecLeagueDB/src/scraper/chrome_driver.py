"""Chrome driver initialization with stealth mode."""

import time
import logging
from typing import Optional
import undetected_chromedriver as uc
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)


class ChromeDriverManager:
    """Manage undetected Chrome driver initialization."""

    def __init__(self, headless: bool = True):
        """
        Initialize Chrome driver manager.

        Args:
            headless: Run in headless mode (default True)
        """
        self.headless = headless
        self.driver: Optional[uc.Chrome] = None

    def get_driver(self) -> uc.Chrome:
        """
        Get or create Chrome driver with stealth options.

        Returns:
            uc.Chrome: Undetected Chrome driver instance
        """
        if self.driver is not None:
            try:
                # Test if driver is still responsive
                self.driver.execute_script("return 1;")
                return self.driver
            except Exception as e:
                logger.warning(f"Driver became unresponsive, reinitializing: {e}")
                self.driver = None

        try:
            options = uc.ChromeOptions()

            if self.headless:
                options.add_argument("--headless=new")

            # Anti-bot detection options
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )

            # Performance options
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-plugins")

            # Stability improvements for Windows
            options.add_argument("--disable-gpu")
            options.add_argument("--start-maximized")

            logger.info("Initializing undetected Chrome driver...")
            # Use version 144 to match installed Chrome 144.0.7559.133
            self.driver = uc.Chrome(options=options, version_main=144, use_subprocess=True)
            logger.info("Chrome driver initialized successfully")

            return self.driver

        except Exception as e:
            logger.error(f"Failed to initialize Chrome driver: {e}")
            logger.info("Falling back to standard Selenium driver")
            # Fallback to standard Selenium for compatibility
            raise

    def fetch_url(
        self,
        url: str,
        wait_time: int = 15,
        scroll_delay: int = 3,
    ) -> str:
        """
        Fetch a URL using Chrome driver.

        Args:
            url: URL to fetch
            wait_time: Max seconds to wait for page load (default 15)
            scroll_delay: Additional delay after page load for lazy loading (default 3)

        Returns:
            str: Page source HTML

        Raises:
            Exception: If page fetch fails
        """
        try:
            driver = self.get_driver()
        except Exception as e:
            logger.error(f"Failed to get driver, giving up: {e}")
            raise

        try:
            logger.info(f"Fetching: {url}")

            # Set page load timeout
            driver.set_page_load_timeout(wait_time)

            try:
                driver.get(url)
            except Exception as e:
                logger.warning(f"Page load timeout or error: {e}, trying to get source anyway")

            # Reset driver state to be safe
            driver.set_page_load_timeout(300)

            # Simple wait for page to load
            time.sleep(2)  # Initial wait for page to start loading

            # Wait for body element
            try:
                WebDriverWait(driver, wait_time).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
            except Exception:
                logger.warning("Timeout waiting for body element, continuing anyway")

            # Additional wait for content to render
            logger.debug(f"Waiting {scroll_delay}s for content rendering...")
            time.sleep(scroll_delay)

            # Get HTML before scrolling (some sites crash on scroll in headless)
            try:
                html = driver.page_source
                if len(html) < 500:
                    # Try scrolling if page seems too small
                    try:
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        time.sleep(1)
                        html = driver.page_source
                    except Exception:
                        pass  # Ignore scroll errors
            except Exception as e:
                logger.warning(f"Error during page access: {e}, trying to recover")
                try:
                    html = driver.page_source
                except Exception:
                    # Driver is dead, reset it
                    logger.error("Driver crashed, resetting...")
                    self.driver = None
                    raise

            logger.info(f"Successfully fetched {len(html)} bytes from {url}")
            return html

        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            # Don't reset driver here - let caller decide
            raise

    def quit(self):
        """Close the driver."""
        if self.driver is not None:
            try:
                self.driver.quit()
                logger.info("Chrome driver closed")
            except Exception as e:
                logger.warning(f"Error closing driver: {e}")
            finally:
                self.driver = None

    def __enter__(self):
        """Context manager entry."""
        self.get_driver()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.quit()
