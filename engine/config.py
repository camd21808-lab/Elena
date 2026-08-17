from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _mojibake_chars(s: str) -> list[str]:
    bad = [c for c in s if ord(c) < 0x20 or 0x80 <= ord(c) <= 0x9F or c == "\ufffd"]
    return [repr(c) for c in dict.fromkeys(bad)]


def _check_path_env(name: str, value: str) -> str:
    bad = _mojibake_chars(value)
    if bad:
        raise RuntimeError(
            f"SCANDE_{name} trong .env chua ky tu encoding hong {bad}: {value!r}\n"
            f"Sua lai .env (phai luu UTF-8), vi du: SCANDE_LOCAL_ROOT=D:\\Đề thi, "
            f"roi khoi dong lai server."
        )
    return value


class Settings:
    domain_allowlist: list[str]
    drive_root: str
    local_root: str
    convert_root: str
    convert_max_mb: int
    soffice_path: str
    job_timeout_seconds: int
    retry_transient: int
    ocr_confidence_warning: float
    temp_ttl_hours: int
    max_concurrent: int
    use_system_chrome: bool
    redis_url: str
    google_client_id: str
    google_client_secret: str
    google_callback_port: int

    def __init__(self) -> None:
        allowlist = os.getenv("SCANDE_DOMAIN_ALLOWLIST", "scribd.com,*.scribd.com,drive.google.com,docs.google.com")
        self.domain_allowlist = [d.strip() for d in allowlist.split(",") if d.strip()]
        self.drive_root = _check_path_env("DRIVE_ROOT", os.getenv("SCANDE_DRIVE_ROOT", ""))
        self.local_root = _check_path_env("LOCAL_ROOT", os.getenv("SCANDE_LOCAL_ROOT", r"D:\Đề thi"))
        self.convert_root = _check_path_env("CONVERT_ROOT", os.getenv("SCANDE_CONVERT_ROOT", r"D:\Chuyen doi"))
        self.convert_max_mb = int(os.getenv("SCANDE_CONVERT_MAX_MB", "50"))
        self.soffice_path = _check_path_env("SOFFICE", os.getenv("SCANDE_SOFFICE", r"C:\Program Files\LibreOffice\program\soffice.exe"))
        self.job_timeout_seconds = int(os.getenv("SCANDE_JOB_TIMEOUT", "600"))
        self.retry_transient = int(os.getenv("SCANDE_RETRY_TRANSIENT", "1"))
        self.ocr_confidence_warning = float(os.getenv("SCANDE_OCR_WARN", "0.5"))
        self.temp_ttl_hours = float(os.getenv("SCANDE_TEMP_TTL_HOURS", "24"))
        self.max_concurrent = int(os.getenv("SCANDE_MAX_CONCURRENT", "2"))
        self.use_system_chrome = _env_bool("SCANDE_SYSTEM_CHROME", True)
        self.redis_url = os.getenv("SCANDE_REDIS_URL", "redis://localhost:6379/0")
        self.google_client_id = os.getenv("SCANDE_GOOGLE_CLIENT_ID", "")
        self.google_client_secret = os.getenv("SCANDE_GOOGLE_CLIENT_SECRET", "")
        self.google_callback_port = int(os.getenv("SCANDE_GOOGLE_CALLBACK_PORT", "8765"))

    def temp_dir(self) -> Path:
        base = Path(_check_path_env("TEMP_DIR", os.getenv("SCANDE_TEMP_DIR", str(Path(self.local_root).parent / "scan-de-temp"))))
        base.mkdir(parents=True, exist_ok=True)
        return base

    def data_dir(self) -> Path:
        """App data root for accounts.db / vault.key / prefs.

        SCANDE_DATA_DIR env, else a `scan-de-data` sibling of the existing
        roots (D:\\scan-de-data by default). library.db keeps its own location.
        """
        env = os.getenv("SCANDE_DATA_DIR")
        if env:
            base = Path(_check_path_env("DATA_DIR", env))
        else:
            base = Path(self.local_root).parent / "scan-de-data"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def local_subject_dir(self, mon: str) -> Path:
        return Path(self.local_root) / mon

    def convert_subject_dir(self, mon: str) -> Path:
        return Path(self.convert_root) / mon


settings = Settings()
