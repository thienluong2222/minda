import logging
import re


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        text = super().format(record)
        text = re.sub(r"(mongodb(?:\+srv)?://)[^/@\s]+:[^@\s]+@", r"\1[redacted]@", text)
        return re.sub(r"hf_[A-Za-z0-9]{15,}", "[redacted]", text)
