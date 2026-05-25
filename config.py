import os
import logging
import logging.config
import secrets
import re
from pathlib import Path
from typing import Any, Optional, Union
from dotenv import load_dotenv

# --- Logger Configuration ---
def _setup_logger() -> logging.Logger:
    """
    Configure centralized logger for config module with fallback to NullHandler.
    Returns early if logging is already configured to avoid duplication.
    """
    logger_instance = logging.getLogger(__name__)
    
    # Avoid reconfiguring if already configured
    if logger_instance.handlers:
        return logger_instance
    
    # Use NullHandler if no handlers are configured upstream
    if not logging.getLogger().handlers:
        logger_instance.addHandler(logging.NullHandler())
    
    return logger_instance

logger = _setup_logger()

# Load .env file
PROJECT_ROOT = Path(__file__).resolve().parent
PROJECT_ENV_PATH = PROJECT_ROOT / ".env"

if PROJECT_ENV_PATH.exists():
    load_dotenv(dotenv_path=PROJECT_ENV_PATH)
else:
    load_dotenv()

# Detection of the environment should be done only once at startup.
try:
    import streamlit as st
    # Verify st.secrets is accessible
    _ = st.secrets
    _HAS_STREAMLIT = True
except (ImportError, RuntimeError, AttributeError, FileNotFoundError):
    st = None
    _HAS_STREAMLIT = False

# --- Configuration Constants ---
VALID_APP_ENVS = {"dev", "development", "local", "staging", "production", "prod", "live"}
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
VALID_PRIVACY_PROFILES = {"personal_identifiers", "sensitive_data", "all_data"}
BOOL_TRUE_VALUES = {"1", "true", "yes", "on"}
BOOL_FALSE_VALUES = {"0", "false", "no", "off"}

class ConfigError(Exception):
    """Raised when configuration validation fails."""
    pass


