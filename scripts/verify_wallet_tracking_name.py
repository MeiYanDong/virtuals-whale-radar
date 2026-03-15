import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar


def request_json(opener, method: str, url: str, payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(request) as response:
            body = response.read().decode("utf-8")
            return response.getcode(), json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify tracked wallet name propagates into Overview payload")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--project", default="FIXTURE_TRACKED_WALLET")
    parser.add_argument("--wallet", default="0x1111111111111111111111111111111111111111")
    parser.add_argument("--initial-name", default="Fixture Wallet Alpha")
    parser.add_argument("--renamed-name", default="Fixture Wallet Renamed")
    args = parser.parse_args()

    cookies = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))

    results = []
    status, payload = request_json(
        opener,
        "POST",
        urllib.parse.urljoin(args.base_url, "/api/auth/login"),
        {"email": args.email, "password": args.password},
    )
    results.append({"name": "admin_login", "ok": status == 200, "status": status, "payload": payload})

    params = urllib.parse.urlencode({"project": args.project})
    status, payload = request_json(
        opener,
        "GET",
        urllib.parse.urljoin(args.base_url, f"/api/admin/overview-active?{params}"),
    )
    tracked = payload.get("trackedWallets") or []
    before_name = next((item.get("name") for item in tracked if item.get("wallet") == args.wallet), None)
    results.append(
        {
            "name": "overview_contains_initial_wallet_name",
            "ok": status == 200 and before_name == args.initial_name,
            "status": status,
            "observed_name": before_name,
        }
    )

    status, payload = request_json(
        opener,
        "POST",
        urllib.parse.urljoin(args.base_url, "/api/admin/wallets"),
        {"wallet": args.wallet, "name": args.renamed_name},
    )
    results.append({"name": "rename_wallet", "ok": status == 200, "status": status, "payload": payload})

    status, payload = request_json(
        opener,
        "GET",
        urllib.parse.urljoin(args.base_url, f"/api/admin/overview-active?{params}"),
    )
    tracked = payload.get("trackedWallets") or []
    after_name = next((item.get("name") for item in tracked if item.get("wallet") == args.wallet), None)
    results.append(
        {
            "name": "overview_reflects_renamed_wallet_name",
            "ok": status == 200 and after_name == args.renamed_name,
            "status": status,
            "observed_name": after_name,
        }
    )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item.get("ok") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
