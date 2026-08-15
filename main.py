import sys
import time
import threading
import dns.resolver
import requests
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
COUNTRY_NAME_MAP = {
    "US": "United States", "GB": "United Kingdom", "DE": "Germany",
    "FR": "France", "IT": "Italy", "ES": "Spain", "NL": "Netherlands",
    "SE": "Sweden", "NO": "Norway", "DK": "Denmark", "FI": "Finland",
    "IE": "Ireland", "PT": "Portugal", "GR": "Greece", "AT": "Austria",
    "CH": "Switzerland", "BE": "Belgium", "PL": "Poland", "CZ": "Czech Republic",
    "HU": "Hungary", "RO": "Romania", "BG": "Bulgaria", "HR": "Croatia",
    "SI": "Slovenia", "LT": "Lithuania", "LV": "Latvia", "EE": "Estonia",
    "IS": "Iceland", "LU": "Luxembourg", "MT": "Malta", "CY": "Cyprus",
    "SK": "Slovakia", "UA": "Ukraine", "RU": "Russia", "TR": "Turkey",
    "IL": "Israel", "ZA": "South Africa", "AU": "Australia", "NZ": "New Zealand",
    "JP": "Japan", "KR": "South Korea", "IN": "India", "CN": "China",
    "TW": "Taiwan", "HK": "Hong Kong", "SG": "Singapore", "MY": "Malaysia",
    "ID": "Indonesia", "PH": "Philippines", "VN": "Vietnam", "TH": "Thailand",
    "PK": "Pakistan", "BD": "Bangladesh", "LK": "Sri Lanka", "NP": "Nepal",
    "KH": "Cambodia", "MM": "Myanmar", "SA": "Saudi Arabia", "AE": "UAE",
    "KW": "Kuwait", "QA": "Qatar", "BH": "Bahrain", "OM": "Oman",
    "YE": "Yemen", "JO": "Jordan", "LB": "Lebanon", "EG": "Egypt",
    "MA": "Morocco", "DZ": "Algeria", "TN": "Tunisia", "LY": "Libya",
    "SD": "Sudan", "NG": "Nigeria", "KE": "Kenya", "TZ": "Tanzania",
    "UG": "Uganda", "GH": "Ghana", "ZW": "Zimbabwe", "ZM": "Zambia",
    "MW": "Malawi", "MZ": "Mozambique", "AO": "Angola", "CM": "Cameroon",
    "CI": "Ivory Coast", "SN": "Senegal", "ET": "Ethiopia", "SO": "Somalia",
    "RW": "Rwanda", "CA": "Canada", "MX": "Mexico", "BR": "Brazil",
    "AR": "Argentina", "CL": "Chile", "CO": "Colombia", "PE": "Peru",
    "VE": "Venezuela", "EC": "Ecuador", "UY": "Uruguay", "PY": "Paraguay",
    "BO": "Bolivia", "DO": "Dominican Republic", "GT": "Guatemala",
    "SV": "El Salvador", "HN": "Honduras", "NI": "Nicaragua", "CR": "Costa Rica",
    "PA": "Panama", "PR": "Puerto Rico", "CU": "Cuba", "JM": "Jamaica",
}

def get_country_name(code):
    return COUNTRY_NAME_MAP.get(code, code)

# ─── HELPERS ──────────────────────────────────────────────────────────────
def extract_domain(email):
    parts = email.strip().split('@')
    return parts[-1] if len(parts) == 2 else ""

def get_ip_from_domain(domain):
    try:
        answers = dns.resolver.resolve(domain, 'A', lifetime=5)
        return str(answers[0]) if answers else None
    except Exception:
        return None

def get_country_from_ip(ip):
    try:
        resp = requests.get("https://api.country.is/" + ip, timeout=5)
        if resp.status_code == 200:
            return resp.json().get('country', '').upper()
        return ''
    except Exception:
        return ''
