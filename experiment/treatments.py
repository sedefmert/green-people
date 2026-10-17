# This script defines the treatments used in the experiment, along with the corresponding shell commands for compressing and sending data. 
# It also provides utility functions for generating archive names and running shell commands with error handling.
TREATMENTS = ["none", "zip", "tar.gz", "tar.zst", "tar.br"]
COMPRESSING = [t for t in TREATMENTS if t != "none"]

COMPRESS = {
    "zip":     "zip -r -q {archive} {dir}",
    "tar.gz":  "tar -czf {archive} {dir}",
    "tar.zst": "tar -cf - {dir} | zstd -q -c > {archive}",
    "tar.br":  "tar -cf - {dir} | brotli -c > {archive}",
}

# Baseline (uncompressed tar stream)
SEND_BASELINE = "tar -cf - {dir} | nc -N {host} {port}"
SEND_ARCHIVE = "nc -N {host} {port} < {archive}"

PAYLOAD_DIRS = {"S": "wiki_S", "L": "wiki_L"}

# archive name for a treatment
def archive_name(treatment: str) -> str:
    return f"a.{treatment}" 

# Run shell command
def bash(cmd: str) -> list:
    return ["bash", "-o", "pipefail", "-c", cmd]