def _get_val(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Retrieve configuration value from Streamlit secrets or environment variables.
    
    Args:
        key: Configuration key to retrieve
        default: Default value if key is not found
        
    Returns:
        Configuration value or default, or None if not found and no default provided
    """
    if _HAS_STREAMLIT and st is not None:
        try:
            if key in st.secrets:
                value = st.secrets[key]
                logger.debug(f"Retrieved {key} from Streamlit secrets")
                return value
        except Exception as e:
            logger.debug(f"Failed to retrieve {key} from Streamlit: {e}")
    
    # Fallback to environment variables
    value = os.getenv(key, default)
    if value is not None and value != default:
        logger.debug(f"Retrieved {key} from environment")
    return value


def _get_bool_env(key: str, default: bool = False) -> bool:
    """
    Retrieve boolean configuration value with strict normalization.
    
    Args:
        key: Configuration key to retrieve
        default: Default value if key is not found
        
    Returns:
        Boolean configuration value
        
    Raises:
        ConfigError: If value exists but is not a valid boolean representation
    """
    raw_value = _get_val(key)
    
    if raw_value is None:
        return default
    
    normalized = str(raw_value).lower().strip()
    
    if normalized in BOOL_TRUE_VALUES:
        return True
    elif normalized in BOOL_FALSE_VALUES:
        return False
    else:
        logger.warning(
            f"Invalid boolean value for {key}={raw_value}. "
            f"Valid values: {BOOL_TRUE_VALUES | BOOL_FALSE_VALUES}. "
            f"Using default: {default}"
        )
        return default


def _get_int_env(key: str, default: int, min_value: Optional[int] = None, 
                 max_value: Optional[int] = None) -> int:
    """
    Retrieve integer configuration value with validation and error handling.
    
    Args:
        key: Configuration key to retrieve
        default: Default value if key is not found or conversion fails
        min_value: Minimum acceptable value (optional)
        max_value: Maximum acceptable value (optional)
        
    Returns:
        Integer configuration value
        
    Raises:
        ConfigError: If value exists but cannot be converted to int in strict mode
    """
    raw_value = _get_val(key)
    
    if raw_value is None:
        return default
    
    try:
        int_value = int(raw_value)
        
        # Validate range if bounds specified
        if min_value is not None and int_value < min_value:
            logger.warning(
                f"{key}={int_value} is below minimum {min_value}. Using default: {default}"
            )
            return default
        
        if max_value is not None and int_value > max_value:
            logger.warning(
                f"{key}={int_value} is above maximum {max_value}. Using default: {default}"
            )
            return default
        
        return int_value
        
    except (ValueError, TypeError) as e:
        logger.warning(
            f"Failed to convert {key}={raw_value} to int. Using default {default}: {e}"
        )
        return default


def _get_float_env(key: str, default: float, min_value: Optional[float] = None,
                   max_value: Optional[float] = None) -> float:
    """
    Retrieve float configuration value with validation and error handling.
    
    Args:
        key: Configuration key to retrieve
        default: Default value if key is not found or conversion fails
        min_value: Minimum acceptable value (optional)
        max_value: Maximum acceptable value (optional)
        
    Returns:
        Float configuration value
        
    Raises:
        ConfigError: If value exists but cannot be converted to float in strict mode
    """
    raw_value = _get_val(key)
    
    if raw_value is None:
        return default
    
    try:
        float_value = float(raw_value)
        
        # Validate range if bounds specified
        if min_value is not None and float_value < min_value:
            logger.warning(
                f"{key}={float_value} is below minimum {min_value}. Using default: {default}"
            )
            return default
        
        if max_value is not None and float_value > max_value:
            logger.warning(
                f"{key}={float_value} is above maximum {max_value}. Using default: {default}"
            )
            return default
        
        return float_value
        
    except (ValueError, TypeError) as e:
        logger.warning(
            f"Failed to convert {key}={raw_value} to float. Using default {default}: {e}"
        )
        return default


def _validate_url(url: str, require_https: bool = False) -> bool:
    """
    Validate URL format.
    
    Args:
        url: URL string to validate
        require_https: If True, require https:// scheme
        
    Returns:
        True if valid, False otherwise
    """
    if not url:
        return False
    
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
        r'localhost|'  # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # IP
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    is_valid = url_pattern.match(url) is not None
    
    if require_https and is_valid and not url.lower().startswith("https://"):
        return False
    
    return is_valid

class Config:
    """
    Configuration management for LegalEase AI application.
    
    Supports environment-based configuration from:
    1. Streamlit secrets (if available)
    2. Environment variables
    3. .env file
    4. Hardcoded defaults
    
    All configuration is validated at module load time. Call validate_all() 
    to perform comprehensive validation.
    """
    
    # --- App Identity ---
    APP_NAME: str = _get_val("APP_NAME", "LegalEase AI")
    APP_ENV: str = _get_val("APP_ENV", _get_val("ENVIRONMENT", "development")).lower()
    DEBUG: bool = _get_bool_env("DEBUG", APP_ENV in ("dev", "development", "local"))
    TESTING: bool = _get_bool_env("TESTING", False)
    REQUIRE_HTTPS: bool = _get_bool_env("REQUIRE_HTTPS", True)
    
    # --- Logging ---
    LOG_LEVEL: str = _get_val("LOG_LEVEL", "INFO")
    
    # --- Model Settings (LLM) ---
    # The primary model used for generating summaries and legal remedies analysis.
    # Default is Llama 3.1 8B Instruct via OpenRouter.
    DEFAULT_MODEL: str = _get_val("DEFAULT_MODEL", "meta-llama/llama-3.1-8b-instruct")
    
    # Base URL for the OpenAI-compatible API (OpenRouter is used by default).
    OPENROUTER_BASE_URL: str = _get_val("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    
    # API Key for OpenRouter. Must be provided for the AI features to work.
    OPENROUTER_API_KEY: str = _get_val("OPENROUTER_API_KEY", "")
    
    # API Key for OpenAI.
    OPENAI_API_KEY: str = _get_val("OPENAI_API_KEY", "")
    
    # --- AI Request Performance & Reliability ---
    # The maximum number of tokens allowed for judgment summaries.
    SUMMARY_MAX_TOKENS: int = _get_int_env("SUMMARY_MAX_TOKENS", 280, min_value=1, max_value=10000)
    
    # The maximum number of tokens allowed for legal remedies analysis.
    REMEDIES_MAX_TOKENS: int = _get_int_env("REMEDIES_MAX_TOKENS", 900, min_value=1, max_value=10000)
    
    # Controls the randomness of the AI output. 
    # Lower values (0.0-0.2) make the output more deterministic and focused.
    LLM_TEMPERATURE: float = _get_float_env("LLM_TEMPERATURE", 0.05, min_value=0.0, max_value=2.0)
    
    # The timeout in seconds for AI model API requests. 
    # This is critical for preventing the application from hanging on slow network calls.
    AI_REQUEST_TIMEOUT: float = _get_float_env("AI_REQUEST_TIMEOUT", 60.0, min_value=1.0, max_value=300.0)
    
    # Alias for backward compatibility with legacy code.
    LLM_TIMEOUT: float = AI_REQUEST_TIMEOUT 
    
    # The maximum number of retry attempts for failed AI requests (e.g., on rate limits).
    AI_MAX_RETRIES: int = _get_int_env("AI_MAX_RETRIES", 3, min_value=0, max_value=10)
    
    # The base delay in seconds for exponential backoff during retries.
    AI_RETRY_BACKOFF_BASE: float = _get_float_env("AI_RETRY_BACKOFF_BASE", 2.0, min_value=0.1, max_value=60.0)

    # --- OCR Settings ---
    OCR_ENABLED: bool = _get_bool_env("OCR_ENABLED", False)
    OCR_LANGUAGES: str = _get_val("OCR_LANGUAGES", "eng+hin")
    OCR_DPI: int = _get_int_env("OCR_DPI", 300, min_value=50, max_value=600)
    
    # --- File Processing ---
    MAX_FILE_SIZE_MB: int = _get_int_env("MAX_FILE_SIZE_MB", 25, min_value=1, max_value=500)
    WARN_FILE_SIZE_MB: int = _get_int_env("WARN_FILE_SIZE_MB", 10, min_value=1, max_value=500)
    TEXT_COMPRESSION_LIMIT: int = _get_int_env("TEXT_COMPRESSION_LIMIT", 6000, min_value=100)
    MAX_DOCUMENT_TEXT_STORAGE_LIMIT: int = _get_int_env("MAX_DOCUMENT_TEXT_STORAGE_LIMIT", 50000, min_value=1000)
    
    # --- Attachments ---
    # Directory where uploaded attachments are stored (development)
    ATTACHMENTS_DIR: str = _get_val("ATTACHMENTS_DIR", str(PROJECT_ROOT / "attachments"))
    # Use randomized filenames to avoid collisions and leaking original names
    ATTACHMENTS_RANDOMIZE_FILENAMES: bool = _get_bool_env("ATTACHMENTS_RANDOMIZE_FILENAMES", True)
    
    # --- Export Settings ---
    # Directory where user data exports are saved (local storage)
    EXPORTS_DIR: str = _get_val("EXPORTS_DIR", str(PROJECT_ROOT / ".exports"))
    # Hours before export files expire and can be deleted
    EXPORT_FILE_EXPIRY_HOURS: int = _get_int_env("EXPORT_FILE_EXPIRY_HOURS", 24, min_value=1, max_value=360)
    # Default privacy redaction profile for anonymized exports and reports
    DEFAULT_PRIVACY_PROFILE: str = _get_val("DEFAULT_PRIVACY_PROFILE", "personal_identifiers")
    # Optional JSON override for privacy profile definitions
    PRIVACY_REDACTION_PROFILES_JSON: str = _get_val("PRIVACY_REDACTION_PROFILES_JSON", "")
    
    # --- Database Settings ---
    DATABASE_URL: str = _get_val("DATABASE_URL", "sqlite:///./legalassist.db")

    # --- Backend API Settings ---
    API_BASE_URL: str = _get_val("API_BASE_URL", "")
    API_REQUEST_TIMEOUT_SECONDS: float = _get_float_env("API_REQUEST_TIMEOUT_SECONDS", 5.0, min_value=0.1, max_value=60.0)
    
    # --- Authentication (JWT & OTP) ---
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = _get_val("JWT_ISSUER", "legalassist.ai")
    JWT_AUDIENCE: str = _get_val("JWT_AUDIENCE", "legalassist-users")
    JWT_EXPIRY_HOURS: int = _get_int_env("JWT_EXPIRY_HOURS", 7 * 24, min_value=1, max_value=365 * 24)
    JWT_SECRET_PREVIOUS: str = _get_val("JWT_SECRET_PREVIOUS", _get_val("JWT_SECRET_KEY_PREVIOUS", _get_val("JWT_SECRET_OLD", "")))
    OTP_EXPIRY_MINUTES: int = _get_int_env("OTP_EXPIRY_MINUTES", 10, min_value=1, max_value=1440)
    OTP_MAX_ATTEMPTS: int = _get_int_env("OTP_MAX_ATTEMPTS", 3, min_value=1, max_value=10)
    OTP_REQUEST_RATE_LIMIT_MAX: int = _get_int_env("OTP_REQUEST_RATE_LIMIT_MAX", 5, min_value=1, max_value=100)
    OTP_REQUEST_RATE_LIMIT_HOURS: int = _get_int_env("OTP_REQUEST_RATE_LIMIT_HOURS", 1, min_value=1, max_value=24)
    
    @classmethod
    def get_jwt_secret(cls) -> str:
        """
        Resolve JWT secret securely.
        
        JWT_SECRET must be provided via environment variable or Streamlit secrets.
        File-based secrets are no longer supported for security.
        
        Returns:
            JWT secret string
            
        Raises:
            RuntimeError: If JWT_SECRET is not configured in environment variables.
        """
        secret = cls.get_current_jwt_secret()
        if secret:
            return secret
        
        env_name = cls.APP_ENV.upper()
        raise RuntimeError(
            f"JWT_SECRET is not configured for the {env_name} environment. "
            "For security, secrets must be explicitly provided via the 'JWT_SECRET' "
            "environment variable. Consider using AWS Secrets Manager or HashiCorp Vault "
            "for production secret management."
        )

    @classmethod
    def get_current_jwt_secret(cls) -> str:
        """
        Return the active JWT signing secret without falling back to placeholders.
        
        Returns:
            JWT secret string (empty string if not configured)
        """
        secret = str(_get_val("JWT_SECRET", _get_val("JWT_SECRET_KEY", _get_val("JWT_SECRET_CURRENT", "")))).strip()
        if not secret and cls.is_production():
            logger.error("JWT_SECRET is not configured in production environment")
        return secret

    @classmethod
    def get_jwt_secrets(cls) -> list[str]:
        """
        Return JWT secrets in verification order: current first, then previous.
        
        Returns:
            List of JWT secrets suitable for token verification
        """
        secrets_to_try = [
            cls.get_current_jwt_secret(),
            str(cls.JWT_SECRET_PREVIOUS).strip(),
        ]
        return [secret for secret in dict.fromkeys(secrets_to_try) if secret and len(secret) >= 16]

    @classmethod
    def get_twilio_auth_token(cls) -> str:
        """
        Return the Twilio auth token, retrieved on demand to limit exposure.
        
        Returns:
            Twilio auth token (empty string if not configured)
        """
        return str(_get_val("TWILIO_AUTH_TOKEN", "") or "")

    @classmethod
    def get_sendgrid_event_webhook_public_key(cls) -> str:
        """
        Return the SendGrid event webhook public key, if configured.
        
        Returns:
            SendGrid webhook public key (empty string if not configured)
        """
        return str(_get_val("SENDGRID_EVENT_WEBHOOK_PUBLIC_KEY", _get_val("SENDGRID_WEBHOOK_PUBLIC_KEY", "")) or "")

    @classmethod
    def get_sendgrid_api_key(cls) -> str:
        """
        Return the SendGrid API key, retrieved on demand to limit exposure.
        
        Returns:
            SendGrid API key (empty string if not configured)
        """
        return str(_get_val("SENDGRID_API_KEY", "") or "")

    @classmethod
    def validate_configuration(cls) -> tuple[bool, list[str]]:
        """
        Validate configuration settings comprehensively.
        
        Returns:
            Tuple of (is_valid: bool, errors: list[str])
        """
        errors = []
        
        # Validate APP_ENV
        if cls.APP_ENV not in VALID_APP_ENVS:
            errors.append(f"APP_ENV={cls.APP_ENV} not in valid values: {VALID_APP_ENVS}")
        
        # Validate LOG_LEVEL
        if cls.LOG_LEVEL.upper() not in VALID_LOG_LEVELS:
            errors.append(f"LOG_LEVEL={cls.LOG_LEVEL} not in valid values: {VALID_LOG_LEVELS}")
        
        # Validate privacy profile
        if cls.DEFAULT_PRIVACY_PROFILE not in VALID_PRIVACY_PROFILES:
            errors.append(
                f"DEFAULT_PRIVACY_PROFILE={cls.DEFAULT_PRIVACY_PROFILE} "
                f"not in valid values: {VALID_PRIVACY_PROFILES}"
            )
        
        # Validate URL formats
        if cls.OPENROUTER_BASE_URL and not _validate_url(cls.OPENROUTER_BASE_URL):
            errors.append(f"OPENROUTER_BASE_URL is not a valid URL: {cls.OPENROUTER_BASE_URL}")
        
        if cls.API_BASE_URL and not _validate_url(cls.API_BASE_URL):
            errors.append(f"API_BASE_URL is not a valid URL: {cls.API_BASE_URL}")
        
        if not _validate_url(cls.BASE_URL):
            errors.append(f"BASE_URL is not a valid URL: {cls.BASE_URL}")
        
        # Validate numeric constraints
        if cls.MAX_FILE_SIZE_MB < cls.WARN_FILE_SIZE_MB:
            errors.append(
                f"MAX_FILE_SIZE_MB ({cls.MAX_FILE_SIZE_MB}) "
                f"cannot be less than WARN_FILE_SIZE_MB ({cls.WARN_FILE_SIZE_MB})"
            )
        
        if cls.TEXT_COMPRESSION_LIMIT > cls.MAX_DOCUMENT_TEXT_STORAGE_LIMIT:
            errors.append(
                f"TEXT_COMPRESSION_LIMIT ({cls.TEXT_COMPRESSION_LIMIT}) "
                f"cannot exceed MAX_DOCUMENT_TEXT_STORAGE_LIMIT ({cls.MAX_DOCUMENT_TEXT_STORAGE_LIMIT})"
            )
        
        return len(errors) == 0, errors

    @classmethod
    def validate_runtime_security(cls) -> None:
        """
        Fail fast when production settings are insecure or missing required secrets.
        
        Raises:
            RuntimeError: If production security requirements are not met
        """
        if cls.is_production() and (cls.DEBUG or cls.TESTING):
            raise RuntimeError("DEBUG and TESTING must be disabled in production")

        if cls.is_production():
            required = {
                "JWT_SECRET": cls.get_current_jwt_secret(),
                "OPENROUTER_API_KEY": str(cls.OPENROUTER_API_KEY).strip(),
                "SENDGRID_API_KEY": cls.get_sendgrid_api_key(),
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise RuntimeError(
                    "Missing required production secrets: " + ", ".join(sorted(missing))
                )

            if cls.REQUIRE_HTTPS:
                if not str(cls.BASE_URL).lower().startswith("https://"):
                    raise RuntimeError("BASE_URL must use https:// in production")
                if cls.API_BASE_URL and not str(cls.API_BASE_URL).lower().startswith("https://"):
                    raise RuntimeError("API_BASE_URL must use https:// in production")

    @classmethod
    def is_development(cls) -> bool:
        """Check if application is in development mode."""
        return cls.APP_ENV in ("dev", "development", "local") or cls.DEBUG or cls.TESTING

    @classmethod
    def is_production(cls) -> bool:
        """Check if application is in production mode."""
        return cls.APP_ENV in ("production", "prod", "live")


import re
import copy

class ConfigSanitizer:
    """
    Utility class to sanitize configuration dictionaries before logging to prevent
    accidental leakage of sensitive credentials like API keys and JWT secrets.
    """
    
    # Patterns for keys that likely contain sensitive data
    SENSITIVE_KEY_PATTERNS = [
        re.compile(r"secret", re.IGNORECASE),
        re.compile(r"key", re.IGNORECASE),
        re.compile(r"token", re.IGNORECASE),
        re.compile(r"password", re.IGNORECASE),
        re.compile(r"pwd", re.IGNORECASE),
        re.compile(r"auth", re.IGNORECASE),
        re.compile(r"credential", re.IGNORECASE),
        re.compile(r"jwt", re.IGNORECASE),
        re.compile(r"sid", re.IGNORECASE),
        re.compile(r"api_?key", re.IGNORECASE),
        re.compile(r"access", re.IGNORECASE),
        re.compile(r"url", re.IGNORECASE),
    ]

    # Keys that we explicitly want to mask
    EXPLICIT_SENSITIVE_KEYS = {
        "DATABASE_URL",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "JWT_SECRET",
        "JWT_SECRET_PREVIOUS",
        "JWT_SECRET_KEY",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "SENDGRID_API_KEY",
    }
    
    @classmethod
    def is_sensitive(cls, key: str) -> bool:
        """
        Determine if a configuration key represents sensitive information.
        """
        if key.upper() in cls.EXPLICIT_SENSITIVE_KEYS:
            return True
            
        for pattern in cls.SENSITIVE_KEY_PATTERNS:
            if pattern.search(key):
                return True
                
        return False
        
    @classmethod
    def mask_string(cls, value: str) -> str:
        """
        Mask a string value.
        - Strings <= 4 chars: completely masked with asterisks
        - Strings 5-8 chars: show 1st char, mask rest, show last char
        - Strings > 8 chars: show 1st 2 chars, mask rest, show last 2 chars
        """
        if not value:
            return value
            
        length = len(value)
        if length <= 4:
            return "*" * length
        elif length <= 8:
            return f"{value[0]}{'*' * (length - 2)}{value[-1]}"
        else:
            return f"{value[:2]}{'*' * (length - 4)}{value[-2:]}"

    @classmethod
    def sanitize_value(cls, value: any) -> any:
        """Sanitize an individual value."""
        if value is None:
            return value
        elif isinstance(value, bool):
            return value
        elif isinstance(value, (int, float)):
            return "***"
        else:
            return cls.mask_string(str(value))

    @classmethod
    def sanitize_dict(cls, config_dict: dict) -> dict:
        """
        Recursively sanitize a dictionary, masking sensitive values.
        Returns a new dictionary; does not mutate the original.
        """
        sanitized = {}
        for k, v in config_dict.items():
            if isinstance(v, dict):
                sanitized[k] = cls.sanitize_dict(v)
            elif cls.is_sensitive(str(k)):
                sanitized[k] = cls.sanitize_value(v)
            else:
                sanitized[k] = v
        return sanitized


def get_config_dict(cls_obj: type) -> dict[str, Any]:
    """
    Extract configuration variables from a Config class object.
    
    Args:
        cls_obj: The Config class to extract from
        
    Returns:
        Dictionary of configuration attributes
    """
    cfg = {}
    for key in dir(cls_obj):
        if key.startswith("_"):
            continue
        val = getattr(cls_obj, key)
        if callable(val) or isinstance(val, (classmethod, staticmethod, property)):
            continue
        cfg[key] = val
    return cfg


def _initialize_config() -> None:
    """
    Perform initialization-time configuration validation and logging.
    Called automatically when the module is loaded.
    """
    # Validate configuration
    is_valid, errors = Config.validate_configuration()
    if not is_valid:
        logger.warning(f"Configuration validation warnings:\n  " + "\n  ".join(errors))
        if Config.is_production():
            logger.error("Configuration validation errors in production:")
            for error in errors:
                logger.error(f"  - {error}")
    
    # Log sanitized config in debug mode
    if Config.DEBUG:
        try:
            raw_config = get_config_dict(Config)
            safe_config = ConfigSanitizer.sanitize_dict(raw_config)
            logger.debug(f"Active Configuration (Sanitized): {safe_config}")
        except Exception as e:
            logger.exception(f"Failed to log sanitized configuration: {e}")
    
    # Perform security validation
    try:
        Config.validate_runtime_security()
        logger.debug(f"Security validation passed for {Config.APP_ENV} environment")
    except RuntimeError as e:
        logger.error(f"Security validation failed: {e}")
        if Config.is_production():
            raise


# Initialize configuration on module load
_initialize_config()

