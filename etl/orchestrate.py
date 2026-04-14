
import subprocess
import sys

scripts = [
    "etl_sider.py",
    "etl_faers.py",
    "etl_drugbank.py",
    "etl_pubmed.py",
]

for script in scripts:
    print(f"\n{'='*50}")
    print(f"RUNNING {script}")
    print(f"{'='*50}\n")
    result = subprocess.run([sys.executable, "-u", script], check=True)