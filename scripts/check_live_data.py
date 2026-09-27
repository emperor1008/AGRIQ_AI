"""Real-data verification for the weather and mandi integrations (Phase 7.3).

Run against the REAL providers, not mocks:

    python scripts/check_live_data.py                # weather + market + provider audit
    python scripts/check_live_data.py --weather-only  # skip the market probes

What it proves, honestly
------------------------
* **Weather (Open-Meteo)** — whether a real retrieval works right now, and what
  the provider actually returned for a real location (no credential is needed).
* **Mandi (AGMARKNET via data.gov.in)** — whether this deployment can retrieve
  live official records. Without ``DATA_GOV_IN_API_KEY`` the script prints
  ``CONFIGURATION_BLOCKED`` and shows the provider's own refusal, because AGRIQ
  never substitutes an estimate.
* **Provider audit** — the official keyless surfaces that exist, so the report
  can state *why* live mandi prices need a credential instead of implying the
  integration is simply untested.

Secrets: the configured key is never printed, and never logged. Every request
carries a timeout and a bounded retry count.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from agriq.core.constants import (  # noqa: E402
    DATA_GOV_IN_API_URL,
    DATA_GOV_IN_MARKET_RESOURCE_ID,
)
from agriq.integrations.market import agmarknet  # noqa: E402
from agriq.integrations.weather import open_meteo  # noqa: E402

AGMARKNET_API = "https://api.agmarknet.gov.in/v1"
PROBE_LOCATION = ("Cuttack", 20.4625, 85.883)
RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'INFO'}] {name}: {detail}")


def check_weather() -> None:
    print("\n=== Weather: Open-Meteo (live) ===")
    district, lat, lon = PROBE_LOCATION
    result = open_meteo.get_weather(district, lat=lat, lon=lon, location_source="verification")
    if not result.get("available"):
        record("weather", False,
               f"no live data now - state={result.get('state')} reason={result.get('reason')}")
        return
    freshness = open_meteo.freshness(result, 1800)
    record("weather", True,
           f"{district} {result.get('temp')}°C, humidity {result.get('humidity')}%, "
           f"wind {result.get('wind')} km/h, '{result.get('condition')}'")
    print(f"        provider={result.get('provider')} observed_at={result.get('provider_observed_at')}")
    print(f"        retrieved_at={result.get('retrieved_at')} "
          f"freshness={freshness['freshness_status']} age_s={freshness['age_seconds']}")
    print(f"        coords={result.get('latitude')},{result.get('longitude')} "
          f"location_source={result.get('location_source')}")
    print(f"        hourly rows={len(result.get('hourly') or [])} "
          f"daily rows={len(result.get('daily') or [])}")


def check_invalid_location() -> None:
    """A location AGRIQ cannot resolve must never become another district."""
    print("\n=== Weather: invalid location handling ===")
    result = open_meteo.get_weather("Notarealdistrict")
    ok = result.get("available") is False and result.get("state") == "INVALID_LOCATION"
    record("weather_invalid_location", ok,
           f"state={result.get('state')} reason={result.get('reason')}")


def check_mandi(api_key: str) -> None:
    print("\n=== Mandi: AGMARKNET via data.gov.in (live) ===")
    if not api_key:
        # Show the provider's own answer, so the blocked state is evidenced.
        status, body = _http_probe(
            f"{DATA_GOV_IN_API_URL.format(resource_id=DATA_GOV_IN_MARKET_RESOURCE_ID)}"
            "?format=json&limit=1"
        )
        record("mandi", False,
               "CONFIGURATION_BLOCKED - DATA_GOV_IN_API_KEY is not configured")
        print(f"        provider refusal: HTTP {status} {body[:120]}")
        return

    result = agmarknet.fetch_mandi_prices(
        api_key=api_key, commodity="Paddy(Common)", district="Cuttack", state="Odisha"
    )
    state = result.get("state")
    if result.get("available") and result.get("records"):
        first = result["records"][0]
        record("mandi", True,
               f"{len(result['records'])} official record(s); first: {first['market']} "
               f"{first['commodity']} modal={first['modal_price']} ({first['arrival_date']})")
        print(f"        provider={result.get('provider')} state={state} "
              f"fetched_at={result.get('fetched_at')}")
        print(f"        provider_updated_at={result.get('provider_updated_at')} "
              f"reported_total={result.get('reported_total')}")
        assert api_key not in json.dumps(result), "credential leaked into payload"
    elif result.get("available") and state == "NO_OFFICIAL_RECORD":
        record("mandi", True, "provider answered; no official record for this query")
    else:
        record("mandi", False, f"state={state} reason={result.get('reason')}")


def check_provider_audit() -> None:
    """Document the official keyless surfaces (why a credential is required)."""
    print("\n=== Provider audit: official keyless surfaces ===")
    for name, path in (
        ("agmarknet_reference_filters", "/daily-price-arrival/filters"),
        ("agmarknet_states", "/location/state"),
    ):
        status, body = _http_probe(f"{AGMARKNET_API}{path}")
        # ``body`` is a truncated preview, so no byte count is claimed here.
        detail = f"HTTP {status}"
        if status == 200:
            detail += " - reference data only, no prices"
        else:
            detail += f" - {body[:90]}"
        record(name, status == 200, detail)

    status, body = _http_probe(
        f"{AGMARKNET_API}/daily-price-arrival/report", method="POST",
        payload={"state_id": "26", "from_date": "", "to_date": ""},
    )
    gated = "CAPTCHA" in body.upper() or "TOKEN_OR_CAPTCHA" in body.upper()
    record("agmarknet_price_report", not gated,
           f"HTTP {status} {body[:110]}")
    print("        -> price reports are provider-gated; AGRIQ does not bypass it.")


def _http_probe(url: str, *, method: str = "GET", payload: dict | None = None):
    """Bounded real HTTP probe (no secret is ever sent by this helper)."""
    import urllib.error
    import urllib.request

    data = None
    headers = {"Accept": "application/json", "User-Agent": "AGRIQ-AI/1.0 (verification)"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read()[:400].decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:400].decode("utf-8", "replace")
    except Exception as exc:  # network
        return 0, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weather-only", action="store_true",
                        help="skip the market and provider probes")
    args = parser.parse_args()

    api_key = ""
    for candidate in (REPO_ROOT / ".env", API_ROOT / ".env"):
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith("DATA_GOV_IN_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
    print(f"Configured DATA_GOV_IN_API_KEY: {'yes' if api_key else 'no'}")

    check_weather()
    check_invalid_location()
    if not args.weather_only:
        check_mandi(api_key)
        check_provider_audit()

    print("\n=== Summary ===")
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'INFO'}  {name}")
    failures = [name for name, ok, _ in RESULTS if not ok]
    blocked = [name for name in failures if name == "mandi"]
    if blocked:
        print("\nCONFIGURATION_BLOCKED: live mandi prices need DATA_GOV_IN_API_KEY on this\n"
              "deployment. AGRIQ shows persisted official records and an explicit\n"
              "configuration state instead of inventing a price.")
    print(f"\n{len(RESULTS) - len(failures)}/{len(RESULTS)} checks returned real data.")
    return 1 if [f for f in failures if f != "mandi"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