def main():
    parser = argparse.ArgumentParser(description="Minimal email country sorter")
    parser.add_argument("-i", "--input", required=True, help="Input file (emails, one per line)")
    parser.add_argument("-o", "--output-dir", default="sorted_emails", help="Output folder")
    parser.add_argument("-t", "--threads", type=int, default=8, help="Number of threads")
    parser.add_argument("--chunk-size", type=int, default=500, help="Chunk size")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[!] File not found: {args.input}")
        sys.exit(1)

    with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
        emails = [line.strip() for line in f if line.strip()]
    if not emails:
        print("[!] No emails found.")
        sys.exit(0)

    total = len(emails)
    print(f"[*] Processing {total} emails...")

    cache = {}
    stats = {'valid': 0, 'invalid': 0, 'dns_fail': 0, 'api_fail': 0}
    stats_lock = threading.Lock()
    results = defaultdict(list)
    country_counts = defaultdict(int)
    results_lock = threading.Lock()

    def process_email(email):
        domain = extract_domain(email)
        if not domain:
            with stats_lock:
                stats['invalid'] += 1
            return None, None

        with stats_lock:
            if domain in cache:
                code = cache[domain]
                if code:
                    stats['valid'] += 1
                    return email, code
                else:
                    stats['dns_fail'] += 1
                    return None, None

        ip = get_ip_from_domain(domain)
        if not ip:
            cache[domain] = None
            with stats_lock:
                stats['dns_fail'] += 1
            return None, None

        code = get_country_from_ip(ip)
        cache[domain] = code
        if code:
            with stats_lock:
                stats['valid'] += 1
            return email, code
        else:
            with stats_lock:
                stats['api_fail'] += 1
            return None, None

    start_time = time.time()

    def process_chunk(chunk):
        local_results = defaultdict(list)
        for email in chunk:
            email, code = process_email(email)
            if code:
                local_results[code].append(email)
                with results_lock:
                    country_counts[code] += 1
        with results_lock:
            for code, ems in local_results.items():
                results[code].extend(ems)

    chunks = [emails[i:i+args.chunk_size] for i in range(0, total, args.chunk_size)]

    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        futures = [executor.submit(process_chunk, chunk) for chunk in chunks]
        for _ in as_completed(futures):
            pass 

    elapsed = time.time() - start_time

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    total_valid = 0
    for code, ems in results.items():
        total_valid += len(ems)
        name = get_country_name(code)
        fname = f"{code}_{name.replace(' ', '_')}.txt"
        with open(output_dir / fname, 'w', encoding='utf-8') as f:
            for email in sorted(ems):
                f.write(email + '\n')
    print(f"[*] Done in {elapsed:.2f}s")
    print(f"[*] Valid emails: {total_valid}")
    print(f"[*] Invalid emails: {stats['invalid']}")
    print(f"[*] DNS failures: {stats['dns_fail']}")
    print(f"[*] API failures: {stats['api_fail']}")
    print(f"[*] Countries: {len(results)}")
    print(f"[*] Output folder: {output_dir}/")
    summary_path = output_dir / "_summary.txt"
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write("# Email Country Sort Summary\n")
        f.write(f"# Input: {args.input}\n")
        f.write(f"# Total: {total}\n")
        f.write(f"# Valid: {total_valid}\n")
        f.write(f"# Invalid: {stats['invalid']}\n")
        f.write(f"# DNS fail: {stats['dns_fail']}\n")
        f.write(f"# API fail: {stats['api_fail']}\n")
        f.write(f"# Time: {elapsed:.2f}s\n")
        f.write("\nCountry Distribution:\n")
        for code, ems in sorted(results.items(), key=lambda x: -len(x[1])):
            f.write(f"  {code}: {len(ems)}\n")


if __name__ == "__main__":    try:
        import dns.resolver
        import requests
    except ImportError as e:
        print(f"[!] Missing dependency: {e}. Install with: pip install dnspython requests")
        sys.exit(1)
    main()
