from .protect_pdf import (
    add_password_protection,
    add_watermark,
    preview_redaction,
    protect_file,
    restrict_permissions,
    sanitize_metadata,
    true_redact,
)

__all__ = [
    "protect_file",
    "add_password_protection",
    "restrict_permissions",
    "add_watermark",
    "sanitize_metadata",
    "true_redact",
    "preview_redaction",
]
